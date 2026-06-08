# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Full-coverage tests for ``alphafold_sovereign.clients.hpo``.

Mocks the ontology.jax.org HPO REST endpoints and exercises the various
parsing branches (term details nesting, synonym shape variations,
network-annotation payloads, etc.).
"""

from __future__ import annotations

import httpx
import respx

from alphafold_sovereign.clients.hpo import (
    DiseaseByPhenotype,
    HPOClient,
    _normalise_hpo_id,
)

_BASE = "https://ontology.jax.org/api"


# ---------------------------------------------------------------------------
# _normalise_hpo_id
# ---------------------------------------------------------------------------


def test_normalise_hpo_id_bare_digits() -> None:
    assert _normalise_hpo_id("0001250") == "HP:0001250"


def test_normalise_hpo_id_underscore_form() -> None:
    assert _normalise_hpo_id("hp_0001250") == "HP:0001250"


def test_normalise_hpo_id_already_curie() -> None:
    assert _normalise_hpo_id("HP:0001250") == "HP:0001250"


def test_disease_by_phenotype_to_dict() -> None:
    d = DiseaseByPhenotype(
        disease_id="OMIM:1",
        disease_name="X",
        hpo_id="HP:0001250",
        mondo_id="MONDO:0001",
    )
    out = d.to_dict()
    assert out["disease_id"] == "OMIM:1"
    assert out["mondo_id"] == "MONDO:0001"


# ---------------------------------------------------------------------------
# lookup — exercises the defensive _parse_term branches
# ---------------------------------------------------------------------------


async def test_lookup_term_nested_details(respx_mock: respx.MockRouter) -> None:
    """When the payload nests under ``details``, prefer that branch."""
    respx_mock.get(f"{_BASE}/hp/terms/HP:0001250").mock(
        return_value=httpx.Response(
            200,
            json={
                "details": {
                    "id": "HP:0001250",
                    "name": "Seizure",
                    "definition": "An abnormal electrical activity in the brain.",
                    "synonyms": [
                        "Seizures",
                        {"label": "Convulsions"},
                    ],
                    "obsolete": False,
                }
            },
        ),
    )
    async with HPOClient() as client:
        term = await client.lookup("HP:0001250")
    assert term.id == "HP:0001250"
    assert term.label == "Seizure"
    assert "Seizures" in term.synonyms
    assert "Convulsions" in term.synonyms


async def test_lookup_term_top_level_id_fallback(respx_mock: respx.MockRouter) -> None:
    """Flat payload (the live ontology.jax.org shape): id/name/synonyms at top."""
    respx_mock.get(f"{_BASE}/hp/terms/HP:0009999").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "HP:0009999",
                "name": "Some Pheno",
                "synonyms": None,  # exercise the `or []` fallback
            },
        ),
    )
    async with HPOClient() as client:
        term = await client.lookup("HP:0009999")
    assert term.id == "HP:0009999"
    assert term.synonyms == ()


async def test_lookup_term_id_from_outer_when_details_missing_id(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get(f"{_BASE}/hp/terms/HP:0001000").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "HP:0001000",
                "details": {"name": "no-id-here"},
            },
        ),
    )
    async with HPOClient() as client:
        term = await client.lookup("HP:0001000")
    assert term.id == "HP:0001000"


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


async def test_search_clamps_max_results(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{_BASE}/hp/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "terms": [
                    {"id": "HP:0003198", "name": "Myopathy"},
                ],
                "totalCount": 1,
            },
        ),
    )
    async with HPOClient() as client:
        # max_results=999 clamps to 50; max_results=0 floors to 1
        results_high = await client.search("muscle", max_results=999)
        results_low = await client.search("muscle", max_results=0)
    assert results_high[0].label == "Myopathy"
    assert results_low[0].label == "Myopathy"


async def test_search_no_results(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{_BASE}/hp/search").mock(
        return_value=httpx.Response(200, json={}),
    )
    async with HPOClient() as client:
        results = await client.search("nothing")
    assert results == []


# ---------------------------------------------------------------------------
# diseases_for_phenotype  (/network/annotation/{hpo_id} -> diseases[])
# ---------------------------------------------------------------------------


async def test_diseases_for_phenotype_sorted(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{_BASE}/network/annotation/HP:0001250").mock(
        return_value=httpx.Response(
            200,
            json={
                "diseases": [
                    {"id": "OMIM:2", "name": "Zebra disease", "mondoId": "MONDO:0002"},
                    {"id": "OMIM:1", "name": "Alpha disease", "mondoId": None},
                ]
            },
        ),
    )
    async with HPOClient() as client:
        results = await client.diseases_for_phenotype("HP:0001250", limit=10)
    names = [r.disease_name for r in results]
    assert names == ["Alpha disease", "Zebra disease"]
    # The MONDO cross-reference is surfaced; ``None`` collapses to "".
    by_id = {r.disease_id: r for r in results}
    assert by_id["OMIM:2"].mondo_id == "MONDO:0002"
    assert by_id["OMIM:1"].mondo_id == ""


async def test_diseases_for_phenotype_empty(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{_BASE}/network/annotation/HP:0001250").mock(
        return_value=httpx.Response(200, json={}),
    )
    async with HPOClient() as client:
        results = await client.diseases_for_phenotype("HP:0001250")
    assert results == []


# ---------------------------------------------------------------------------
# phenotypes_for_gene_id  (/network/annotation/{ncbi_id} -> phenotypes[])
# ---------------------------------------------------------------------------


async def test_phenotypes_for_gene_id(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{_BASE}/network/annotation/NCBIGene:672").mock(
        return_value=httpx.Response(
            200,
            json={
                "phenotypes": [
                    {"id": "HP:0001250", "name": "Seizure"},
                    {"id": "HP:0002119", "name": "Ventriculomegaly"},
                ]
            },
        ),
    )
    async with HPOClient() as client:
        results = await client.phenotypes_for_gene_id("NCBIGene:672", gene_symbol="BRCA1", limit=5)
    assert results[0].hpo_id == "HP:0001250"
    assert results[0].gene_symbol == "BRCA1"
    assert len(results) == 2


async def test_phenotypes_for_gene_id_none_phenotypes(respx_mock: respx.MockRouter) -> None:
    """``phenotypes`` may be ``None`` ⇒ default empty list."""
    respx_mock.get(f"{_BASE}/network/annotation/NCBIGene:9999").mock(
        return_value=httpx.Response(200, json={"phenotypes": None}),
    )
    async with HPOClient() as client:
        results = await client.phenotypes_for_gene_id("NCBIGene:9999")
    assert results == []


# ---------------------------------------------------------------------------
# phenotypes_for_disease  (/network/annotation/{disease_id} -> categories{})
# ---------------------------------------------------------------------------


async def test_phenotypes_for_disease_with_metadata(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{_BASE}/network/annotation/OMIM:1").mock(
        return_value=httpx.Response(
            200,
            json={
                "disease": {"name": "Test disease"},
                "categories": {
                    "Neurologic": [
                        {
                            "id": "HP:0001",
                            "name": "Phen 1",
                            "metadata": {"frequency": "HP:0040281", "onset": "HP:0003577"},
                        },
                        {
                            "id": "HP:0002",
                            "name": "Phen 2",
                            # No metadata → frequency/onset fall through to "".
                        },
                    ]
                },
            },
        ),
    )
    async with HPOClient() as client:
        results = await client.phenotypes_for_disease("OMIM:1")
    assert len(results) == 2
    assert results[0].disease_name == "Test disease"
    assert results[0].onset == "HP:0003577"
    assert results[1].onset == ""


async def test_phenotypes_for_disease_inner_break(respx_mock: respx.MockRouter) -> None:
    """Hit the ``len(associations) >= limit`` break inside a category."""
    respx_mock.get(f"{_BASE}/network/annotation/OMIM:1").mock(
        return_value=httpx.Response(
            200,
            json={
                "categories": {
                    "A": [
                        {"id": "HP:1", "name": "A1"},
                        {"id": "HP:2", "name": "A2"},
                        {"id": "HP:3", "name": "A3"},
                    ],
                    "B": [
                        {"id": "HP:4", "name": "B1"},
                    ],
                },
            },
        ),
    )
    async with HPOClient() as client:
        results = await client.phenotypes_for_disease("OMIM:1", limit=2)
    assert len(results) == 2


# ---------------------------------------------------------------------------
# ancestors / children  (/hp/terms/{id}/parents|children -> list)
# ---------------------------------------------------------------------------


async def test_ancestors(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{_BASE}/hp/terms/HP:0001250/parents").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": "HP:0000118", "name": "Phenotypic abnormality"}],
        ),
    )
    async with HPOClient() as client:
        results = await client.ancestors("HP:0001250")
    assert results[0].label == "Phenotypic abnormality"


async def test_children(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{_BASE}/hp/terms/HP:0001250/children").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": "HP:0011168", "name": "Aura"}],
        ),
    )
    async with HPOClient() as client:
        results = await client.children("HP:0001250")
    assert results[0].id == "HP:0011168"


async def test_ancestors_non_list_payload(respx_mock: respx.MockRouter) -> None:
    """A non-list payload (e.g. an error object) yields an empty list."""
    respx_mock.get(f"{_BASE}/hp/terms/HP:0001250/parents").mock(
        return_value=httpx.Response(200, json={"error": "boom"}),
    )
    async with HPOClient() as client:
        assert await client.ancestors("HP:0001250") == []


async def test_children_non_list_payload(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{_BASE}/hp/terms/HP:0001250/children").mock(
        return_value=httpx.Response(200, json={"error": "boom"}),
    )
    async with HPOClient() as client:
        assert await client.children("HP:0001250") == []
