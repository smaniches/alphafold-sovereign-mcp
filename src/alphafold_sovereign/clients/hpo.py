# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Human Phenotype Ontology (HPO) async client.

Data sources:
- HPO REST API (hpo.jax.org)  — phenotype terms, disease-phenotype links
- OLS4 REST API               — hierarchy traversal fallback

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

_HPO_BASE = "https://hpo.jax.org/api"
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
    hpo_label: str
    frequency: str = ""
    onset: str = ""
    sex: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "disease_id": self.disease_id,
            "disease_name": self.disease_name,
            "hpo_id": self.hpo_id,
            "hpo_label": self.hpo_label,
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
        data = await self._get(f"/hpo/term/{hpo_id}")
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
            "/hpo/search",
            params={"q": query, "max": max_results},
        )
        return [
            self._parse_term(t)
            for t in data.get("terms", [])
        ]

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
        data = await self._get(f"/hpo/term/{hpo_id}/diseases")
        associations = data.get("diseaseAssoc", [])
        results: list[DiseaseByPhenotype] = []
        for assoc in associations[:limit]:
            results.append(
                DiseaseByPhenotype(
                    disease_id=assoc.get("diseaseId", ""),
                    disease_name=assoc.get("diseaseName", ""),
                    hpo_id=hpo_id,
                    hpo_label=assoc.get("ontologyTerm", {}).get("name", ""),
                    frequency=assoc.get("frequency", ""),
                    onset=assoc.get("onset", ""),
                    sex=assoc.get("sex", ""),
                )
            )
        return sorted(results, key=lambda d: d.disease_name)

    async def phenotypes_for_gene(
        self,
        gene_symbol: str,
        *,
        limit: int = 50,
    ) -> list[PhenotypeAssociation]:
        """Return HPO phenotype annotations for a human gene.

        Args:
            gene_symbol: HGNC gene symbol, e.g. ``'BRCA1'``.
            limit: Maximum phenotype associations to return.

        Returns:
            List of ``PhenotypeAssociation`` objects.
        """
        data = await self._get(
            f"/hpo/gene",
            params={"gene": gene_symbol},
        )
        associations: list[PhenotypeAssociation] = []
        for item in (data.get("termAssoc") or [])[:limit]:
            term = item.get("ontologyTerm", {})
            associations.append(
                PhenotypeAssociation(
                    hpo_id=term.get("id", ""),
                    hpo_label=term.get("name", ""),
                    gene_symbol=gene_symbol,
                    frequency=item.get("frequency", ""),
                    onset=item.get("onset", ""),
                    evidence_codes=tuple(item.get("evidenceCodes", [])),
                    references=tuple(item.get("references", [])),
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
        data = await self._get(
            f"/hpo/disease",
            params={"disease_id": disease_id},
        )
        associations: list[PhenotypeAssociation] = []
        for cat in data.get("catTermsMap", {}).values():
            for item in cat.get("terms", []):
                term = item.get("ontologyTerm", {})
                associations.append(
                    PhenotypeAssociation(
                        hpo_id=term.get("id", ""),
                        hpo_label=term.get("name", ""),
                        disease_name=data.get("disease", {}).get("diseaseName", ""),
                        frequency=item.get("frequency", {}).get("id", ""),
                        onset=item.get("onset", {}).get("id", "") if item.get("onset") else "",
                        evidence_codes=tuple(
                            e.get("id", "") for e in (item.get("evidence") or [])
                        ),
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
        data = await self._get(f"/hpo/term/{hpo_id}/parents")
        return [self._parse_term(t) for t in data.get("parents", [])]

    async def children(self, hpo_id: str) -> list[OntologyTerm]:
        """Return direct children of an HPO term."""
        hpo_id = _normalise_hpo_id(hpo_id)
        data = await self._get(f"/hpo/term/{hpo_id}/children")
        return [self._parse_term(t) for t in data.get("children", [])]

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
