# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Full-coverage tests for ``alphafold_sovereign.clients.gnomad``.

Mocks the gnomAD GraphQL endpoint, covers every population-filter
branch and every constraint-interpretation tier.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from alphafold_sovereign.clients._base import UpstreamError
from alphafold_sovereign.clients.gnomad import (
    GnomADClient,
    _af_safe,
    _interpret_constraint,
)

# ---------------------------------------------------------------------------
# Pure-function helpers
# ---------------------------------------------------------------------------


def test_af_safe_zero_denominator() -> None:
    assert _af_safe(0, 0) == 0.0


def test_af_safe_normal_case() -> None:
    assert _af_safe(1, 4) == 0.25


def test_interpret_constraint_unavailable() -> None:
    assert _interpret_constraint({}) == "Constraint data unavailable."


def test_interpret_constraint_highly_constrained() -> None:
    msg = _interpret_constraint({"loeuf": 0.2})
    assert "Highly constrained" in msg
    assert "haploinsufficiency not established" in msg


def test_interpret_constraint_moderately_constrained() -> None:
    msg = _interpret_constraint({"loeuf": 0.45})
    assert "Moderately constrained" in msg


def test_interpret_constraint_tolerant() -> None:
    msg = _interpret_constraint({"loeuf": 0.9})
    assert "Tolerant to loss-of-function" in msg


# ---------------------------------------------------------------------------
# variant_frequencies
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"data": {"variant": None}},
        {"data": {}},
        {"data": None},
        {},
        {"data": {"variant": {}}},
        {"data": {"variant": "none"}},
    ],
)
async def test_variant_frequencies_no_record_without_not_found_error_is_rejected(
    respx_mock: respx.MockRouter, body: dict[str, Any]
) -> None:
    """HTTP 200 with neither a record nor gnomAD's not-found error is not absence."""
    respx_mock.post("https://gnomad.broadinstitute.org/api").mock(
        return_value=httpx.Response(200, json=body),
    )
    async with GnomADClient() as client:
        with pytest.raises(ValueError, match="neither a variant record nor"):
            await client.variant_frequencies("1-2-A-G")


async def test_variant_frequencies_graphql_not_found_is_absence(
    respx_mock: respx.MockRouter,
) -> None:
    """gnomAD's live reply for an unknown variant (recorded 2026-11-10 UTC)."""
    respx_mock.post("https://gnomad.broadinstitute.org/api").mock(
        return_value=httpx.Response(
            200,
            json={"errors": [{"message": "Variant not found"}], "data": {"variant": None}},
        ),
    )
    async with GnomADClient() as client:
        result = await client.variant_frequencies("17-43106487-A-T")
    assert result == {
        "variant_id": "17-43106487-A-T",
        "found": False,
        "dataset": "gnomad_r4",
        "global_af": None,
        "populations": [],
    }


@pytest.mark.parametrize(
    "errors",
    [
        [{"message": "Internal server error"}],
        [{"message": "Variant not found"}, {"message": "Internal server error"}],
        [{"message": "Variant not found in dataset index"}],
    ],
)
async def test_variant_frequencies_other_graphql_errors_still_fail(
    respx_mock: respx.MockRouter, errors: list[dict[str, str]]
) -> None:
    """Only the exact single not-found error is absence; anything else is a failure."""
    respx_mock.post("https://gnomad.broadinstitute.org/api").mock(
        return_value=httpx.Response(200, json={"errors": errors, "data": {"variant": None}}),
    )
    async with GnomADClient() as client:
        with pytest.raises(UpstreamError):
            await client.variant_frequencies("1-2-A-G")


@pytest.mark.parametrize("returned_id", ["1-2-A-T", "2-2-A-G", None])
async def test_variant_frequencies_rejects_record_for_another_variant(
    respx_mock: respx.MockRouter, returned_id: str | None
) -> None:
    """Counts are attributed only to the variant gnomAD says it returned."""
    respx_mock.post("https://gnomad.broadinstitute.org/api").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "variant": {"variantId": returned_id, "exome": {"ac": 1, "an": 10, "af": 0.1}}
                }
            },
        ),
    )
    async with GnomADClient() as client:
        with pytest.raises(ValueError, match="different variant"):
            await client.variant_frequencies("1-2-A-G")


