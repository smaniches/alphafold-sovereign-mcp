# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
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
  }
}
"""

_GENE_CONSTRAINT_QUERY = """
query GeneConstraint($geneSymbol: String!) {
  gene(gene_symbol: $geneSymbol, reference_genome: GRCh38) {
    gnomad_constraint {
      pLI
      loeuf: oe_lof_upper
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

    async def variant_frequencies(self, variant_id: str) -> dict[str, Any]:  # noqa: PLR0912
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
        # A variant record without a sampled allele denominator is not AF=0.
        raw_ac: object = cohort.get("ac")
        raw_an: object = cohort.get("an")
        if raw_ac is not None and (
            not isinstance(raw_ac, int) or isinstance(raw_ac, bool) or raw_ac < 0
        ):
            raise ValueError("Invalid gnomAD allele count")
        if raw_an is not None and (
            not isinstance(raw_an, int) or isinstance(raw_an, bool) or raw_an < 0
        ):
            raise ValueError("Invalid gnomAD allele number")
        global_ac: int | None = raw_ac if isinstance(raw_ac, int) else None
        global_an: int | None = raw_an if isinstance(raw_an, int) else None
        if global_ac is not None and global_an is not None and global_ac > global_an:
            raise ValueError("gnomAD allele count exceeds allele number")

        raw_af = cohort.get("af")
        global_af: float | None = None
        if global_an is not None and global_an > 0:
            if raw_af is None:
                if global_ac is not None:
                    global_af = _af_safe(global_ac, global_an)
            elif (
                isinstance(raw_af, (int, float))
                and not isinstance(raw_af, bool)
                and 0.0 <= raw_af <= 1.0
            ):
                global_af = float(raw_af)
            else:
                raise ValueError("Invalid gnomAD allele frequency")

        populations: list[PopulationFrequency] = []
        for pop in cohort.get("populations", []):
            pop_id: str = pop.get("id", "")
            # Skip sex-stratified and sub-populations (contain "-")
            if "-" in pop_id or pop_id.upper() in {"XX", "XY"}:
                continue
            ac = pop.get("ac")
            an = pop.get("an")
            if not isinstance(an, int) or isinstance(an, bool) or an <= 0:
                continue  # No sampled denominator: do not claim frequency 0.
            if not isinstance(ac, int) or isinstance(ac, bool) or not 0 <= ac <= an:
                raise ValueError("Invalid gnomAD population allele count")
            populations.append(
                PopulationFrequency(
                    population=_POP_LABELS.get(pop_id, pop_id),
                    allele_count=ac,
                    allele_number=an,
                    allele_frequency=_af_safe(ac, an),
                    homozygote_count=pop.get("ac_hom"),
                )
            )

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
            "homozygote_count": cohort.get("ac_hom"),
            "populations": [p.to_dict() for p in populations],
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
            - ``pLI`` ≥ 0.9 = LoF depletion; haploinsufficiency is not established.
            - ``mis_z`` ≥ 3.09 = missense-intolerant.
        """
        data = await self._graphql(
            self._GQL_PATH,
            _GENE_CONSTRAINT_QUERY,
            {"geneSymbol": gene_symbol},
        )
        constraint = (data.get("gene") or {}).get("gnomad_constraint") or {}
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
    if loeuf is None:
        return "Constraint data unavailable."
    if loeuf < 0.35:
        return (
            f"Highly constrained (LOEUF={loeuf:.3f}): "
            "loss-of-function depleted; haploinsufficiency not established."
        )
    if loeuf < 0.6:
        return (
            f"Moderately constrained (LOEUF={loeuf:.3f}): partial intolerance to loss-of-function."
        )
    return (
        f"Tolerant to loss-of-function (LOEUF={loeuf:.3f}): "
        "LoF variants are tolerated in the population."
    )
