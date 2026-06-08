# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""Human Phenotype Ontology (HPO) async client.

Data sources:
- HPO REST API (ontology.jax.org)  — phenotype terms, disease-phenotype links
- OLS4 REST API                    — hierarchy traversal fallback

HPO provides a standardised vocabulary for describing human disease
phenotypes.  It is the canonical ontology for rare-disease phenotyping,
clinical genetics, and EHR phenotyping.

Reference:
  Köhler S et al. The Human Phenotype Ontology in 2021.
  Nucleic Acids Res. 2021;49(D1):D1207–D1217.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import structlog

from alphafold_sovereign.clients._base import BaseAsyncClient, UpstreamConfig
from alphafold_sovereign.domain.disease import OntologyTerm, PhenotypeAssociation

logger = structlog.get_logger(__name__)

_HPO_BASE = "https://ontology.jax.org/api"
_HPO_CONFIG = UpstreamConfig(
    base_url=_HPO_BASE,
    calls_per_second=5.0,
    max_retries=3,
    timeout=20.0,
)

_OLS4_BASE = "https://www.ebi.ac.uk/ols4/api"
_OLS4_HPO_CONFIG = UpstreamConfig(
    base_url=_OLS4_BASE,
    calls_per_second=3.0,
    max_retries=3,
    timeout=20.0,
)

_HPO_CURIE_RE = re.compile(r"^HP:\d{7}$", re.IGNORECASE)


def _normalise_hpo_id(raw: str) -> str:
    raw = raw.strip()
    if re.match(r"^\d{7}$", raw):
        return f"HP:{raw}"
    return raw.upper().replace("HP_", "HP:")


@dataclass
class DiseaseByPhenotype:
    """A disease associated with a given HPO term."""

    disease_id: str
    """OMIM or Orphanet ID, e.g. 'OMIM:114480'."""
    disease_name: str
    hpo_id: str
    hpo_label: str = ""
    mondo_id: str = ""
    """Cross-referenced MONDO ID, e.g. 'MONDO:0007254' (when provided by HPO)."""
    frequency: str = ""
    onset: str = ""
    sex: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "disease_id": self.disease_id,
            "disease_name": self.disease_name,
            "hpo_id": self.hpo_id,
            "hpo_label": self.hpo_label,
            "mondo_id": self.mondo_id,
            "frequency": self.frequency,
            "onset": self.onset,
            "sex": self.sex,
        }


