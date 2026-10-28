# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Full-coverage tests for ``alphafold_sovereign.clients.opentargets``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from alphafold_sovereign.clients._base import UpstreamError
from alphafold_sovereign.clients.opentargets import (
    OpenTargetsClient,
    _observed_score,
    _observed_tractable,
    _to_curie,
)

_GQL_URL = "https://api.platform.opentargets.org/api/v4/graphql"


# ---------------------------------------------------------------------------
# Static helpers
# ---------------------------------------------------------------------------


def test_extract_uniprot_match() -> None:
    pids = [
        {"id": "NX1", "source": "neXtProt"},
        {"id": "P38398", "source": "uniprot_swissprot"},
    ]
    assert OpenTargetsClient._extract_uniprot(pids) == "P38398"


def test_extract_uniprot_uppercase_source() -> None:
    pids = [{"id": "Q1", "source": "UniProt"}]
    assert OpenTargetsClient._extract_uniprot(pids) == "Q1"


def test_extract_uniprot_none() -> None:
    pids = [{"id": "X", "source": "RefSeq"}]
    assert OpenTargetsClient._extract_uniprot(pids) == ""


def test_datatype_scores_builds_dict() -> None:
    rows = [
        {"id": "genetic_association", "score": 0.7},
        {"id": "literature", "score": 0.2},
    ]
    out = OpenTargetsClient._datatype_scores(rows)
    assert out == {"genetic_association": 0.7, "literature": 0.2}


def test_datatype_scores_missing_is_not_zero() -> None:
    rows = [{"id": "x"}]
    with pytest.raises(ValueError, match="Open Targets score"):
        OpenTargetsClient._datatype_scores(rows)


def test_row_to_score_full() -> None:
    row = {
        "disease": {"id": "MONDO:1", "name": "Cancer"},
        "score": 0.85,
        "datatypeScores": [
            {"id": "genetic_association", "score": 0.5},
        ],
    }
    score = OpenTargetsClient._row_to_score(row, "ENSG1", "BRCA1", "P38398")
    assert score.target_ensembl_id == "ENSG1"
    assert score.disease_mondo_id == "MONDO:1"
    assert score.genetic_association == 0.5


def test_row_to_score_missing_disease_uses_defaults() -> None:
    score = OpenTargetsClient._row_to_score({"score": 0.0}, "ENSG1", "X", "")
    assert score.disease_mondo_id == ""
    assert score.disease_name == ""
    assert score.overall_score == 0.0
    assert score.genetic_association == 0.0
    assert score.evidence_datatypes_reported == ()
    assert score.drug_count is None


def test_to_curie_underscore_to_colon() -> None:
    assert _to_curie("MONDO_0007254") == "MONDO:0007254"


def test_to_curie_efo_underscore() -> None:
    # Open Targets also returns EFO disease ids; the prefix is preserved.
    assert _to_curie("EFO_0000305") == "EFO:0000305"


def test_to_curie_already_colon_is_noop() -> None:
    assert _to_curie("MONDO:0007254") == "MONDO:0007254"


def test_to_curie_falsy_or_non_string_is_empty() -> None:
    # Empty, None (a null upstream id), and non-string ids collapse to "" and
    # never raise -- disease.get("id") can be None when the key is present.
    assert _to_curie("") == ""
    assert _to_curie(None) == ""
    assert _to_curie(12345) == ""


def test_to_curie_non_alpha_prefix_is_noop() -> None:
    # No alphabetic prefix -> don't invent a CURIE; leave untouched.
    assert _to_curie("0007254_x") == "0007254_x"


def test_row_to_score_normalises_underscore_disease_id() -> None:
    # The live Open Targets API returns underscore-form disease ids; the mapped
    # output must be canonical colon-form CURIE (the #52 output-side fix).
    row = {"disease": {"id": "MONDO_0007254", "name": "breast carcinoma"}, "score": 0.4}
    score = OpenTargetsClient._row_to_score(row, "ENSG1", "BRCA1", "P38398")
    assert score.disease_mondo_id == "MONDO:0007254"


