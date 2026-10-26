# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""ClinVar async client via NCBI E-utilities.

ClinVar is the NCBI archive of variants and their clinical interpretations.
This client resolves HGVS expressions to ClinVar variant records, returning
pathogenicity classifications, review status, and associated conditions.

Reference:
  Landrum MJ et al. ClinVar: improvements to accessing data.
  Nucleic Acids Res. 2020;48(D1):D835–D844.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

from alphafold_sovereign.clients._base import BaseAsyncClient, UpstreamConfig
from alphafold_sovereign.domain.disease import PathogenicityClass

logger = structlog.get_logger(__name__)

_CLINVAR_CONFIG = UpstreamConfig(
    base_url="https://eutils.ncbi.nlm.nih.gov",
    calls_per_second=3.0,  # NCBI requests ≤ 3/s without API key; 10/s with
    max_retries=3,
    timeout=20.0,
)

# Mapping ClinVar free-text interpretations → PathogenicityClass enum
_PATHO_MAP: dict[str, PathogenicityClass] = {
    "pathogenic": PathogenicityClass.PATHOGENIC,
    "likely pathogenic": PathogenicityClass.LIKELY_PATHOGENIC,
    "uncertain significance": PathogenicityClass.UNCERTAIN,
    "likely benign": PathogenicityClass.LIKELY_BENIGN,
    "benign": PathogenicityClass.BENIGN,
    "conflicting interpretations of pathogenicity": PathogenicityClass.CONFLICTING,
    "conflicting classifications of pathogenicity": PathogenicityClass.CONFLICTING,
}


def _parse_classification(raw: str) -> PathogenicityClass:
    return _PATHO_MAP.get(raw.lower().strip(), PathogenicityClass.NOT_PROVIDED)


# ClinVar review status → star-quality rank, used only to break ties when more
# than one record matches a query so the best-reviewed record surfaces first
# (higher is better; an unknown or blank status ranks lowest).
_REVIEW_STATUS_RANK: dict[str, int] = {
    "practice guideline": 4,
    "reviewed by expert panel": 3,
    "criteria provided, multiple submitters, no conflicts": 2,
    "criteria provided, conflicting classifications": 1,
    "criteria provided, conflicting interpretations": 1,
    "criteria provided, single submitter": 1,
    "no assertion criteria provided": 0,
}


def _canonical_change(change: str) -> str:
    """Normalise an HGVS change token toward ClinVar's canonical spelling.

    ClinVar renders duplications and deletions without their trailing bases:
    the legacy ``c.5266dupC`` and ``c.68_69delAG`` appear in ClinVar as
    ``c.5266dup`` and ``c.68_69del``. A raw query token therefore never
    substring-matches the canonical record name. Stripping a trailing base run
    after a bare ``dup`` or ``del`` — never ``delins``, whose inserted bases are
    significant — lets the exact record be recognised. Other change forms
    (substitutions, protein changes, ``delins``) pass through unchanged.
    """
    return re.sub(r"(dup|del)[acgt]+$", r"\1", change.strip().lower())


# Transcript accession identity requires the full RefSeq accession *and*
# version. ClinVar may print a newer transcript than the caller supplied;
# equivalence of c./n. coordinates across versions requires a separate mapping.
# Protein/genomic accessions (NP_, NC_, NG_, ...) cannot be checked against
# a title that displays a nucleotide transcript and must not be treated as exact.
_TRANSCRIPT_ACCESSION_PREFIXES = ("nm_", "nr_", "xm_", "xr_")


def _query_reference(prefix: str) -> tuple[str, str] | None:
    """Parse a lower-cased ``(versioned_accession, gene)`` reference.

    ``BRCA1`` yields only a gene, ``NM_007294.3`` only an accession and
    ``NM_007294.4(BRCA1)`` both. Preserve the accession version: silently
    replacing ``.3`` with ``.4`` cannot establish variant identity. ``None``
    means an unparseable prefix.
    """
    prefix = prefix.strip().lower()
    if not prefix:
        return None
    # Same accession test as _build_search_term: RefSeq accessions carry an
    # underscore; gene symbols do not.
    if not re.match(r"[a-z]{2}_\d", prefix):
        return ("", prefix)
    ref = re.fullmatch(r"([a-z]{2}_\d+(?:\.\d+)?)(?:\(([^()\s]+)\))?", prefix)
    if ref is None:
        return None
    return (ref.group(1), ref.group(2) or "")


