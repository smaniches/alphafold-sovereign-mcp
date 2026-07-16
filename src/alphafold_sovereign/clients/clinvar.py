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
            List of raw variant summary dicts.  Use ``get_variant`` to
            fetch full details for a specific variation ID.
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
        change = hgvs.partition(":")[2]
        summaries.sort(key=lambda s: self._match_rank_key(change, s))
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
    def _match_rank_key(change: str, summary: dict[str, Any]) -> tuple[bool, int]:
        """Rank a candidate summary for ``search_by_hgvs`` ordering.

        Sorts an exact change match ahead of nearby variants, then prefers the
        better-reviewed record. The key is ``(not exact, -review_rank)`` so that
        Python's ascending, stable sort puts exact matches first, the highest
        review status next, and preserves the upstream order for genuine ties.
        """
        canon = _canonical_change(change)
        name = str(summary.get("name", "")).lower()
        exact = bool(canon) and re.search(re.escape(canon) + r"(?![0-9a-z])", name) is not None
        review_rank = _REVIEW_STATUS_RANK.get(str(summary.get("review_status", "")).lower(), 0)
        return (not exact, -review_rank)

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
