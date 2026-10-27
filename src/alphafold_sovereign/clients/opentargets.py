# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""Open Targets Platform async GraphQL client.

Provides disease-target evidence scores, drug tractability, and
associated diseases for a given target gene or UniProt accession.

Reference:
  Ochoa D et al. Open Targets Platform: supporting systematic drug–target
  identification and prioritisation.  Nucleic Acids Res. 2021;49(D1):D1302–D1310.
  https://platform.opentargets.org
"""

from __future__ import annotations

import math
from typing import Any

import structlog

from alphafold_sovereign.clients._base import BaseAsyncClient, UpstreamConfig
from alphafold_sovereign.domain.disease import TargetEvidenceScore

logger = structlog.get_logger(__name__)


def _observed_score(value: Any) -> float:
    """Only explicit valid Open Targets scores are scientific observations."""
    if value is None or isinstance(value, bool):
        raise ValueError("Open Targets score is missing or invalid")
    try:
        score = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Open Targets score is not numeric") from exc
    if not math.isfinite(score) or not 0 <= score <= 1:
        raise ValueError("Open Targets score must be finite and between 0 and 1")
    return score


_OT_CONFIG = UpstreamConfig(
    base_url="https://api.platform.opentargets.org",
    calls_per_second=5.0,
    max_retries=3,
    timeout=30.0,
    headers={"Content-Type": "application/json"},
)

# ── GraphQL queries ────────────────────────────────────────────────────────

_ASSOCIATED_DISEASES_QUERY = """
query AssociatedDiseases($ensemblId: String!, $page: Pagination!) {
  target(ensemblId: $ensemblId) {
    id
    approvedSymbol
    proteinIds { id source }
    associatedDiseases(page: $page) {
      rows {
        disease {
          id
          name
        }
        score
        datatypeScores {
          id
          score
        }
      }
    }
  }
}
"""

_DISEASE_TARGETS_QUERY = """
query DiseaseTargets($efoId: String!, $page: Pagination!) {
  disease(efoId: $efoId) {
    id
    name
    associatedTargets(page: $page) {
      rows {
        target {
          id
          approvedSymbol
          proteinIds { id source }
          tractability {
            label
            modality
            value
          }
        }
        score
        datatypeScores {
          id
          score
        }
      }
    }
  }
}
"""

_DRUG_COUNT_QUERY = """
query TargetDrugs($ensemblId: String!) {
  target(ensemblId: $ensemblId) {
    id
    drugAndClinicalCandidates { count }
    tractability {
      label
      modality
      value
    }
  }
}
"""

_UNIPROT_TO_ENSEMBL_QUERY = """
query MapTargetIdentity($q: String!) {
  mapIds(queryTerms: [$q], entityNames: ["target"]) {
    mappings {
      hits {
        id
        name
        object {
          ... on Target {
            id
            approvedSymbol
            proteinIds { id source }
          }
        }
      }
    }
  }
}
"""

_DISEASE_SEARCH_QUERY = """
query DiseaseSearch($q: String!) {
  search(queryString: $q, entityNames: ["disease"]) {
    hits { id entity name }
  }
}
"""


def _to_curie(raw: object) -> str:
    """Return an ontology disease id in canonical colon-form CURIE.

    Open Targets keys and returns disease ids in underscore form (e.g.
    ``MONDO_0007254``, ``EFO_0000305``); the conventional CURIE form uses a
    colon. Replace only the first ``_`` separating an alphabetic prefix from the
    local id. Ids already in colon form, or without an alphabetic prefix, pass
    through unchanged; a ``None`` / empty / non-string id (e.g. a null upstream
    value, since ``disease.get("id")`` is ``None`` when the key is present but
    null) collapses to ``""``. The function is therefore idempotent and never
    raises on a malformed upstream payload.
    """
    if not isinstance(raw, str) or not raw:
        return ""
    prefix, sep, local = raw.partition("_")
    if sep and prefix.isalpha() and local:
        return f"{prefix}:{local}"
    return raw


class OpenTargetsClient(BaseAsyncClient):
    """
    Async GraphQL client for Open Targets Platform.

    All disease IDs in Open Targets use EFO/MONDO notation;  MONDO IDs are
    generally accepted as Open Targets disease IDs (they map EFO → MONDO).
    """

    upstream_name = "open_targets"
    config = _OT_CONFIG

    _GQL_PATH = "/api/v4/graphql"

    # ------------------------------------------------------------------
    # Target → diseases
    # ------------------------------------------------------------------

    async def associated_diseases(
        self,
        ensembl_id: str,
        *,
        limit: int = 20,
    ) -> list[TargetEvidenceScore]:
        """Return the top diseases associated with a target (by evidence score).

        Args:
            ensembl_id: Ensembl gene ID, e.g. ``'ENSG00000012048'`` (BRCA1).
            limit: Maximum disease associations to return.

        Returns:
            List of ``TargetEvidenceScore`` sorted by overall score descending.
            Missing datatype components remain None rather than measured zero.
        """
        limit = max(1, min(limit, 200))
        data = await self._graphql(
            self._GQL_PATH,
            _ASSOCIATED_DISEASES_QUERY,
            {"ensemblId": ensembl_id, "page": {"index": 0, "size": limit}},
        )
        target = data.get("target") or {}
        symbol: str = target.get("approvedSymbol", "")
        uniprot_id = self._extract_uniprot(target.get("proteinIds", []))
        rows = target.get("associatedDiseases", {}).get("rows", [])
        return [self._row_to_score(r, ensembl_id, symbol, uniprot_id) for r in rows]

    # ------------------------------------------------------------------
    # Disease → targets
    # ------------------------------------------------------------------

    async def associated_targets(
        self,
        disease_id: str,
        *,
        limit: int = 20,
    ) -> list[TargetEvidenceScore]:
        """Return the top protein targets associated with a disease.

        Args:
            disease_id: Open Targets / EFO / MONDO disease ID, in either
                colon or underscore form, e.g. ``'MONDO:0007254'`` or
                ``'MONDO_0007254'`` (breast carcinoma).
            limit: Maximum target associations to return.

        Returns:
            List of ``TargetEvidenceScore`` sorted by overall score descending.
            Missing datatype components remain None rather than measured zero.
        """
        limit = max(1, min(limit, 200))
        # Open Targets keys disease records on underscore-form CURIEs
        # (e.g. MONDO_0007254, EFO_0000305). Normalise the conventional
        # colon form so callers may pass either; underscore input is a no-op.
        efo_id = disease_id.replace(":", "_")
        data = await self._graphql(
            self._GQL_PATH,
            _DISEASE_TARGETS_QUERY,
            {"efoId": efo_id, "page": {"index": 0, "size": limit}},
        )
        disease = data.get("disease") or {}
        disease_name: str = disease.get("name", "")
        rows = disease.get("associatedTargets", {}).get("rows", [])
        scores: list[TargetEvidenceScore] = []
        for row in rows:
            target = row.get("target", {})
            ensembl = target.get("id", "")
            symbol = target.get("approvedSymbol", "")
            uniprot = self._extract_uniprot(target.get("proteinIds", []))
            tractability = target.get("tractability")
            tractable: bool | None = None
            if isinstance(tractability, list):
                tractable = any(t.get("value") is True for t in tractability)
            dt = self._datatype_scores(row.get("datatypeScores", []))
            scores.append(
                TargetEvidenceScore(
                    target_ensembl_id=ensembl,
                    target_gene_symbol=symbol,
                    uniprot_id=uniprot,
                    disease_mondo_id=_to_curie(disease_id),
                    disease_name=disease_name,
                    overall_score=_observed_score(row.get("score")),
                    genetic_association=dt.get("genetic_association"),
                    somatic_mutation=dt.get("somatic_mutation"),
                    known_drug=dt.get("known_drug"),
                    affected_pathway=dt.get("affected_pathway"),
                    literature=dt.get("literature"),
                    animal_model=dt.get("animal_model"),
                    rna_expression=dt.get("rna_expression"),
                    tractable=tractable,
                )
            )
        return sorted(scores, key=lambda s: s.overall_score, reverse=True)

    # ------------------------------------------------------------------
    # Drug tractability
    # ------------------------------------------------------------------

    async def drug_count_and_tractability(self, ensembl_id: str) -> dict[str, Any]:
        """Return known drug count and tractability labels for a target.

        Args:
            ensembl_id: Ensembl gene ID.

        Returns:
            Dict with ``drug_count`` and ``tractability_labels`` list.
        """
        data = await self._graphql(
            self._GQL_PATH,
            _DRUG_COUNT_QUERY,
            {"ensemblId": ensembl_id},
        )
        target = data.get("target") or {}
        candidates = target.get("drugAndClinicalCandidates") or {}
        # A missing target/field is not an observed count of zero.
        count = candidates.get("count")
        if count is not None and (
            not isinstance(count, int) or isinstance(count, bool) or count < 0
        ):
            raise ValueError("Open Targets drug count must be a nonnegative integer")
        return {
            "drug_count": count,
            "tractability_labels": [
                t.get("label", "") for t in (target.get("tractability") or []) if t.get("value")
            ],
        }

    # ------------------------------------------------------------------
    # UniProt / symbol -> Ensembl target resolution
    # ------------------------------------------------------------------

    async def resolve_target(self, query: str) -> dict[str, str]:
        """Resolve an exact UniProt accession or approved gene symbol to a target.

        Open Targets free-text search ranks plausible candidates; its first hit
        is not proof of identity. Use the documented identifier mapping service
        and verify accession protein cross-references or exact approved symbols.
        Refuse ambiguous mappings rather than guessing.
        """
        key = query.strip().upper()
        data = await self._graphql(
            self._GQL_PATH,
            _UNIPROT_TO_ENSEMBL_QUERY,
            {"q": key},
        )
        mapped = data.get("mapIds")
        mappings = mapped.get("mappings") if isinstance(mapped, dict) else None
        if not isinstance(mappings, list) or len(mappings) != 1:
            raise ValueError("Open Targets mapIds response is missing a valid mapping")
        entry = mappings[0]
        hits = entry.get("hits") if isinstance(entry, dict) else None
        if not isinstance(hits, list):
            raise ValueError("Open Targets mapIds hits must be a list")

        # Check the approved-symbol and protein-accession namespaces together.
        # A valid approved gene symbol may resemble a UniProt accession.
        candidates: dict[str, str] = {}
        for hit in hits:
            if not isinstance(hit, dict):
                raise ValueError("Open Targets target mapping contains a malformed hit")
            target = hit.get("object")
            if not isinstance(target, dict):
                continue
            ensembl = target.get("id")
            symbol = target.get("approvedSymbol")
            if (
                not isinstance(ensembl, str)
                or not ensembl.startswith("ENSG")
                or hit.get("id") != ensembl
                or not isinstance(symbol, str)
            ):
                continue
            protein_ids = target.get("proteinIds")
            accession_match = isinstance(protein_ids, list) and any(
                isinstance(p, dict) and p.get("id") == key for p in protein_ids
            )
            symbol_match = symbol.casefold() == key.casefold()
            if accession_match or symbol_match:
                candidates[ensembl] = symbol

        if len(candidates) > 1:
            raise ValueError("Open Targets target mapping is ambiguous")
        if not candidates:
            return {}
        ensembl_id, symbol = next(iter(candidates.items()))
        return {"ensembl_id": ensembl_id, "symbol": symbol}

    async def resolve_disease_efo(self, query: str) -> str:
        """Resolve only one exact EFO name or ID, never a relevance-ranked guess.

        Search ranking alone cannot establish a disease identity. Unknown or
        ambiguous aliases require an explicit ontology cross-reference.
        """
        data = await self._graphql(self._GQL_PATH, _DISEASE_SEARCH_QUERY, {"q": query})
        hits = ((data or {}).get("search") or {}).get("hits") or []
        key = query.strip().casefold().replace("_", ":")
        matches = {
            hit["id"]
            for hit in hits
            if isinstance(hit, dict)
            and hit.get("entity") == "disease"
            and isinstance(hit.get("id"), str)
            and hit["id"].startswith("EFO_")
            and (
                str(hit.get("name", "")).strip().casefold() == key
                or hit["id"].replace("_", ":").casefold() == key
            )
        }
        return next(iter(matches)).replace("_", ":") if len(matches) == 1 else ""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_uniprot(protein_ids: list[dict[str, str]]) -> str:
        for p in protein_ids:
            if p.get("source", "").lower() in {"uniprot_swissprot", "uniprot_trembl", "uniprot"}:
                return p.get("id", "")
        return ""

    @staticmethod
    def _datatype_scores(rows: list[dict[str, Any]]) -> dict[str, float]:
        if not isinstance(rows, list):
            raise ValueError("Open Targets datatypeScores must be an array")
        result: dict[str, float] = {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                raise ValueError("Open Targets datatype score has invalid identity")
            result[row["id"]] = _observed_score(row.get("score"))
        return result

    @staticmethod
    def _row_to_score(
        row: dict[str, Any],
        ensembl_id: str,
        symbol: str,
        uniprot_id: str,
    ) -> TargetEvidenceScore:
        disease = row.get("disease", {})
        dt = OpenTargetsClient._datatype_scores(row.get("datatypeScores", []))
        return TargetEvidenceScore(
            target_ensembl_id=ensembl_id,
            target_gene_symbol=symbol,
            uniprot_id=uniprot_id,
            disease_mondo_id=_to_curie(disease.get("id", "")),
            disease_name=disease.get("name", ""),
            overall_score=_observed_score(row.get("score")),
            genetic_association=dt.get("genetic_association"),
            somatic_mutation=dt.get("somatic_mutation"),
            known_drug=dt.get("known_drug"),
            affected_pathway=dt.get("affected_pathway"),
            literature=dt.get("literature"),
            animal_model=dt.get("animal_model"),
            rna_expression=dt.get("rna_expression"),
        )