class ClinVarClient(BaseAsyncClient):
    """
    Async client for ClinVar variant interpretation data.

    Uses the NCBI E-utilities JSON API.  Set ``NCBI_API_KEY`` environment
    variable to raise rate limit from 3 to 10 req/s.
    """

    upstream_name = "clinvar"
    config = _CLINVAR_CONFIG

    def __init__(self, *, ncbi_api_key: str = "", **kwargs: Any) -> None:
        import os

        self._api_key = ncbi_api_key or os.environ.get("NCBI_API_KEY", "")
        if self._api_key:
            self.config = UpstreamConfig(
                base_url=_CLINVAR_CONFIG.base_url,
                calls_per_second=10.0,
                max_retries=3,
                timeout=20.0,
            )
        super().__init__(**kwargs)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search_by_hgvs(self, hgvs: str) -> list[dict[str, Any]]:
        """Search ClinVar for variants matching an HGVS expression.

        Args:
            hgvs: HGVS nucleotide or protein expression,
                e.g. ``'NM_007294.3:c.181T>G'`` or ``'BRCA1:c.181T>G'``.

        Returns:
            Ranked variant summary dicts. ``exact_change_match`` is true only
            for identical changes on an explicit versioned transcript. A
            gene-relative match is ``candidate_change_match`` only: its
            ClinVar classification is NOT yet attributable to the input
            allele. Use ``get_variant`` for more detail, not as proof of
            cross-transcript equivalence.
        """
        params: dict[str, Any] = {
            "db": "clinvar",
            "term": self._build_search_term(hgvs),
            "retmode": "json",
            "retmax": 10,
        }
        if self._api_key:
            params["api_key"] = self._api_key
        data = await self._get("/entrez/eutils/esearch.fcgi", params=params)
        ids = data.get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        summaries = await self._fetch_summaries(ids)
        # The gene-scoped search also returns nearby variants; rank the exact
        # change match first so callers can take row[0]. Matching is done on the
        # canonicalised change token (ClinVar renders c.5266dupC as c.5266dup),
        # and ties are broken by review-status quality so an expert-panel record
        # wins over a single-submitter one. Without this, a legacy dup/del
        # spelling matched nothing and row[0] fell back to an arbitrary hit.
        summaries.sort(key=lambda s: self._match_rank_key(hgvs, s))
        # Search similarity is NOT variant identity. A gene-relative c./p.
        # token can match titles from distinct transcripts (and a deletion's
        # omitted reference bases require sequence validation). Preserve such
        # rows for discovery, but never stamp them as an exact variant.
        for row in summaries:
            confidence = self._match_confidence(hgvs, row)
            row["exact_change_match"] = confidence == "exact_transcript"
            row["candidate_change_match"] = confidence == "candidate_text"
            row["identity_status"] = confidence
        return summaries

    async def get_variant(self, variation_id: str) -> dict[str, Any]:
        """Fetch a ClinVar variant by its numeric variation ID.

        Args:
            variation_id: ClinVar variation ID as string, e.g. ``'12375'``.

        Returns:
            Parsed variant dict with keys:
            ``variation_id``, ``name``, ``gene_symbol``, ``classification``,
            ``review_status``, ``conditions``, ``molecular_consequence``,
            ``last_evaluated``.
        """
        summaries = await self._fetch_summaries([variation_id])
        if not summaries:
            raise KeyError(f"ClinVar variation not found: {variation_id}")
        return summaries[0]

    async def search_gene(self, gene_symbol: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """Fetch pathogenic / likely-pathogenic variants for a gene.

        Args:
            gene_symbol: HGNC gene symbol, e.g. ``'BRCA1'``.
            limit: Maximum variants to return.

        Returns:
            List of variant summary dicts filtered to P/LP.
        """
        params: dict[str, Any] = {
            "db": "clinvar",
            "term": (
                f"{gene_symbol}[Gene Name] AND "
                '("pathogenic"[Significance] OR "likely pathogenic"[Significance])'
            ),
            "retmode": "json",
            "retmax": min(limit, 200),
        }
        if self._api_key:
            params["api_key"] = self._api_key
        data = await self._get("/entrez/eutils/esearch.fcgi", params=params)
        ids = data.get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        return await self._fetch_summaries(ids[:limit])

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _build_search_term(hgvs: str) -> str:
        """Translate an HGVS expression into a robust ClinVar esearch term.

        ClinVar's ``[Variant Name]`` field only matches the database's own
        canonical names such as ``NM_007294.4(BRCA1):c.181T>G``. A
        gene-relative expression never matches that field, and a pinned
        RefSeq version (``NM_007294.3`` against the current ``.4``) silently
        misses. When the prefix is a gene symbol we query
        ``<gene>[gene] AND <change>``, which is robust to RefSeq version
        drift; a bare RefSeq prefix carries no gene token, so we fall back
        to a free-text search of the whole expression.
        """
        if ":" not in hgvs:
            return hgvs
        prefix, _, change = hgvs.partition(":")
        prefix, change = prefix.strip(), change.strip()
        # RefSeq accessions (NM_, NP_, NC_, NG_, XM_, ...) carry an
        # underscore; gene symbols do not.
        if re.match(r"[A-Z]{2}_\d", prefix, re.IGNORECASE):
            return hgvs
        return f"{prefix}[gene] AND {change}"

    @staticmethod
    def _match_reference_parts(
        hgvs: str, summary: dict[str, Any]
    ) -> tuple[str, str, str, str, str] | None:
        """Require compatible RefSeq and gene context before comparing changes."""
        prefix, sep, change = hgvs.partition(":")
        reference = _query_reference(prefix) if sep and change.strip() else None
        if reference is None:
            return None
        accession, gene = reference
        # The current title parser does not establish protein or genomic
        # accession identity, and transcript versions must be explicit.
        if accession and (
            not accession.startswith(_TRANSCRIPT_ACCESSION_PREFIXES)
            or re.fullmatch(r"[a-z]{2}_\d+\.\d+", accession) is None
        ):
            return None
        name = str(summary.get("name", "")).strip().lower()
        title = re.match(r"^([a-z]{2}_\d+(?:\.\d+)?)(?:\(([^()\s]+)\))?:(\S+)", name)
        if title is None:
            return None
        record_accession, record_gene, primary_change = title.groups()
        if (gene and gene != record_gene) or (accession and accession != record_accession):
            return None
        return accession, record_accession, change.strip().lower(), primary_change, name

    @staticmethod
    def _match_nucleotide_change(requested_change: str, primary_change: str, accession: str) -> str:
        """Match literal nucleotide text without inferring deleted-base identity."""
        if _canonical_change(primary_change) != _canonical_change(requested_change):
            return "unmatched"
        # Optional deletion/duplication bases are useful for discovery, but
        # omitted bases in an upstream title require reference verification.
        explicit_query = re.fullmatch(r"(.+(?:dup|del))([acgt]+)", requested_change)
        explicit_record = re.fullmatch(r"(.+(?:dup|del))([acgt]+)", primary_change)
        if (
            explicit_query
            and explicit_record
            and explicit_query.groups() != explicit_record.groups()
        ):
            return "unmatched"
        return (
            "exact_transcript"
            if accession and primary_change == requested_change
            else "candidate_text"
        )

    @staticmethod
    def _match_confidence(hgvs: str, summary: dict[str, Any]) -> str:
        """Identify literal same-version transcript matches; otherwise abstain.

        Gene-relative expressions and protein annotations only discover
        candidates. Matching canonical text is not cross-transcript or
        patient-level allele equivalence, nor a clinical interpretation.
        """
        parts = ClinVarClient._match_reference_parts(hgvs, summary)
        if parts is None:
            return "unmatched"
        accession, record_accession, requested_change, primary_change, name = parts
        if requested_change.startswith(("c.", "n.", "r.")):
            if not record_accession.startswith(_TRANSCRIPT_ACCESSION_PREFIXES):
                return "unmatched"
            return ClinVarClient._match_nucleotide_change(
                requested_change, primary_change, accession
            )
        if requested_change.startswith("p.") and re.search(
            r"\(\s*" + re.escape(requested_change) + r"\s*\)", name
        ):
            # A secondary protein annotation is not a verified reference allele.
            return "candidate_text"
        return "unmatched"

    @staticmethod
    def _is_exact_match(hgvs: str, summary: dict[str, Any]) -> bool:
        """True only for a literal change on an identical, versioned transcript.

        This is a transcript-expression match, not an independently validated
        clinical allele normalization or cross-transcript equivalence claim.
        """
        return ClinVarClient._match_confidence(hgvs, summary) == "exact_transcript"

    @classmethod
    def _match_rank_key(cls, hgvs: str, summary: dict[str, Any]) -> tuple[bool, bool, int]:
        """Put exact transcript expressions first, then same-text candidates.

        Rank by review quality only WITHIN each match-confidence tier. Never
        let an unrelated expert-panel record outrank a lower-review candidate.
        """
        confidence = cls._match_confidence(hgvs, summary)
        review_rank = _REVIEW_STATUS_RANK.get(str(summary.get("review_status", "")).lower(), 0)
        return (confidence == "unmatched", confidence != "exact_transcript", -review_rank)

    async def _fetch_summaries(self, ids: list[str]) -> list[dict[str, Any]]:
        """Batch-fetch esummary records for a list of variation IDs."""
        params: dict[str, Any] = {
            "db": "clinvar",
            "id": ",".join(ids),
            "retmode": "json",
        }
        if self._api_key:
            params["api_key"] = self._api_key
        data = await self._get("/entrez/eutils/esummary.fcgi", params=params)
        result_map = data.get("result", {})
        parsed: list[dict[str, Any]] = []
        for vid in ids:
            raw = result_map.get(vid)
            if not isinstance(raw, dict):
                continue
            parsed.append(self._parse_summary(raw))
        return parsed

    @staticmethod
    def _parse_summary(raw: dict[str, Any]) -> dict[str, Any]:
        var_id = str(raw.get("uid", ""))
        name = raw.get("title", "")
        gene_info = (raw.get("gene_sort") or "").split(";")
        gene_symbol = gene_info[0].strip() if gene_info else ""

        # Clinical significance (may be nested)
        germline = raw.get("germline_classification") or {}
        clinical_sig = germline.get("description", "") or raw.get("clinical_significance", {}).get(
            "description", ""
        )

        review_status = germline.get("review_status", "") or raw.get(
            "clinical_significance", {}
        ).get("review_status", "")

        # Conditions
        conditions: list[str] = []
        for cond in raw.get("trait_set", []):
            trait_name = cond.get("trait_name", "")
            if trait_name:
                conditions.append(trait_name)

        # Molecular consequence. ``variation_set`` may be absent OR present but
        # empty ([]); ``or [{}]`` covers both so the [0] index never raises.
        mol_cons: list[str] = []
        variation_set = raw.get("variation_set") or [{}]
        for loc in variation_set[0].get("variation_loc", []):
            mc = loc.get("molecular_consequence", "")
            if mc:
                mol_cons.append(mc)

        return {
            "variation_id": var_id,
            "name": name,
            "gene_symbol": gene_symbol,
            "classification": _parse_classification(clinical_sig).value,
            "review_status": review_status,
            "conditions": conditions,
            "molecular_consequence": list(set(mol_cons)),
            "last_evaluated": (germline.get("last_evaluated") or ""),
        }
