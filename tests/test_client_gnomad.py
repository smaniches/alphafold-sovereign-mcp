# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Full-coverage tests for ``alphafold_sovereign.clients.gnomad``.

Mocks the gnomAD GraphQL endpoint, covers every population-filter
branch and every constraint-interpretation tier.
"""

from __future__ import annotations

import httpx
import respx

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


def test_interpret_constraint_moderately_constrained() -> None:
    msg = _interpret_constraint({"loeuf": 0.45})
    assert "Moderately constrained" in msg


def test_interpret_constraint_tolerant() -> None:
    msg = _interpret_constraint({"loeuf": 0.9})
    assert "Tolerant to loss-of-function" in msg


# ---------------------------------------------------------------------------
# variant_frequencies
# ---------------------------------------------------------------------------


async def test_variant_frequencies_not_found(respx_mock: respx.MockRouter) -> None:
    respx_mock.post("https://gnomad.broadinstitute.org/api").mock(
        return_value=httpx.Response(200, json={"data": {"variant": None}}),
    )
    async with GnomADClient() as client:
        result = await client.variant_frequencies("1-2-A-G")
    assert result["found"] is False
    assert result["global_af"] is None
    assert result["populations"] == []


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
                                # Skipped: contains "-"
                                {"id": "nfe-XX", "ac": 0, "an": 0, "ac_hom": 0},
                                # Skipped: XX sex stratum
                                {"id": "XX", "ac": 1, "an": 1, "ac_hom": 0},
                                # Skipped: XY sex stratum (separate branch)
                                {"id": "XY", "ac": 2, "an": 2, "ac_hom": 0},
                                # Kept: maps via _POP_LABELS
                                {"id": "nfe", "ac": 3, "an": 100, "ac_hom": 0},
                                # Kept but unknown id (no _POP_LABELS hit)
                                {"id": "unknown", "ac": 1, "an": 50, "ac_hom": 1},
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
    # We expect exactly 3 entries: nfe, unknown, afr
    assert len(populations) == 3
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
                            "ac": None,  # → 0
                            "an": None,  # → 0 ⇒ _af_safe(0,0)=0.0
                            "af": None,  # → fall through to _af_safe
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
    assert result["global_af"] == 0.0


async def test_variant_frequencies_no_cohort_data(respx_mock: respx.MockRouter) -> None:
    """No exome AND no genome → cohort = {} → global_af = _af_safe(0,0) = 0.0."""
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
    assert result["global_af"] == 0.0


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
