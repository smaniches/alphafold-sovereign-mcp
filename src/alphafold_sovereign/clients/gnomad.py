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

import math
from typing import Any

import structlog

from alphafold_sovereign.clients._base import BaseAsyncClient, UpstreamConfig, UpstreamError
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


# gnomAD answers an unknown variant ID with HTTP 200 and this GraphQL error.
_VARIANT_NOT_FOUND = "Variant not found"

# gnomAD repeats its counts split by sex karyotype: ``XX`` and ``XY`` for the
# cohort (``<subset>:XX`` and ``<subset>:XY`` for its HGDP or 1000 Genomes
# subset) and ``<record>_XX`` and ``<record>_XY`` for a population record
# (recorded for gnomad_r4, gnomad_r3 and gnomad_r2_1 on 2026-11-10 UTC; in
# every recorded record the two strata sum to the record they split).
_SEX_KARYOTYPES = ("XX", "XY")

# gnomAD reports a cohort's AF as AC / AN in double precision (recorded: equal
# to the last bit in every cohort record examined, 2026-11-10 UTC). The
# tolerance only absorbs floating-point representation: it is far above
# double rounding (about 1e-16) and below the relative effect of one allele
# for any allele number up to 1e9, so the frequency of other counts cannot pass.
_AF_REL_TOL = 1e-9

# Chromosomes on which every genotype is diploid. On X and Y the ploidy of a
# cohort depends on its sex composition, so no ploidy is assumed there.
_AUTOSOMES = frozenset(str(number) for number in range(1, 23))


def _af_safe(ac: int, an: int) -> float:
    return ac / an if an > 0 else 0.0


def _is_sex_stratum(pop_id: str, record_ids: set[str]) -> bool:
    """True when ``pop_id`` recounts, by sex, alleles of the cohort or of a listed record.

    Only such records are left out of the population breakdown. ``XX`` and
    ``XY``, alone or after a subset prefix, name a sex and no population. A
    ``<record>_XX`` or ``<record>_XY`` stratum is left out only when the
    record it splits is in the same response, so no population is dropped
    because of how its identifier is spelled and none loses its only counts.
    """
    if pop_id.rpartition(":")[2].upper() in _SEX_KARYOTYPES:
        return True
    record, _, suffix = pop_id.rpartition("_")
    return suffix in _SEX_KARYOTYPES and record in record_ids


def _cohort_counts(cohort: dict[str, Any]) -> tuple[int | None, int | None, float | None]:
    """Validate one sequencing cohort's allele count, allele number and frequency.

    Returns ``(AC, AN, AF)``. AF is ``0.0`` only for a measured zero (AC = 0
    with AN > 0) and ``None`` when no allele number was sampled. A malformed
    value raises ``ValueError`` whatever the other two are, and so do values
    that cannot belong together: AC > AN, a frequency that is not AC / AN, or
    a positive frequency reported with AN = 0.
    """
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
    ac: int | None = raw_ac if isinstance(raw_ac, int) else None
    an: int | None = raw_an if isinstance(raw_an, int) else None
    if ac is not None and an is not None and ac > an:
        raise ValueError("gnomAD allele count exceeds allele number")

    # A reported frequency must be a number in [0, 1], whether or not there is
    # an allele number to check it against.
    raw_af = cohort.get("af")
    if raw_af is not None and (
        not isinstance(raw_af, (int, float)) or isinstance(raw_af, bool) or not 0.0 <= raw_af <= 1.0
    ):
        raise ValueError("Invalid gnomAD allele frequency")
    af: float | None = None
    if an is not None and an > 0:
        if raw_af is None:
            if ac is not None:
                af = _af_safe(ac, an)
        else:
            # AF is AC / AN: the reported frequency must be that of the
            # reported count, or of a whole number of alleles when the count
            # is absent. A frequency of 0 therefore requires a count of 0.
            count = ac if ac is not None else round(raw_af * an)
            if not math.isclose(raw_af, count / an, rel_tol=_AF_REL_TOL, abs_tol=0.0):
                raise ValueError("gnomAD allele frequency contradicts allele count and number")
            af = float(raw_af)
    elif an == 0 and raw_af:
        # No allele was sampled, so no frequency can have been measured.
        raise ValueError("gnomAD reports an allele frequency without sampled alleles")
    return ac, an, af