async def test_variant_frequencies_reports_both_cohorts(respx_mock: respx.MockRouter) -> None:
    """An exome cohort without carriers must not hide carriers in genomes."""
    respx_mock.post("https://gnomad.broadinstitute.org/api").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "variant": {
                        "variantId": "1-2-A-G",
                        "exome": {"ac": 0, "an": 1000, "af": 0, "ac_hom": 0},
                        "genome": {"ac": 1, "an": 200, "af": 0.005, "ac_hom": 0},
                    }
                }
            },
        ),
    )
    async with GnomADClient() as client:
        result = await client.variant_frequencies("1-2-A-G")
    # The summary fields keep describing the exome cohort when one is reported.
    assert (result["cohort"], result["global_ac"], result["global_af"]) == ("exome", 0, 0.0)
    assert result["cohorts"] == {
        "exome": {
            "allele_count": 0,
            "allele_number": 1000,
            "allele_frequency": 0.0,
            "homozygote_count": 0,
        },
        "genome": {
            "allele_count": 1,
            "allele_number": 200,
            "allele_frequency": 0.005,
            "homozygote_count": 0,
        },
    }


async def test_variant_frequencies_malformed_second_cohort_rejected(
    respx_mock: respx.MockRouter,
) -> None:
    """Every reported cohort is validated, not only the summarised one."""
    respx_mock.post("https://gnomad.broadinstitute.org/api").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "variant": {
                        "variantId": "1-2-A-G",
                        "exome": {"ac": 0, "an": 1000},
                        "genome": {"ac": 5, "an": 2},
                    }
                }
            },
        ),
    )
    async with GnomADClient() as client:
        with pytest.raises(ValueError, match="exceeds allele number"):
            await client.variant_frequencies("1-2-A-G")


async def test_variant_frequencies_full_payload(respx_mock: respx.MockRouter) -> None:
    """Exercise: exome branch and every population filter."""
    respx_mock.post("https://gnomad.broadinstitute.org/api").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "variant": {
                        "variantId": "13-32936732-G-T",
                        "rsids": ["rs80359550"],
                        "chrom": "13",
                        "pos": 32936732,
                        "ref": "G",
                        "alt": "T",
                        "exome": {
                            "ac": 5,
                            "an": 250000,
                            "af": 0.00002,
                            "ac_hom": 0,
                            "populations": [
                                # Skipped: sex stratum of the listed nfe record
                                {"id": "nfe_XX", "ac": 1, "an": 40, "ac_hom": 0},
                                # Skipped: XX sex stratum
                                {"id": "XX", "ac": 1, "an": 1, "ac_hom": 0},
                                # Skipped: XY sex stratum (separate branch)
                                {"id": "XY", "ac": 2, "an": 2, "ac_hom": 0},
                                # Kept: maps via _POP_LABELS
                                {"id": "nfe", "ac": 3, "an": 100, "ac_hom": 0},
                                # Kept but unknown id (no _POP_LABELS hit)
                                {"id": "unknown", "ac": 2, "an": 50, "ac_hom": 1},
                                # ac/an returned as None → coalesce to 0
                                {"id": "afr", "ac": None, "an": None, "ac_hom": None},
                            ],
                        },
                    }
                }
            },
        ),
    )
    async with GnomADClient() as client:
        result = await client.variant_frequencies("13-32936732-G-T")
    assert result["found"] is True
    assert result["global_af"] == 0.00002
    populations = result["populations"]
    # Only nfe and unknown have observed allele denominators; afr is excluded.
    assert len(populations) == 2
    labels = {p["population"] for p in populations}
    assert "Non-Finnish European" in labels  # from _POP_LABELS
    assert "unknown" in labels  # fallthrough to raw id