async def test_associated_targets_normalises_output_curie(
    respx_mock: respx.MockRouter,
) -> None:
    # Caller passes underscore form; the returned disease_mondo_id must be the
    # canonical colon-form CURIE rather than echoing the input verbatim.
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "disease": {
                        "id": "MONDO_0007254",
                        "name": "breast carcinoma",
                        "associatedTargets": {
                            "rows": [
                                {
                                    "target": {
                                        "id": "ENSG1",
                                        "approvedSymbol": "BRCA1",
                                        "proteinIds": [],
                                        "tractability": None,
                                    },
                                    "score": 0.7,
                                    "datatypeScores": [],
                                }
                            ]
                        },
                    }
                }
            },
        ),
    )
    async with OpenTargetsClient() as client:
        scores = await client.associated_targets("MONDO_0007254")
    assert len(scores) == 1
    assert scores[0].disease_mondo_id == "MONDO:0007254"


# ---------------------------------------------------------------------------
# associated_diseases
# ---------------------------------------------------------------------------


async def test_associated_diseases_full_flow(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "target": {
                        "id": "ENSG0001",
                        "approvedSymbol": "BRCA1",
                        "proteinIds": [{"id": "P38398", "source": "uniprot_swissprot"}],
                        "associatedDiseases": {
                            "rows": [
                                {
                                    "disease": {"id": "MONDO:1", "name": "Cancer"},
                                    "score": 0.9,
                                    "datatypeScores": [
                                        {
                                            "id": "genetic_association",
                                            "score": 0.8,
                                        }
                                    ],
                                }
                            ]
                        },
                    }
                }
            },
        ),
    )
    async with OpenTargetsClient() as client:
        scores = await client.associated_diseases("ENSG0001", limit=5)
    assert len(scores) == 1
    assert scores[0].target_gene_symbol == "BRCA1"
    assert scores[0].uniprot_id == "P38398"
    assert scores[0].overall_score == 0.9


async def test_associated_diseases_reports_observed_drug_count_and_tractability(
    respx_mock: respx.MockRouter,
) -> None:
    """Existing-client contract: successful rows carry an int and a bool.

    Both values are requested in the same query (live 2026-10-28: BRCA1 has
    0 drug records and 28 tractability entries), never imputed.
    """
    route = respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "target": {
                        "id": "ENSG00000012048",
                        "approvedSymbol": "BRCA1",
                        "proteinIds": [{"id": "P38398", "source": "uniprot_swissprot"}],
                        "drugAndClinicalCandidates": {"count": 0},
                        "tractability": [
                            {"label": "Approved Drug", "modality": "SM", "value": False},
                            {"label": "Small Molecule Binder", "modality": "SM", "value": True},
                        ],
                        "associatedDiseases": {
                            "rows": [
                                {
                                    "disease": {"id": "MONDO_0007254", "name": "breast cancer"},
                                    "score": 0.844,
                                    "datatypeScores": [{"id": "literature", "score": 0.6}],
                                }
                            ]
                        },
                    }
                }
            },
        ),
    )
    async with OpenTargetsClient() as client:
        scores = await client.associated_diseases("ENSG00000012048")
    public = scores[0].to_dict()
    assert public["drug_count"] == 0 and isinstance(public["drug_count"], int)
    assert public["tractable"] is True
    body = route.calls.last.request.content.decode()
    assert "drugAndClinicalCandidates { count }" in body
    assert "tractability" in body


async def test_associated_diseases_missing_fields_stay_unknown(
    respx_mock: respx.MockRouter,
) -> None:
    """Scientific missingness: an omitted source field is null, not 0/False."""
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "target": {
                        "id": "ENSG1",
                        "approvedSymbol": "X",
                        "proteinIds": [],
                        "associatedDiseases": {
                            "rows": [
                                {
                                    "disease": {"id": "MONDO_1", "name": "d"},
                                    "score": 0.1,
                                    "datatypeScores": [],
                                }
                            ]
                        },
                    }
                }
            },
        ),
    )
    async with OpenTargetsClient() as client:
        scores = await client.associated_diseases("ENSG1")
    assert scores[0].drug_count is None
    assert scores[0].tractable is None