class HPOClient(BaseAsyncClient):
    """
    Async client for Human Phenotype Ontology via the JAX HPO REST API.

    Provides:
    - Term lookup by HPO ID → ``OntologyTerm``
    - Search by phenotype name
    - Diseases associated with a phenotype
    - Phenotypes of a gene
    - Ancestor / descendant traversal
    """

    upstream_name = "hpo_jax"
    config = _HPO_CONFIG

    # ------------------------------------------------------------------
    # Term lookup
    # ------------------------------------------------------------------

    async def lookup(self, hpo_id: str) -> OntologyTerm:
        """Fetch a single HPO term by compact URI.

        Args:
            hpo_id: HPO compact URI, e.g. ``'HP:0001250'`` (Seizure).

        Returns:
            ``OntologyTerm`` with label, definition, and synonyms.
        """
        hpo_id = _normalise_hpo_id(hpo_id)
        data = await self._get(f"/hp/terms/{hpo_id}")
        return self._parse_term(data)

    async def search(
        self,
        query: str,
        *,
        max_results: int = 10,
    ) -> list[OntologyTerm]:
        """Search HPO terms by phenotype name or keyword.

        Args:
            query: Free-text phenotype query, e.g. ``'muscle weakness'``.
            max_results: Maximum number of results (1–50).

        Returns:
            List of ``OntologyTerm`` ordered by relevance.
        """
        max_results = max(1, min(max_results, 50))
        data = await self._get(
            "/hp/search",
            params={"q": query, "limit": max_results},
        )
        return [self._parse_term(t) for t in (data.get("terms") or [])]

    # ------------------------------------------------------------------
    # Disease ↔ phenotype associations
    # ------------------------------------------------------------------

    async def diseases_for_phenotype(
        self,
        hpo_id: str,
        *,
        limit: int = 20,
    ) -> list[DiseaseByPhenotype]:
        """List diseases associated with an HPO phenotype term.

        Args:
            hpo_id: HPO compact URI, e.g. ``'HP:0001250'``.
            limit: Maximum diseases to return.

        Returns:
            List of ``DiseaseByPhenotype`` sorted by disease name.
        """
        hpo_id = _normalise_hpo_id(hpo_id)
        data = await self._get(f"/network/annotation/{hpo_id}")
        diseases = data.get("diseases") or []
        results: list[DiseaseByPhenotype] = []
        for disease in diseases[:limit]:
            results.append(
                DiseaseByPhenotype(
                    disease_id=disease.get("id", ""),
                    disease_name=disease.get("name", ""),
                    hpo_id=hpo_id,
                    mondo_id=disease.get("mondoId") or "",
                )
            )
        return sorted(results, key=lambda d: d.disease_name)

    async def phenotypes_for_gene_id(
        self,
        ncbi_gene_id: str,
        *,
        gene_symbol: str = "",
        limit: int = 50,
    ) -> list[PhenotypeAssociation]:
        """Return HPO phenotype annotations for a gene by its NCBI Gene ID.

        The HPO network-annotation endpoint is keyed on entity CURIEs, so a
        gene must be addressed by its Entrez/NCBI Gene ID (e.g.
        ``'NCBIGene:672'`` for BRCA1) rather than its HGNC symbol. Resolve the
        symbol upstream (e.g. via Ensembl ``gene_lookup``) before calling.

        Args:
            ncbi_gene_id: NCBI Gene CURIE, e.g. ``'NCBIGene:672'``.
            gene_symbol: Optional HGNC symbol, recorded on each association.
            limit: Maximum phenotype associations to return.

        Returns:
            List of ``PhenotypeAssociation`` objects.
        """
        data = await self._get(f"/network/annotation/{ncbi_gene_id}")
        associations: list[PhenotypeAssociation] = []
        for term in (data.get("phenotypes") or [])[:limit]:
            associations.append(
                PhenotypeAssociation(
                    hpo_id=term.get("id", ""),
                    hpo_label=term.get("name", ""),
                    gene_symbol=gene_symbol,
                )
            )
        return associations

    async def phenotypes_for_disease(
        self,
        disease_id: str,
        *,
        limit: int = 100,
    ) -> list[PhenotypeAssociation]:
        """Return HPO phenotype annotations for a disease.

        Args:
            disease_id: OMIM or Orphanet ID, e.g. ``'OMIM:114480'``.
            limit: Maximum phenotype associations to return.

        Returns:
            List of ``PhenotypeAssociation`` objects.
        """
        data = await self._get(f"/network/annotation/{disease_id}")
        disease_name = (data.get("disease") or {}).get("name", "")
        associations: list[PhenotypeAssociation] = []
        for terms in (data.get("categories") or {}).values():
            for item in terms:
                metadata = item.get("metadata", {}) or {}
                associations.append(
                    PhenotypeAssociation(
                        hpo_id=item.get("id", ""),
                        hpo_label=item.get("name", ""),
                        disease_name=disease_name,
                        frequency=metadata.get("frequency", ""),
                        onset=metadata.get("onset", ""),
                    )
                )
                if len(associations) >= limit:
                    break
            if len(associations) >= limit:
                break
        return associations

    # ------------------------------------------------------------------
    # Hierarchy
    # ------------------------------------------------------------------

    async def ancestors(self, hpo_id: str) -> list[OntologyTerm]:
        """Return ancestor terms (parents and above) for an HPO term."""
        hpo_id = _normalise_hpo_id(hpo_id)
        # These endpoints return a JSON array of term objects; guard against an
        # unexpected non-list payload (e.g. an error object).
        data: Any = await self._get(f"/hp/terms/{hpo_id}/parents")
        if not isinstance(data, list):
            return []
        return [self._parse_term(t) for t in data]

    async def children(self, hpo_id: str) -> list[OntologyTerm]:
        """Return direct children of an HPO term."""
        hpo_id = _normalise_hpo_id(hpo_id)
        data: Any = await self._get(f"/hp/terms/{hpo_id}/children")
        if not isinstance(data, list):
            return []
        return [self._parse_term(t) for t in data]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_term(raw: dict[str, Any]) -> OntologyTerm:
        term = raw.get("details") or raw
        term_id: str = term.get("id", "")
        if not term_id:
            term_id = raw.get("id", "")
        return OntologyTerm(
            id=_normalise_hpo_id(term_id),
            label=term.get("name", ""),
            description=term.get("definition", ""),
            synonyms=tuple(
                s.get("label", "") if isinstance(s, dict) else s
                for s in (term.get("synonyms") or [])
            ),
            namespace="HP",
            obsolete=term.get("obsolete", False),
        )