async def test_variant_frequencies_falls_back_to_genome(respx_mock: respx.MockRouter) -> None:
    """If exome is null, use genome data."""
    respx_mock.post("https://gnomad.broadinstitute.org/api").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "variant": {
                        "variantId": "1-1-A-G",
                        "exome": None,
                        "genome": {
                            "ac": None,
                            "an": None,  # No observed denominator
                            "af": None,  # No source frequency
                            "ac_hom": None,
                            "populations": [],
                        },
                    }
                }
            },
        ),
    )
    async with GnomADClient() as client:
        result = await client.variant_frequencies("1-1-A-G")
    assert result["found"] is True
    assert result["cohort"] == "genome"
    assert result["global_af"] is None
    assert result["global_ac"] is None
    assert result["global_an"] is None


async def test_variant_frequencies_no_cohort_data(respx_mock: respx.MockRouter) -> None:
    """A variant identity without cohort counts has no measured AF."""
    respx_mock.post("https://gnomad.broadinstitute.org/api").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "variant": {
                        "variantId": "1-1-A-G",
                        "exome": None,
                        "genome": None,
                        "in_silico_predictors": [],
                    }
                }
            },
        ),
    )
    async with GnomADClient() as client:
        result = await client.variant_frequencies("1-1-A-G")
    assert result["found"] is True
    assert result["cohort"] is None
    assert result["cohorts"] == {}
    assert result["global_af"] is None
    assert result["homozygote_count"] is None


@pytest.mark.parametrize(
    ("cohort", "expected_af"),
    [
        ({"ac": 0, "an": 200, "af": None}, 0.0),
        ({"ac": 2, "an": 200, "af": None}, 0.01),
        ({"ac": None, "an": 200, "af": None}, None),
        ({"ac": 0, "an": 0, "af": None}, None),
        ({"ac": 0, "an": 200, "af": 0.0}, 0.0),
    ],
)
async def test_variant_frequency_missing_vs_measured_zero(
    respx_mock: respx.MockRouter, cohort: dict[str, Any], expected_af: float | None
) -> None:
    """Only a sampled cohort can establish AF=0 or a nonzero frequency."""
    respx_mock.post("https://gnomad.broadinstitute.org/api").mock(
        return_value=httpx.Response(
            200, json={"data": {"variant": {"variantId": "1-1-A-G", "exome": cohort}}}
        )
    )
    async with GnomADClient() as client:
        result = await client.variant_frequencies("1-1-A-G")
    assert result["found"] is True
    assert result["global_af"] == expected_af


@pytest.mark.parametrize(
    "cohort",
    [
        {"ac": -1, "an": 100},
        {"ac": "one", "an": 100},
        {"ac": True, "an": 100},
        {"ac": 1, "an": -1},
        {"ac": 1, "an": "one hundred"},
        {"ac": 1, "an": False},
        {"ac": 101, "an": 100},
        {"ac": 1, "an": 100, "af": 1.5},
        {"ac": 1, "an": 100, "af": -0.01},
        {"ac": 1, "an": 100, "af": True},
        {"ac": 1, "an": 100, "af": "0.01"},
    ],
)
async def test_variant_frequency_malformed_counts_or_af_rejected(
    respx_mock: respx.MockRouter, cohort: dict[str, Any]
) -> None:
    """Never convert malformed upstream cohort observations into usable evidence."""
    respx_mock.post("https://gnomad.broadinstitute.org/api").mock(
        return_value=httpx.Response(
            200, json={"data": {"variant": {"variantId": "1-1-A-G", "exome": cohort}}}
        )
    )
    async with GnomADClient() as client:
        with pytest.raises(ValueError):
            await client.variant_frequencies("1-1-A-G")