async def test_associated_diseases_rejects_malformed_drug_count(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "target": {
                        "id": "ENSG1",
                        "drugAndClinicalCandidates": {"count": -3},
                        "associatedDiseases": {"rows": []},
                    }
                }
            },
        ),
    )
    async with OpenTargetsClient() as client:
        with pytest.raises(ValueError, match="nonnegative integer"):
            await client.associated_diseases("ENSG1")


async def test_associated_diseases_no_target_data(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"target": None}}),
    )
    async with OpenTargetsClient() as client:
        scores = await client.associated_diseases("ENSG_BAD")
    assert scores == []


async def test_associated_diseases_clamps_limit_high(
    respx_mock: respx.MockRouter,
) -> None:
    """A request limit above 200 is clamped down."""
    route = respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"target": {}}}),
    )
    async with OpenTargetsClient() as client:
        await client.associated_diseases("ENSG1", limit=9999)
    body = route.calls.last.request.content.decode()
    assert '"size":200' in body


async def test_associated_diseases_clamps_limit_low(
    respx_mock: respx.MockRouter,
) -> None:
    """A request limit at zero is clamped up to 1."""
    route = respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"target": {}}}),
    )
    async with OpenTargetsClient() as client:
        await client.associated_diseases("ENSG1", limit=0)
    body = route.calls.last.request.content.decode()
    assert '"size":1' in body


# ---------------------------------------------------------------------------
# associated_targets
# ---------------------------------------------------------------------------


async def test_associated_targets_full_flow(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "disease": {
                        "id": "MONDO:1",
                        "name": "Breast carcinoma",
                        "associatedTargets": {
                            "rows": [
                                {
                                    "target": {
                                        "id": "ENSG2",
                                        "approvedSymbol": "TP53",
                                        "proteinIds": [
                                            {"id": "P04637", "source": "uniprot_swissprot"}
                                        ],
                                        "drugAndClinicalCandidates": {"count": 9},
                                        "tractability": [
                                            {"label": "high_quality_pocket", "value": True}
                                        ],
                                    },
                                    "score": 0.95,
                                    "datatypeScores": [
                                        {
                                            "id": "genetic_association",
                                            "score": 0.9,
                                        },
                                        {
                                            "id": "known_drug",
                                            "score": 0.4,
                                        },
                                    ],
                                },
                                {
                                    "target": {
                                        "id": "ENSG3",
                                        "approvedSymbol": "BRCA1",
                                        "proteinIds": [],
                                        "tractability": None,
                                    },
                                    "score": 0.5,
                                    "datatypeScores": [],
                                },
                            ]
                        },
                    }
                }
            },
        ),
    )
    async with OpenTargetsClient() as client:
        scores = await client.associated_targets("MONDO:1")
    assert len(scores) == 2
    # Sorted desc by overall_score
    assert scores[0].overall_score == 0.95
    assert scores[0].tractable is True
    # Existing-client contract: the observed count is an int on the row.
    assert scores[0].drug_count == 9
    # Source omitted both fields for the second target: unknown, not 0/False.
    assert scores[1].tractable is None
    assert scores[1].drug_count is None


async def test_associated_targets_disease_null(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"disease": None}}),
    )
    async with OpenTargetsClient() as client:
        scores = await client.associated_targets("MONDO:NONE")
    assert scores == []


async def test_associated_targets_clamps_limit(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"disease": {}}}),
    )
    async with OpenTargetsClient() as client:
        await client.associated_targets("MONDO:1", limit=-5)
    body = route.calls.last.request.content.decode()
    assert '"size":1' in body
    # Regression: colon-form CURIEs must be normalised to Open Targets'
    # underscore form (MONDO:1 -> MONDO_1), or the disease is not found and
    # every query silently returns zero targets.
    assert "MONDO_1" in body
    assert "MONDO:1" not in body


