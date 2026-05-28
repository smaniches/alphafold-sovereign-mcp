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

from typing import Any

import structlog

from alphafold_sovereign.clients._base import BaseAsyncClient, UpstreamConfig
from alphafold_sovereign.domain.disease import TargetEvidenceScore

logger = structlog.get_logger(__name__)

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
query UniProtToEnsembl($uniprotId: String!) {
  search(queryString: $uniprotId, entityNames: ["target"]) {
    hits { id entity name }
  }
}
"""


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
            tractable = any(t.get("value", False) for t in (target.get("tractability") or []))
            dt = self._datatype_scores(row.get("datatypeScores", []))
            scores.append(
                TargetEvidenceScore(
                    target_ensembl_id=ensembl,
                    target_gene_symbol=symbol,
                    uniprot_id=uniprot,
                    disease_mondo_id=disease_id,
                    disease_name=disease_name,
                    overall_score=float(row.get("score", 0.0)),
                    genetic_association=dt.get("genetic_association", 0.0),
                    somatic_mutation=dt.get("somatic_mutation", 0.0),
                    known_drug=dt.get("known_drug", 0.0),
                    affected_pathway=dt.get("affected_pathway", 0.0),
                    literature=dt.get("literature", 0.0),
                    animal_model=dt.get("animal_model", 0.0),
                    rna_expression=dt.get("rna_expression", 0.0),
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
        return {
            "drug_count": (target.get("drugAndClinicalCandidates") or {}).get("count", 0),
            "tractability_labels": [
                t.get("label", "") for t in (target.get("tractability") or []) if t.get("value")
            ],
        }

    # ------------------------------------------------------------------
    # UniProt / symbol -> Ensembl target resolution
    # ------------------------------------------------------------------

    async def resolve_target(self, query: str) -> dict[str, str]:
        """Resolve a UniProt accession or gene symbol to an Open Targets target.

        Open Targets keys all target data on Ensembl gene IDs. This helper
        uses the Open Targets full-text search index (which indexes gene
        symbols, names, and UniProt cross-references) to map a UniProt
        accession or symbol to its Ensembl gene ID and approved symbol.

        Args:
            query: UniProt accession (e.g. ``'P01116'``) or gene symbol.

        Returns:
            Dict with ``ensembl_id`` and ``symbol``; empty dict if no
            target hit is found.
        """
        data = await self._graphql(
            self._GQL_PATH,
            _UNIPROT_TO_ENSEMBL_QUERY,
            {"uniprotId": query},
        )
        hits = (data.get("search") or {}).get("hits") or []
        for hit in hits:
            if hit.get("entity") == "target" and hit.get("id"):
                return {"ensembl_id": hit["id"], "symbol": hit.get("name", "")}
        return {}

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
        return {r["id"]: float(r.get("score", 0.0)) for r in rows}

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
            disease_mondo_id=disease.get("id", ""),
            disease_name=disease.get("name", ""),
            overall_score=float(row.get("score", 0.0)),
            genetic_association=dt.get("genetic_association", 0.0),
            somatic_mutation=dt.get("somatic_mutation", 0.0),
            known_drug=dt.get("known_drug", 0.0),
            affected_pathway=dt.get("affected_pathway", 0.0),
            literature=dt.get("literature", 0.0),
            animal_model=dt.get("animal_model", 0.0),
            rna_expression=dt.get("rna_expression", 0.0),
        )