@pytest.mark.parametrize(
    ("cohort", "expected_af"),
    [
        # Measured zero: alleles were sampled and none carries the variant.
        # gnomAD sends the integer 0 for this frequency.
        ({"ac": 0, "an": 1458040, "af": 0}, 0.0),
        # Missing: no allele was sampled, so there is no frequency, not a zero.
        ({"ac": 0, "an": 0, "af": 0}, None),
        # The frequency gnomAD reports is AC / AN in double precision.
        ({"ac": 25, "an": 1452604, "af": 25 / 1452604}, 25 / 1452604),
        # A difference of floating-point representation only.
        (
            {"ac": 1200, "an": 152206, "af": (1200 / 152206) * (1 + 1e-12)},
            pytest.approx(1200 / 152206, rel=1e-11),
        ),
        # Count absent: the frequency of a whole number of alleles is kept.
        ({"ac": None, "an": 1000, "af": 0.003}, 0.003),
    ],
)
async def test_variant_frequency_consistent_cohort_values_accepted(
    respx_mock: respx.MockRouter, cohort: dict[str, Any], expected_af: Any
) -> None:
    """AC, AN and AF that agree keep their meaning: measured zero, missing, or a frequency."""
    respx_mock.post("https://gnomad.broadinstitute.org/api").mock(
        return_value=httpx.Response(
            200, json={"data": {"variant": {"variantId": "1-1-A-G", "exome": cohort}}}
        )
    )
    async with GnomADClient() as client:
        result = await client.variant_frequencies("1-1-A-G")
    assert result["global_af"] == expected_af
    assert result["cohorts"]["exome"]["allele_frequency"] == expected_af
    assert (result["global_ac"], result["global_an"]) == (cohort["ac"], cohort["an"])


@pytest.mark.parametrize(
    ("cohort", "message"),
    [
        # The frequency of other counts.
        ({"ac": 25, "an": 1452604, "af": 0.5}, "contradicts"),
        # Rounded to two digits: no longer 25 / 1,452,604.
        ({"ac": 25, "an": 1452604, "af": 1.7e-05}, "contradicts"),
        # One allele apart in the count, then in the number, at gnomAD scale.
        ({"ac": 1458238, "an": 1461288, "af": 1458237 / 1461288}, "contradicts"),
        ({"ac": 25, "an": 1452605, "af": 25 / 1452604}, "contradicts"),
        # No carrier, yet a positive frequency; carriers, yet frequency 0.
        ({"ac": 0, "an": 1452604, "af": 1e-09}, "contradicts"),
        ({"ac": 25, "an": 1452604, "af": 0}, "contradicts"),
        # Count absent and a frequency that is not a whole number of alleles.
        ({"ac": None, "an": 1000, "af": 0.0035}, "contradicts"),
        # A frequency although no allele was sampled.
        ({"ac": 0, "an": 0, "af": 0.1}, "without sampled alleles"),
    ],
)
async def test_variant_frequency_contradictory_cohort_values_rejected(
    respx_mock: respx.MockRouter, cohort: dict[str, Any], message: str
) -> None:
    """AC, AN and AF that cannot belong together are an invalid response, not evidence."""
    respx_mock.post("https://gnomad.broadinstitute.org/api").mock(
        return_value=httpx.Response(
            200, json={"data": {"variant": {"variantId": "1-1-A-G", "exome": cohort}}}
        )
    )
    async with GnomADClient() as client:
        with pytest.raises(ValueError, match=message):
            await client.variant_frequencies("1-1-A-G")


@pytest.mark.parametrize(
    "cohort",
    [
        # No allele was sampled: a frequency that is no frequency is still invalid.
        {"ac": 0, "an": 0, "af": -0.1},
        {"ac": 0, "an": 0, "af": "0.5"},
        {"ac": 0, "an": 0, "af": True},
        # No allele number at all.
        {"ac": None, "an": None, "af": -0.1},
        {"ac": None, "an": None, "af": "0.5"},
    ],
)
async def test_variant_frequency_malformed_af_rejected_without_sampled_alleles(
    respx_mock: respx.MockRouter, cohort: dict[str, Any]
) -> None:
    """A malformed AF is an invalid response, not missing data, whatever AN is."""
    respx_mock.post("https://gnomad.broadinstitute.org/api").mock(
        return_value=httpx.Response(
            200, json={"data": {"variant": {"variantId": "1-1-A-G", "exome": cohort}}}
        )
    )
    async with GnomADClient() as client:
        with pytest.raises(ValueError, match="Invalid gnomAD allele frequency"):
            await client.variant_frequencies("1-1-A-G")