# ---------------------------------------------------------------------------
# drug_count_and_tractability
# ---------------------------------------------------------------------------


async def test_drug_count_and_tractability(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "target": {
                        "drugAndClinicalCandidates": {"count": 5},
                        "tractability": [
                            {"label": "A", "value": True},
                            {"label": "B", "value": False},
                        ],
                    }
                }
            },
        ),
    )
    async with OpenTargetsClient() as client:
        info = await client.drug_count_and_tractability("ENSG1")
    assert info["drug_count"] == 5
    assert info["tractability_labels"] == ["A"]


@pytest.mark.parametrize(
    "tractability",
    [[{"value": None}], [{}], [None], [{"label": "A", "value": "yes"}], [{"value": True}, {}]],
)
def test_observed_tractable_incomplete_list_is_unknown(tractability: list[Any]) -> None:
    """A bucket without a boolean is not an observed negative assessment."""
    assert _observed_tractable({"tractability": tractability}) is None


@pytest.mark.parametrize(
    ("tractability", "expected"),
    [([], False), ([{"value": False}], False), ([{"value": False}, {"value": True}], True)],
)
def test_observed_tractable_validated_list(tractability: list[Any], expected: bool) -> None:
    assert _observed_tractable({"tractability": tractability}) is expected


async def test_drug_count_and_tractability_rejects_malformed_list(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "target": {
                        "drugAndClinicalCandidates": {"count": 2},
                        "tractability": [{"label": "A", "value": True}, {"label": "B"}],
                    }
                }
            },
        ),
    )
    async with OpenTargetsClient() as client:
        with pytest.raises(ValueError, match="tractability list is malformed"):
            await client.drug_count_and_tractability("ENSG1")


async def test_drug_count_and_tractability_no_target(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"target": None}}),
    )
    async with OpenTargetsClient() as client:
        info = await client.drug_count_and_tractability("ENSG_BAD")
    assert info["drug_count"] is None
    assert info["tractability_labels"] == []


async def test_drug_count_and_tractability_null_tractability(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "target": {"drugAndClinicalCandidates": {"count": 0}, "tractability": None}
                }
            },
        ),
    )
    async with OpenTargetsClient() as client:
        info = await client.drug_count_and_tractability("ENSG1")
    assert info["tractability_labels"] == []
    assert info["drug_count"] == 0  # An explicit observed zero remains zero.


@pytest.mark.parametrize("target", [{}, {"drugAndClinicalCandidates": None}])
async def test_drug_count_and_tractability_unavailable_count_is_not_zero(
    respx_mock: respx.MockRouter, target: dict[str, Any]
) -> None:
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"target": target}})
    )
    async with OpenTargetsClient() as client:
        info = await client.drug_count_and_tractability("ENSG1")
    assert info["drug_count"] is None
    assert info["tractability_labels"] == []


# ---------------------------------------------------------------------------
# resolve_target
# ---------------------------------------------------------------------------


def _mapped_hits(*hits: dict[str, Any]) -> dict[str, Any]:
    return {"data": {"mapIds": {"mappings": [{"hits": list(hits)}]}}}


def _target_hit(ensembl: str, symbol: str, *uniprot_ids: str) -> dict[str, Any]:
    return {
        "id": ensembl,
        "name": symbol,
        "object": {
            "id": ensembl,
            "approvedSymbol": symbol,
            "proteinIds": [
                {"id": accession, "source": "uniprot_swissprot"} for accession in uniprot_ids
            ],
        },
    }


async def test_resolve_target_found(respx_mock: respx.MockRouter) -> None:
    """A verified UniProt accession maps to its Ensembl gene ID."""
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(
            200, json=_mapped_hits(_target_hit("ENSG00000133703", "KRAS", "P01116"))
        )
    )
    async with OpenTargetsClient() as client:
        resolved = await client.resolve_target("P01116")
    assert resolved == {"ensembl_id": "ENSG00000133703", "symbol": "KRAS"}
    assert b"mapIds" in respx_mock.calls[0].request.content