def _homozygote_count(
    record: dict[str, Any], ac: int | None, an: int | None, *, diploid: bool
) -> int | None:
    """Validate the homozygote count reported beside ``ac`` and ``an``.

    ``None`` is kept: a count gnomAD does not report is not a count of 0. A
    homozygote carries the allele at least once, and twice where every
    genotype is diploid, so the count is bounded by the allele count, or by
    the allele number when no allele count is reported. A value that is not a
    non-negative whole number, or that exceeds that bound, raises
    ``ValueError``.
    """
    raw: object = record.get("ac_hom")
    if raw is None:
        return None
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise ValueError("Invalid gnomAD homozygote count")
    alleles = ac if ac is not None else an
    if alleles is not None and raw * (2 if diploid else 1) > alleles:
        raise ValueError("gnomAD homozygote count exceeds what its allele count or number allows")
    return raw


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

    async def variant_frequencies(self, variant_id: str) -> dict[str, Any]:
        """Fetch allele frequencies and population breakdown for a variant.

        Args:
            variant_id: gnomAD variant ID ``'{chrom}-{pos}-{ref}-{alt}'``.

        Returns:
            Dict with ``found`` and ``dataset``. When found: ``global_af``,
            ``global_ac``, ``global_an`` and ``populations`` (list of
            ``PopulationFrequency``) taken from the cohort named in ``cohort``
            (exome when gnomAD reports one, otherwise genome), and
            ``cohorts`` with the validated counts of every reported cohort.
            ``populations`` holds every population record of the named
            cohort with the counts gnomAD reports, except sex strata
            (``XX``, ``XY``, ``<record>_XX``, ``<record>_XY``, also after
            a subset prefix), which count the same alleles a second time.
            A variant gnomAD does not hold is ``found: False`` with
            ``global_af: None``; that is not an allele frequency of 0.

        Raises:
            ValueError: gnomAD returned neither a record nor its "Variant not
                found" error, a record for a different variant, malformed or
                mutually contradictory cohort counts, or a homozygote count
                of a cohort or a listed population that is malformed or
                exceeds what its allele count or number allows.
        """
        try:
            data = await self._graphql(
                self._GQL_PATH,
                _VARIANT_QUERY,
                {"variantId": variant_id, "datasetId": self.dataset},
            )
        except UpstreamError as exc:
            # Only gnomAD's single "Variant not found" error means absence;
            # every other GraphQL error stays an upstream failure.
            if str(exc) != str(UpstreamError(self.upstream_name, 200, _VARIANT_NOT_FOUND)):
                raise
            return {
                "variant_id": variant_id,
                "found": False,
                "dataset": self.dataset,
                "global_af": None,
                "populations": [],
            }
        variant = data.get("variant")
        if not isinstance(variant, dict) or not variant:
            # gnomAD states absence with the error handled above; a reply
            # without it and without a record says nothing about the variant.
            raise ValueError("gnomAD returned neither a variant record nor 'Variant not found'")
        if variant.get("variantId") != variant_id:
            raise ValueError("gnomAD returned a record for a different variant than requested")

        diploid = variant_id.partition("-")[0] in _AUTOSOMES
        # Prefer exome data; fall back to genome. Both cohorts are reported:
        # a variant with no exome carrier can still be observed in genomes.
        cohorts: dict[str, dict[str, Any]] = {}
        for name in ("exome", "genome"):
            if variant.get(name):
                count, number, frequency = _cohort_counts(variant[name])
                cohorts[name] = {
                    "allele_count": count,
                    "allele_number": number,
                    "allele_frequency": frequency,
                    "homozygote_count": _homozygote_count(
                        variant[name], count, number, diploid=diploid
                    ),
                }
        cohort_name = next(iter(cohorts), None)
        cohort = variant[cohort_name] if cohort_name else {}
        global_ac, global_an, global_af = _cohort_counts(cohort)

        populations: list[PopulationFrequency] = []
        records = cohort.get("populations", [])
        record_ids = {pop.get("id", "") for pop in records}
        for pop in records:
            pop_id: str = pop.get("id", "")
            # Sex strata recount alleles of a record that is already listed.
            if _is_sex_stratum(pop_id, record_ids):
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
                    homozygote_count=_homozygote_count(pop, ac, an, diploid=diploid),
                )
            )

        return {
            "variant_id": variant_id,
            "found": True,
            "dataset": self.dataset,
            "cohort": cohort_name,
            "cohorts": cohorts,
            "rsids": variant.get("rsids", []),
            "chrom": variant.get("chrom", ""),
            "pos": variant.get("pos"),
            "ref": variant.get("ref", ""),
            "alt": variant.get("alt", ""),
            "global_af": global_af,
            "global_ac": global_ac,
            "global_an": global_an,
            "homozygote_count": cohorts[cohort_name]["homozygote_count"] if cohort_name else None,
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