async def test_variant_frequency_contradiction_in_second_cohort_rejected(
    respx_mock: respx.MockRouter,
) -> None:
    """The cohort that is not summarised is held to the same rule."""
    variant = {
        "variantId": "1-1-A-G",
        "exome": {"ac": 0, "an": 1000, "af": 0},
        "genome": {"ac": 1, "an": 200, "af": 0.05},
    }
    respx_mock.post("https://gnomad.broadinstitute.org/api").mock(
        return_value=httpx.Response(200, json={"data": {"variant": variant}})
    )
    async with GnomADClient() as client:
        with pytest.raises(ValueError, match="contradicts"):
            await client.variant_frequencies("1-1-A-G")


async def test_variant_frequency_population_rule_leaves_out_only_sex_strata(
    respx_mock: respx.MockRouter,
) -> None:
    """A record is dropped only when it names a sex or splits a listed record by sex."""
    cohort = {
        "ac": 10,
        "an": 1000,
        "af": 0.01,
        "populations": [
            {"id": "nfe", "ac": 6, "an": 600},
            {"id": "nfe_XX", "ac": 2, "an": 300},  # sex stratum of the listed nfe
            {"id": "nfe_XY", "ac": 4, "an": 300},
            {"id": "eas", "ac": 4, "an": 400},
            {"id": "eas_jpn", "ac": 1, "an": 100},  # a named sub-population (gnomad_r2_1)
            {"id": "XX", "ac": 5, "an": 500},  # the cohort split by sex
            {"id": "xy", "ac": 5, "an": 500},  # any case, as before
            {"id": "1kg:acb", "ac": 1, "an": 50},  # a population of a subset
            {"id": "1kg:acb_XX", "ac": 1, "an": 20},  # its sex stratum
            {"id": "1kg:XY", "ac": 1, "an": 30},  # the subset split by sex
            {"id": "new_XY", "ac": 1, "an": 10},  # no "new" record: its only counts
            {"id": "a-b", "ac": 1, "an": 10},  # not dropped for its spelling
        ],
    }
    respx_mock.post("https://gnomad.broadinstitute.org/api").mock(
        return_value=httpx.Response(
            200, json={"data": {"variant": {"variantId": "1-1-A-G", "exome": cohort}}}
        )
    )
    async with GnomADClient() as client:
        out = await client.variant_frequencies("1-1-A-G")
    assert [
        (p["population"], p["allele_count"], p["allele_number"]) for p in out["populations"]
    ] == [
        ("Non-Finnish European", 6, 600),
        ("East Asian", 4, 400),
        ("eas_jpn", 1, 100),
        ("1kg:acb", 1, 50),
        ("new_XY", 1, 10),
        ("a-b", 1, 10),
    ]


async def test_variant_frequency_population_missing_denominator_skipped(
    respx_mock: respx.MockRouter,
) -> None:
    cohort = {
        "ac": 0,
        "an": 100,
        "af": 0.0,
        "populations": [
            {"id": "nfe", "ac": 0, "an": 0},
            {"id": "fin", "ac": 0, "an": True},
            {"id": "eas", "ac": 0, "an": None},
            {"id": "afr", "ac": 0, "an": 10},
        ],
    }
    respx_mock.post("https://gnomad.broadinstitute.org/api").mock(
        return_value=httpx.Response(
            200, json={"data": {"variant": {"variantId": "1-1-A-G", "exome": cohort}}}
        )
    )
    async with GnomADClient() as client:
        out = await client.variant_frequencies("1-1-A-G")
    assert len(out["populations"]) == 1
    assert out["populations"][0]["population"] == "African/African-American"