async def test_resolve_target_gene_symbol_is_exact(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(
            200,
            json=_mapped_hits(
                _target_hit("ENSG00000139618", "BRCA2"),
                _target_hit("ENSG00000012048", "BRCA1"),
            ),
        )
    )
    async with OpenTargetsClient() as client:
        resolved = await client.resolve_target("BRCA1")
    assert resolved == {"ensembl_id": "ENSG00000012048", "symbol": "BRCA1"}


async def test_resolve_target_does_not_accept_first_unrelated_hit(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(
            200,
            json=_mapped_hits(
                _target_hit("ENSG000001", "OTHER", "P99999"),
                _target_hit("ENSG00000133703", "KRAS", "P01116"),
            ),
        )
    )
    async with OpenTargetsClient() as client:
        assert await client.resolve_target("P01116") == {
            "ensembl_id": "ENSG00000133703",
            "symbol": "KRAS",
        }


async def test_resolve_target_skips_non_target_hits(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(
            200,
            json=_mapped_hits(
                {"id": "EFO_0000305", "object": None},
                {"id": "ENSG9999", "object": {"id": "ENSG0001", "approvedSymbol": "X"}},
                {"id": 42, "object": {"id": 42, "approvedSymbol": "X"}},
                {"id": "ENSG0002", "object": {"id": "ENSG0002", "approvedSymbol": None}},
            ),
        )
    )
    async with OpenTargetsClient() as client:
        assert await client.resolve_target("P01116") == {}


async def test_resolve_target_unverified_accession_is_not_a_hit(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(
            200, json=_mapped_hits(_target_hit("ENSG00000133703", "KRAS", "P99999"))
        )
    )
    async with OpenTargetsClient() as client:
        assert await client.resolve_target("P01116") == {}


async def test_resolve_target_ambiguous_accession_is_not_arbitrarily_selected(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(
            200,
            json=_mapped_hits(
                _target_hit("ENSG00000107077", "KDM4C", "Q9H3R0"),
                _target_hit("ENSG00000293552", "ENSG00000293552", "Q9H3R0"),
            ),
        )
    )
    async with OpenTargetsClient() as client:
        with pytest.raises(ValueError, match="ambiguous"):
            await client.resolve_target("Q9H3R0")


async def test_resolve_target_identifier_shaped_gene_symbol(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(
            200, json=_mapped_hits(_target_hit("ENSG00000109956", "B3GAT1"))
        )
    )
    async with OpenTargetsClient() as client:
        assert await client.resolve_target("B3GAT1") == {
            "ensembl_id": "ENSG00000109956",
            "symbol": "B3GAT1",
        }


async def test_resolve_target_rejects_cross_namespace_ambiguity(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(
            200,
            json=_mapped_hits(
                _target_hit("ENSG00000109956", "B3GAT1"),
                _target_hit("ENSG00000999999", "OTHER", "B3GAT1"),
            ),
        )
    )
    async with OpenTargetsClient() as client:
        with pytest.raises(ValueError, match="ambiguous"):
            await client.resolve_target("B3GAT1")


async def test_resolve_target_no_exact_gene_symbol_does_not_accept_alias(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(200, json=_mapped_hits(_target_hit("ENSG00000139618", "BRCA2")))
    )
    async with OpenTargetsClient() as client:
        assert await client.resolve_target("BRCA1") == {}


