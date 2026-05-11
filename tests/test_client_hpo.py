# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Full-coverage tests for ``alphafold_sovereign.clients.hpo``.

Mocks the JAX HPO REST endpoints and exercises the various parsing
branches (term details nesting, synonym shape variations, etc.).
"""

from __future__ import annotations

import httpx
import respx

from alphafold_sovereign.clients.hpo import (
    DiseaseByPhenotype,
    HPOClient,
    _normalise_hpo_id,
)


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
        hpo_label="Seizure",
        frequency="HP:0040281",
        onset="HP:0003577",
        sex="Female",
    )
    assert d.to_dict()["disease_id"] == "OMIM:1"


# ---------------------------------------------------------------------------
# lookup
# ---------------------------------------------------------------------------


async def test_lookup_term_nested_details(respx_mock: respx.MockRouter) -> None:
    """When the payload nests under ``details``, prefer that branch."""
    respx_mock.get("https://hpo.jax.org/api/hpo/term/HP:0001250").mock(
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
    """If ``details`` lacks ``id``, fall back to the outer ``id`` field."""
    respx_mock.get("https://hpo.jax.org/api/hpo/term/HP:0009999").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "HP:0009999",
                # No "details" key → raw acts as the term
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
    respx_mock.get("https://hpo.jax.org/api/hpo/term/HP:0001000").mock(
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
    respx_mock.get("https://hpo.jax.org/api/hpo/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "terms": [
                    {"id": "HP:0003198", "name": "Myopathy"},
                ]
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
    respx_mock.get("https://hpo.jax.org/api/hpo/search").mock(
        return_value=httpx.Response(200, json={}),
    )
    async with HPOClient() as client:
        results = await client.search("nothing")
    assert results == []


# ---------------------------------------------------------------------------
# diseases_for_phenotype
# ---------------------------------------------------------------------------


async def test_diseases_for_phenotype_sorted(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://hpo.jax.org/api/hpo/term/HP:0001250/diseases").mock(
        return_value=httpx.Response(
            200,
            json={
                "diseaseAssoc": [
                    {
                        "diseaseId": "OMIM:2",
                        "diseaseName": "Zebra disease",
                        "ontologyTerm": {"name": "Seizure"},
                        "frequency": "Very frequent",
                        "onset": "Infantile",
                        "sex": "Female",
                    },
                    {
                        "diseaseId": "OMIM:1",
                        "diseaseName": "Alpha disease",
                        "ontologyTerm": {"name": "Seizure"},
                    },
                ]
            },
        ),
    )
    async with HPOClient() as client:
        results = await client.diseases_for_phenotype("HP:0001250", limit=10)
    names = [r.disease_name for r in results]
    assert names == ["Alpha disease", "Zebra disease"]


async def test_diseases_for_phenotype_empty(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://hpo.jax.org/api/hpo/term/HP:0001250/diseases").mock(
        return_value=httpx.Response(200, json={}),
    )
    async with HPOClient() as client:
        results = await client.diseases_for_phenotype("HP:0001250")
    assert results == []


# ---------------------------------------------------------------------------
# phenotypes_for_gene
# ---------------------------------------------------------------------------


async def test_phenotypes_for_gene(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://hpo.jax.org/api/hpo/gene").mock(
        return_value=httpx.Response(
            200,
            json={
                "termAssoc": [
                    {
                        "ontologyTerm": {"id": "HP:0001250", "name": "Seizure"},
                        "frequency": "Very frequent",
                        "onset": "Infantile",
                        "evidenceCodes": ["IEA"],
                        "references": ["PMID:12345"],
                    }
                ]
            },
        ),
    )
    async with HPOClient() as client:
        results = await client.phenotypes_for_gene("BRCA1", limit=5)
    assert results[0].hpo_id == "HP:0001250"
    assert results[0].evidence_codes == ("IEA",)


async def test_phenotypes_for_gene_none_termassoc(respx_mock: respx.MockRouter) -> None:
    """``termAssoc`` may be ``None`` ⇒ default empty list."""
    respx_mock.get("https://hpo.jax.org/api/hpo/gene").mock(
        return_value=httpx.Response(200, json={"termAssoc": None}),
    )
    async with HPOClient() as client:
        results = await client.phenotypes_for_gene("XYZ")
    assert results == []


# ---------------------------------------------------------------------------
# phenotypes_for_disease
# ---------------------------------------------------------------------------


async def test_phenotypes_for_disease_with_onset(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://hpo.jax.org/api/hpo/disease").mock(
        return_value=httpx.Response(
            200,
            json={
                "disease": {"diseaseName": "Test disease"},
                "catTermsMap": {
                    "Neurologic": {
                        "terms": [
                            {
                                "ontologyTerm": {"id": "HP:0001", "name": "Phen 1"},
                                "frequency": {"id": "HP:0040281"},
                                "onset": {"id": "HP:0003577"},
                                "evidence": [{"id": "IEA"}, {"id": "TAS"}],
                            },
                            {
                                "ontologyTerm": {"id": "HP:0002", "name": "Phen 2"},
                                "frequency": {"id": "HP:0040282"},
                                # No onset → fall through to "" branch
                                "evidence": None,  # exercise the `or []` fallback
                            },
                        ]
                    }
                },
            },
        ),
    )
    async with HPOClient() as client:
        results = await client.phenotypes_for_disease("OMIM:1")
    assert len(results) == 2
    assert results[0].onset == "HP:0003577"
    assert results[1].onset == ""
    assert results[0].evidence_codes == ("IEA", "TAS")


async def test_phenotypes_for_disease_inner_break(respx_mock: respx.MockRouter) -> None:
    """Hit the ``len(associations) >= limit`` break inside a category."""
    respx_mock.get("https://hpo.jax.org/api/hpo/disease").mock(
        return_value=httpx.Response(
            200,
            json={
                "catTermsMap": {
                    "A": {
                        "terms": [
                            {"ontologyTerm": {"id": "HP:1", "name": "A1"}},
                            {"ontologyTerm": {"id": "HP:2", "name": "A2"}},
                            {"ontologyTerm": {"id": "HP:3", "name": "A3"}},
                        ]
                    },
                    "B": {
                        "terms": [
                            {"ontologyTerm": {"id": "HP:4", "name": "B1"}},
                        ]
                    },
                },
            },
        ),
    )
    async with HPOClient() as client:
        results = await client.phenotypes_for_disease("OMIM:1", limit=2)
    assert len(results) == 2


# ---------------------------------------------------------------------------
# ancestors / children
# ---------------------------------------------------------------------------


async def test_ancestors(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://hpo.jax.org/api/hpo/term/HP:0001250/parents").mock(
        return_value=httpx.Response(
            200,
            json={"parents": [{"id": "HP:0000118", "name": "Phenotypic abnormality"}]},
        ),
    )
    async with HPOClient() as client:
        results = await client.ancestors("HP:0001250")
    assert results[0].label == "Phenotypic abnormality"


async def test_children(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://hpo.jax.org/api/hpo/term/HP:0001250/children").mock(
        return_value=httpx.Response(
            200,
            json={"children": [{"id": "HP:0011168", "name": "Aura"}]},
        ),
    )
    async with HPOClient() as client:
        results = await client.children("HP:0001250")
    assert results[0].id == "HP:0011168"