@pytest.mark.parametrize("allele_count", [None, True, -1, 10])
async def test_variant_frequency_population_malformed_count_rejected(
    respx_mock: respx.MockRouter, allele_count: Any
) -> None:
    cohort = {
        "ac": 0,
        "an": 100,
        "af": 0.0,
        "populations": [{"id": "nfe", "ac": allele_count, "an": 3}],
    }
    respx_mock.post("https://gnomad.broadinstitute.org/api").mock(
        return_value=httpx.Response(
            200, json={"data": {"variant": {"variantId": "1-1-A-G", "exome": cohort}}}
        )
    )
    async with GnomADClient() as client:
        with pytest.raises(ValueError):
            await client.variant_frequencies("1-1-A-G")


# ---------------------------------------------------------------------------
# Homozygote counts
# ---------------------------------------------------------------------------


def _record_with_homozygotes(
    where: str, value: Any, *, ac: int | None = 5, an: int | None = 100
) -> dict[str, Any]:
    """Two cohorts of ``ac`` alleles in ``an``; ``where`` gets the homozygote count.

    ``where`` is ``exome``, ``genome`` or ``population`` (the listed ``nfe``
    record of the exome cohort, which has 5 alleles in 100).
    """
    record: dict[str, Any] = {
        name: {
            "ac": ac,
            "an": an,
            "ac_hom": 0,
            "populations": [{"id": "nfe", "ac": 5, "an": 100, "ac_hom": 0}],
        }
        for name in ("exome", "genome")
    }
    target = record["exome"]["populations"][0] if where == "population" else record[where]
    target["ac_hom"] = value
    return record


def _mock_variant(respx_mock: respx.MockRouter, variant_id: str, record: dict[str, Any]) -> None:
    respx_mock.post("https://gnomad.broadinstitute.org/api").mock(
        return_value=httpx.Response(
            200, json={"data": {"variant": {"variantId": variant_id, **record}}}
        )
    )


def _reported_homozygotes(out: dict[str, Any]) -> dict[str, Any]:
    """Every place the client's result carries a homozygote count."""
    return {
        "summary": out["homozygote_count"],
        "exome": out["cohorts"]["exome"]["homozygote_count"],
        "genome": out["cohorts"]["genome"]["homozygote_count"],
        "population": out["populations"][0]["homozygote_count"],
    }


@pytest.mark.parametrize("where", ["exome", "genome", "population"])
@pytest.mark.parametrize("value", [True, -1, 1.0, "1", 6])
async def test_variant_frequency_malformed_homozygote_count_rejected(
    respx_mock: respx.MockRouter, where: str, value: Any
) -> None:
    """A homozygote count is passed on only as a whole number its 5 alleles allow.

    The variant is on X, so no ploidy is assumed: 6 homozygotes are rejected
    because each carries the allele at least once.
    """
    _mock_variant(respx_mock, "X-1-A-G", _record_with_homozygotes(where, value))
    async with GnomADClient() as client:
        with pytest.raises(ValueError, match="homozygote count"):
            await client.variant_frequencies("X-1-A-G")


@pytest.mark.parametrize("where", ["exome", "genome", "population"])
@pytest.mark.parametrize(
    ("variant_id", "homozygotes", "accepted"),
    [
        ("1-1-A-G", 2, True),  # two diploid homozygotes: 4 of the 5 alleles
        ("1-1-A-G", 3, False),  # three would carry 6
        ("22-1-A-G", 3, False),
        ("X-1-A-G", 3, True),  # ploidy is not assumed off the autosomes
        ("Y-1-A-G", 5, True),
    ],
)
async def test_variant_frequency_homozygote_bound_is_diploid_only_on_autosomes(
    respx_mock: respx.MockRouter, where: str, variant_id: str, homozygotes: int, accepted: bool
) -> None:
    _mock_variant(respx_mock, variant_id, _record_with_homozygotes(where, homozygotes))
    async with GnomADClient() as client:
        if not accepted:
            with pytest.raises(ValueError, match="exceeds what its allele count or number allows"):
                await client.variant_frequencies(variant_id)
            return
        reported = _reported_homozygotes(await client.variant_frequencies(variant_id))
    assert reported[where] == homozygotes
    # The summary repeats the exome cohort's count; every other count is the 0 it was given.
    expected = {"summary": 0, "exome": 0, "genome": 0, "population": 0, where: homozygotes}
    if where == "exome":
        expected["summary"] = homozygotes
    assert reported == expected