async def test_resolve_target_empty_hits_is_valid_no_mapping(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(_GQL_URL).mock(return_value=httpx.Response(200, json=_mapped_hits()))
    async with OpenTargetsClient() as client:
        assert await client.resolve_target("P01116") == {}


@pytest.mark.parametrize(
    "invalid_payload",
    [
        {"data": {"mapIds": None}},
        {"data": {"mapIds": {"mappings": []}}},
        {"data": {"mapIds": {"mappings": [None]}}},
        {"data": {"mapIds": {"mappings": [{"hits": None}]}}},
        _mapped_hits("not-a-dict"),
    ],
)
async def test_resolve_target_malformed_mapping_fails_closed(
    respx_mock: respx.MockRouter, invalid_payload: dict[str, Any]
) -> None:
    respx_mock.post(_GQL_URL).mock(return_value=httpx.Response(200, json=invalid_payload))
    async with OpenTargetsClient() as client:
        with pytest.raises(ValueError, match="Open Targets"):
            await client.resolve_target("P01116")


# ---------------------------------------------------------------------------
# # resolve_disease_efo
# ---------------------------------------------------------------------------


_MAPIDS_FIXTURE = Path(__file__).parent / "fixtures" / "opentargets_mapids_20261028.json"


@pytest.mark.parametrize(
    ("term", "expected"),
    [
        ("P38398", {"ensembl_id": "ENSG00000012048", "symbol": "BRCA1"}),
        ("P04637", {"ensembl_id": "ENSG00000141510", "symbol": "TP53"}),
        ("B3GAT1", {"ensembl_id": "ENSG00000109956", "symbol": "B3GAT1"}),
        ("Q99999999", {}),
        ("XYZNOTAGENE123", {}),
    ],
)
async def test_resolve_target_recorded_live_mapids_examples(
    respx_mock: respx.MockRouter, term: str, expected: dict[str, str]
) -> None:
    """Replay recorded live ``mapIds`` responses (see fixture ``meta``).

    The fixture is a sanitised capture of the deployed Open Targets GraphQL
    API, not a hand-authored shape; its ``meta`` records the API/data release
    and retrieval date so a future schema drift can be re-verified.
    """
    fixture = json.loads(_MAPIDS_FIXTURE.read_text())
    assert fixture["meta"]["api_version"] and fixture["meta"]["data_version"]
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(200, json=fixture["responses"][term])
    )
    async with OpenTargetsClient() as client:
        assert await client.resolve_target(term) == expected
    sent = json.loads(respx_mock.calls.last.request.content)
    assert sent["variables"] == {"q": term}
    assert "mapIds(queryTerms: [$q]" in sent["query"]


async def test_resolve_disease_efo_found(respx_mock: respx.MockRouter) -> None:
    """Returns the first EFO hit as a colon-form CURIE, skipping non-EFO hits."""
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "search": {
                        "hits": [
                            {"id": "MONDO_0007254", "entity": "disease", "name": "breast cancer"},
                            {"id": "EFO_0000305", "entity": "disease", "name": "breast cancer"},
                        ]
                    }
                }
            },
        ),
    )
    async with OpenTargetsClient() as client:
        assert await client.resolve_disease_efo("breast cancer") == "EFO:0000305"


async def test_resolve_disease_efo_no_efo_hit(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": {"search": {"hits": [{"id": "MONDO_0007254", "entity": "disease"}]}}},
        ),
    )
    async with OpenTargetsClient() as client:
        assert await client.resolve_disease_efo("breast cancer") == ""


async def test_resolve_disease_efo_error_returns_empty(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(_GQL_URL).mock(return_value=httpx.Response(500))
    async with OpenTargetsClient() as client:
        with pytest.raises(UpstreamError):
            await client.resolve_disease_efo("breast cancer")


async def test_resolve_disease_efo_null_data(respx_mock: respx.MockRouter) -> None:
    """A null GraphQL ``data`` payload yields '' without raising."""
    respx_mock.post(_GQL_URL).mock(return_value=httpx.Response(200, json={"data": None}))
    async with OpenTargetsClient() as client:
        assert await client.resolve_disease_efo("breast cancer") == ""


async def test_resolve_disease_efo_rejects_nonexact_search_hit(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "search": {
                        "hits": [
                            {"id": "EFO_0000305", "entity": "disease", "name": "breast carcinoma"},
                        ]
                    }
                }
            },
        )
    )
    async with OpenTargetsClient() as client:
        assert await client.resolve_disease_efo("breast cancer") == ""


