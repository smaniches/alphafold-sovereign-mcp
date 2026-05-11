# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""gnomAD async GraphQL client.

Provides population allele frequencies, LOEUF constraint scores, and
per-population breakdown for human variants.

Reference:
  Chen S et al. A genomic mutational constraint map using variation in
  1,000 human exomes. Nature. 2024;625:92–100.
  https://gnomad.broadinstitute.org
"""
from __future__ import annotations

from typing import Any

import structlog

from alphafold_sovereign.clients._base import BaseAsyncClient, UpstreamConfig
from alphafold_sovereign.domain.disease import PopulationFrequency

logger = structlog.get_logger(__name__)

_GNOMAD_CONFIG = UpstreamConfig(
    base_url="https://gnomad.broadinstitute.org",
    calls_per_second=2.0,  # gnomAD rate-limits aggressively
    max_retries=3,
    min_wait=2.0,
    max_wait=60.0,
    timeout=30.0,
    headers={"Content-Type": "application/json"},
)

_VARIANT_QUERY = """
query Variant($variantId: String!, $datasetId: DatasetId!) {
  variant(variantId: $variantId, dataset: $datasetId) {
    variantId
    rsids
    chrom
    pos
    ref
    alt
    exome {
      ac
      an
      af
      ac_hom
      populations {
        id
        ac
        an
        ac_hom
      }
    }
    genome {
      ac
      an
      af
      ac_hom
      populations {
        id
        ac
        an
        ac_hom
      }
    }
    in_silico_predictors {
      id
      value
      flags
    }
  }
}
"""

_GENE_CONSTRAINT_QUERY = """
query GeneConstraint($geneSymbol: String!, $datasetId: DatasetId!) {
  gene(gene_symbol: $geneSymbol, reference_genome: GRCh38) {
    gnomad_constraint {
      pLI
      loeuf
      mis_z
      oe_lof_upper
    }
  }
}
"""

# Population label mapping
_POP_LABELS: dict[str, str] = {
    "afr": "African/African-American",
    "amr": "Admixed American",
    "asj": "Ashkenazi Jewish",
    "eas": "East Asian",
    "fin": "Finnish",
    "mid": "Middle Eastern",
    "nfe": "Non-Finnish European",
    "oth": "Other",
    "sas": "South Asian",
    "XX": "Female",
    "XY": "Male",
}


def _af_safe(ac: int, an: int) -> float:
    return ac / an if an > 0 else 0.0


class GnomADClient(BaseAsyncClient):
    """
    Async GraphQL client for gnomAD population genetics data.

    Variant IDs use the gnomAD format: ``{chrom}-{pos}-{ref}-{alt}``
    e.g. ``'13-32936732-G-T'`` (BRCA2 missense).

    For HGVS-to-gnomAD-ID conversion, pair with the Ensembl client.
    """

    upstream_name = "gnomad"
    config = _GNOMAD_CONFIG

    _GQL_PATH = "/api"

    def __init__(
        self,
        *,
        dataset: str = "gnomad_r4",
        **kwargs: Any,
    ) -> None:
        """
        Args:
            dataset: gnomAD dataset identifier.  Use ``'gnomad_r4'``
                (GRCh38) or ``'gnomad_r2_1'`` (GRCh37 legacy).
        """
        self.dataset = dataset
        super().__init__(**kwargs)

    # ------------------------------------------------------------------
    # Variant queries
    # ------------------------------------------------------------------

    async def variant_frequencies(
        self, variant_id: str
    ) -> dict[str, Any]:
        """Fetch allele frequencies and population breakdown for a variant.

        Args:
            variant_id: gnomAD variant ID ``'{chrom}-{pos}-{ref}-{alt}'``.

        Returns:
            Dict with ``global_af``, ``global_ac``, ``global_an``,
            ``populations`` (list of ``PopulationFrequency``).
        """
        data = await self._graphql(
            self._GQL_PATH,
            _VARIANT_QUERY,
            {"variantId": variant_id, "datasetId": self.dataset},
        )
        variant = data.get("variant")
        if not variant:
            return {
                "variant_id": variant_id,
                "found": False,
                "global_af": None,
                "populations": [],
            }

        # Prefer exome data; fall back to genome
        cohort = variant.get("exome") or variant.get("genome") or {}
        global_ac: int = cohort.get("ac", 0) or 0
        global_an: int = cohort.get("an", 0) or 0
        global_af: float = cohort.get("af") or _af_safe(global_ac, global_an)

        populations: list[PopulationFrequency] = []
        for pop in cohort.get("populations", []):
            pop_id: str = pop.get("id", "")
            # Skip sex-stratified and sub-populations (contain "-")
            if "-" in pop_id or pop_id.upper() in {"XX", "XY"}:
                continue
            ac = pop.get("ac", 0) or 0
            an = pop.get("an", 0) or 0
            populations.append(
                PopulationFrequency(
                    population=_POP_LABELS.get(pop_id, pop_id),
                    allele_count=ac,
                    allele_number=an,
                    allele_frequency=_af_safe(ac, an),
                    homozygote_count=pop.get("ac_hom", 0) or 0,
                )
            )

        # In-silico predictors (AlphaMissense if present)
        am_score: float | None = None
        for pred in variant.get("in_silico_predictors") or []:
            if pred.get("id", "").lower() == "alphamissense":
                try:
                    am_score = float(pred["value"])
                except (TypeError, ValueError):
                    pass

        return {
            "variant_id": variant_id,
            "found": True,
            "rsids": variant.get("rsids", []),
            "chrom": variant.get("chrom", ""),
            "pos": variant.get("pos"),
            "ref": variant.get("ref", ""),
            "alt": variant.get("alt", ""),
            "global_af": global_af,
            "global_ac": global_ac,
            "global_an": global_an,
            "homozygote_count": cohort.get("ac_hom", 0),
            "populations": [p.to_dict() for p in populations],
            "alphamissense_score": am_score,
        }

    # ------------------------------------------------------------------
    # Gene constraint
    # ------------------------------------------------------------------

    async def gene_constraint(self, gene_symbol: str) -> dict[str, Any]:
        """Fetch gnomAD constraint scores for a gene.

        Args:
            gene_symbol: HGNC gene symbol, e.g. ``'BRCA1'``.

        Returns:
            Dict with ``pLI``, ``loeuf``, ``mis_z``, ``oe_lof_upper``.
            Returns empty dict if gene not found.

            Interpretation guidance:
            - ``loeuf`` (Loss-of-function Observed/Expected Upper-bound
              Fraction): < 0.35 = highly constrained (LoF intolerant).
            - ``pLI`` ≥ 0.9 = likely haploinsufficient.
            - ``mis_z`` ≥ 3.09 = missense-intolerant.
        """
        data = await self._graphql(
            self._GQL_PATH,
            _GENE_CONSTRAINT_QUERY,
            {"geneSymbol": gene_symbol, "datasetId": self.dataset},
        )
        constraint = (
            (data.get("gene") or {}).get("gnomad_constraint") or {}
        )
        if not constraint:
            return {"gene_symbol": gene_symbol, "constraint_available": False}
        return {
            "gene_symbol": gene_symbol,
            "constraint_available": True,
            "pLI": constraint.get("pLI"),
            "loeuf": constraint.get("loeuf"),
            "mis_z": constraint.get("mis_z"),
            "oe_lof_upper": constraint.get("oe_lof_upper"),
            "interpretation": _interpret_constraint(constraint),
        }


def _interpret_constraint(c: dict[str, Any]) -> str:
    """Return a human-readable constraint interpretation."""
    loeuf = c.get("loeuf")
    pli = c.get("pLI")
    if loeuf is None:
        return "Constraint data unavailable."
    if loeuf < 0.35:
        return (
            f"Highly constrained (LOEUF={loeuf:.3f}): "
            "strong intolerance to loss-of-function — likely haploinsufficient."
        )
    if loeuf < 0.6:
        return (
            f"Moderately constrained (LOEUF={loeuf:.3f}): "
            "partial intolerance to loss-of-function."
        )
    return (
        f"Tolerant to loss-of-function (LOEUF={loeuf:.3f}): "
        "LoF variants are tolerated in the population."
    )