@pytest.mark.parametrize("unreported", ["null", "absent"])
async def test_variant_frequency_unreported_homozygote_count_stays_unreported(
    respx_mock: respx.MockRouter, unreported: str
) -> None:
    """A count gnomAD does not report is not a count of 0, and nothing else is withheld."""
    record = _record_with_homozygotes("exome", None)
    for cohort in record.values():
        for target in (cohort, cohort["populations"][0]):
            if unreported == "absent":
                del target["ac_hom"]
            else:
                target["ac_hom"] = None
    _mock_variant(respx_mock, "1-1-A-G", record)
    async with GnomADClient() as client:
        out = await client.variant_frequencies("1-1-A-G")
    assert _reported_homozygotes(out) == {
        "summary": None,
        "exome": None,
        "genome": None,
        "population": None,
    }
    assert out["global_af"] == 0.05
    assert out["populations"][0]["allele_count"] == 5


@pytest.mark.parametrize(
    ("variant_id", "an", "homozygotes", "accepted"),
    [
        ("1-1-A-G", 100, 50, True),  # 50 diploid homozygotes account for all 100 alleles
        ("1-1-A-G", 100, 51, False),
        ("X-1-A-G", 100, 100, True),
        ("X-1-A-G", 100, 101, False),
        ("1-1-A-G", None, 7, True),  # nothing reported that the count could contradict
    ],
)
async def test_variant_frequency_homozygote_count_without_allele_count_is_bounded_by_allele_number(
    respx_mock: respx.MockRouter, variant_id: str, an: int | None, homozygotes: int, accepted: bool
) -> None:
    record = _record_with_homozygotes("genome", homozygotes, ac=None, an=an)
    _mock_variant(respx_mock, variant_id, record)
    async with GnomADClient() as client:
        if not accepted:
            with pytest.raises(ValueError, match="exceeds what its allele count or number allows"):
                await client.variant_frequencies(variant_id)
            return
        out = await client.variant_frequencies(variant_id)
    assert out["cohorts"]["genome"]["homozygote_count"] == homozygotes


# ---------------------------------------------------------------------------
# gene_constraint
# ---------------------------------------------------------------------------


async def test_gene_constraint_unavailable(respx_mock: respx.MockRouter) -> None:
    respx_mock.post("https://gnomad.broadinstitute.org/api").mock(
        return_value=httpx.Response(200, json={"data": {"gene": None}}),
    )
    async with GnomADClient() as client:
        result = await client.gene_constraint("FOO")
    assert result["constraint_available"] is False


async def test_gene_constraint_full(respx_mock: respx.MockRouter) -> None:
    respx_mock.post("https://gnomad.broadinstitute.org/api").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "gene": {
                        "gnomad_constraint": {
                            "pLI": 0.99,
                            "loeuf": 0.21,
                            "mis_z": 4.5,
                            "oe_lof_upper": 0.21,
                        }
                    }
                }
            },
        ),
    )
    async with GnomADClient() as client:
        result = await client.gene_constraint("BRCA1")
    assert result["constraint_available"] is True
    assert result["loeuf"] == 0.21
    assert "Highly constrained" in result["interpretation"]


async def test_gene_constraint_empty_constraint_dict(respx_mock: respx.MockRouter) -> None:
    """A gene with no constraint sub-document → unavailable branch."""
    respx_mock.post("https://gnomad.broadinstitute.org/api").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"gene": {"gnomad_constraint": None}}},
        ),
    )
    async with GnomADClient() as client:
        result = await client.gene_constraint("FOO")
    assert result == {"gene_symbol": "FOO", "constraint_available": False}
