# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Full-coverage tests for ``alphafold_sovereign.clients.opentargets``."""

from __future__ import annotations

import httpx
import respx

from alphafold_sovereign.clients.opentargets import OpenTargetsClient


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


def test_datatype_scores_default_when_missing() -> None:
    rows = [{"id": "x"}]
    out = OpenTargetsClient._datatype_scores(rows)
    assert out == {"x": 0.0}


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
    score = OpenTargetsClient._row_to_score({}, "ENSG1", "X", "")
    assert score.disease_mondo_id == ""
    assert score.disease_name == ""


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
    assert scores[1].tractable is False


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


async def test_drug_count_and_tractability_no_target(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"target": None}}),
    )
    async with OpenTargetsClient() as client:
        info = await client.drug_count_and_tractability("ENSG_BAD")
    assert info["drug_count"] == 0
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


# ---------------------------------------------------------------------------
# resolve_target
# ---------------------------------------------------------------------------


async def test_resolve_target_found(respx_mock: respx.MockRouter) -> None:
    """A UniProt accession resolves to its Ensembl gene ID and symbol."""
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "search": {
                        "hits": [{"id": "ENSG00000133703", "entity": "target", "name": "KRAS"}]
                    }
                }
            },
        ),
    )
    async with OpenTargetsClient() as client:
        resolved = await client.resolve_target("P01116")
    assert resolved == {"ensembl_id": "ENSG00000133703", "symbol": "KRAS"}


async def test_resolve_target_skips_non_target_hits(
    respx_mock: respx.MockRouter,
) -> None:
    """Non-target hits are skipped; with no target hit an empty dict is returned."""
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "search": {
                        "hits": [{"id": "EFO_0000305", "entity": "disease", "name": "breast"}]
                    }
                }
            },
        ),
    )
    async with OpenTargetsClient() as client:
        resolved = await client.resolve_target("not-a-target")
    assert resolved == {}


async def test_resolve_target_null_search(respx_mock: respx.MockRouter) -> None:
    """A null search payload yields an empty dict without raising."""
    respx_mock.post(_GQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"search": None}}),
    )
    async with OpenTargetsClient() as client:
        resolved = await client.resolve_target("P01116")
    assert resolved == {}