async def test_resolve_disease_efo_rejects_ambiguous_identity(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "search": {
                        "hits": [
                            {"id": "EFO_0000305", "entity": "disease", "name": "breast cancer"},
                            {"id": "EFO_1000001", "entity": "disease", "name": "breast cancer"},
                        ]
                    }
                }
            },
        )
    )
    async with OpenTargetsClient() as client:
        assert await client.resolve_disease_efo("breast cancer") == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(0, 0.0), ("0.0", 0.0), (0.5, 0.5), (1, 1.0)],
)
def test_open_targets_observed_score_preserves_valid_values(raw: Any, expected: float) -> None:
    assert _observed_score(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [None, True, False, -0.1, 1.1, "invalid", float("nan"), float("inf")],
)
def test_open_targets_observed_score_rejects_invalid_source_values(raw: Any) -> None:
    with pytest.raises(ValueError, match="Open Targets score"):
        _observed_score(raw)


def test_open_targets_missing_association_score_cannot_become_zero() -> None:
    with pytest.raises(ValueError, match="Open Targets score"):
        OpenTargetsClient._row_to_score({}, "ENSG1", "X", "")


def test_open_targets_datatype_absence_vs_observed_zero() -> None:
    assert OpenTargetsClient._datatype_scores([]) == {}
    assert OpenTargetsClient._datatype_scores([{"id": "genetic_association", "score": 0.0}]) == {
        "genetic_association": 0.0
    }
    with pytest.raises(ValueError, match="score"):
        OpenTargetsClient._datatype_scores([{"id": "genetic_association", "score": None}])
    with pytest.raises(ValueError, match="array"):
        OpenTargetsClient._datatype_scores(None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="identity"):
        OpenTargetsClient._datatype_scores([{"score": 0.0}])
    with pytest.raises(ValueError, match="identity"):
        OpenTargetsClient._datatype_scores([None])  # type: ignore[list-item]


def test_open_targets_row_component_missing_vs_observed_zero() -> None:
    base = {
        "disease": {"id": "MONDO_1", "name": "Synthetic"},
        "score": 0.0,
        "datatypeScores": [{"id": "known_drug", "score": 0.0}],
    }
    out = OpenTargetsClient._row_to_score(base, "ENSG1", "SYNTH", "")
    assert out.overall_score == 0.0
    assert out.known_drug == 0.0
    # Open Targets lists only datatypes that contributed evidence; an absent
    # datatype is the platform's own zero, kept numeric for the published
    # contract, while the reported list preserves which ones were listed.
    assert out.genetic_association == 0.0
    assert out.evidence_datatypes_reported == ("known_drug",)
    assert out.drug_count is None
    public = out.to_dict()
    assert public["evidence_scores"]["known_drug"] == 0.0
    assert public["evidence_scores"]["genetic_association"] == 0.0
    assert public["evidence_datatypes_reported"] == ["known_drug"]


async def test_open_targets_sparse_components_stay_numeric_with_reported_list(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "disease": {
                        "id": "MONDO_1",
                        "name": "Synthetic",
                        "associatedTargets": {
                            "rows": [
                                {
                                    "target": {
                                        "id": "ENSG1",
                                        "approvedSymbol": "SYNTH",
                                        "proteinIds": [],
                                        "tractability": None,
                                    },
                                    "score": 0.0,
                                    "datatypeScores": [],
                                }
                            ]
                        },
                    }
                }
            },
        )
    )
    async with OpenTargetsClient() as client:
        scores = await client.associated_targets("MONDO:1")
    assert len(scores) == 1
    assert scores[0].overall_score == 0.0
    assert scores[0].genetic_association == 0.0
    assert scores[0].evidence_datatypes_reported == ()
    assert scores[0].tractable is None


@pytest.mark.parametrize("invalid_count", [True, False, -1, 0.5, "7"])
async def test_open_targets_malformed_drug_count_fails_closed(
    respx_mock: respx.MockRouter, invalid_count: Any
) -> None:
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "target": {
                        "drugAndClinicalCandidates": {"count": invalid_count},
                        "tractability": [],
                    }
                }
            },
        )
    )
    async with OpenTargetsClient() as client:
        with pytest.raises(ValueError, match="drug count"):
            await client.drug_count_and_tractability("ENSG1")
