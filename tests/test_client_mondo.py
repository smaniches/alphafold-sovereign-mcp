# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Full-coverage tests for ``alphafold_sovereign.clients.mondo``.

Mocks OLS4 and Monarch endpoints. Exercises both list-of-string and
list-of-dict synonym shapes, plus every cross-reference regex branch.
"""

from __future__ import annotations

from urllib.parse import quote

import httpx
import pytest
import respx

from alphafold_sovereign.clients.mondo import (
    MONDOClient,
    MONDOSearchResult,
    _extract_xrefs,
    _normalise_mondo_id,
    _url_encode,
)

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_normalise_mondo_id_bare_digits() -> None:
    assert _normalise_mondo_id("0004995") == "MONDO:0004995"


def test_normalise_mondo_id_underscore() -> None:
    assert _normalise_mondo_id("mondo_0004995") == "MONDO:0004995"


def test_normalise_mondo_id_already_curie() -> None:
    assert _normalise_mondo_id("MONDO:0004995") == "MONDO:0004995"


def test_extract_xrefs_all_buckets() -> None:
    """Each regex branch must match at least once."""
    buckets = _extract_xrefs(
        [
            "ICD10:G40.0",
            "ICD10CM:G40.0",
            "ICD11:abc123",
            "OMIM:114480",
            "Orphanet:524",
            "MeSH:D001943",
            "DOID:1909",
            "EFO:0000339",
            "BOGUS:should-not-match",
        ]
    )
    assert buckets["icd10"] == ["G40.0", "G40.0"]
    assert buckets["icd11"] == ["abc123"]
    assert buckets["omim"] == ["114480"]
    assert buckets["orphanet"] == ["524"]
    assert buckets["mesh"] == ["D001943"]
    assert buckets["doid"] == ["1909"]
    # EFO is stored as the full CURIE (the native key for OT / ChEMBL).
    assert buckets["efo"] == ["EFO:0000339"]


def test_url_encode_double_quoted() -> None:
    s = "http://purl.obolibrary.org/obo/MONDO_0004995"
    expected = quote(quote(s, safe=""), safe="")
    assert _url_encode(s) == expected


def test_search_result_to_dict_rounds_score() -> None:
    r = MONDOSearchResult(
        mondo_id="MONDO:0004995",
        label="cancer",
        description="",
        synonyms=[],
        score=0.123456789,
    )
    assert r.to_dict()["score"] == 0.1235


# ---------------------------------------------------------------------------
# lookup
# ---------------------------------------------------------------------------


async def test_lookup_returns_disease_record_synonyms_strings(
    respx_mock: respx.MockRouter,
) -> None:
    """Synonyms returned as plain strings should pass through unchanged."""
    respx_mock.get("https://www.ebi.ac.uk/ols4/api/ontologies/mondo/terms").mock(
        return_value=httpx.Response(
            200,
            json={
                "_embedded": {
                    "terms": [
                        {
                            "short_form": "MONDO_0004995",
                            "label": "cardiomyopathy",
                            "description": ["A disease of the heart."],
                            "synonyms": ["CMP", "heart muscle disease"],
                            "annotation": {
                                "database_cross_reference": [
                                    "ICD10:I42.0",
                                    "OMIM:115200",
                                ]
                            },
                        }
                    ]
                }
            },
        ),
    )
    async with MONDOClient() as client:
        record = await client.lookup("MONDO:0004995")
    assert record.name == "cardiomyopathy"
    assert "CMP" in record.synonyms
    assert "I42.0" in record.icd10_codes


async def test_lookup_returns_disease_record_synonyms_dicts(
    respx_mock: respx.MockRouter,
) -> None:
    """Synonyms returned as ``{val: ...}`` dicts must be extracted.

    Also covers the non-str / non-dict synonym branch (loop continues).
    """
    respx_mock.get("https://www.ebi.ac.uk/ols4/api/ontologies/mondo/terms").mock(
        return_value=httpx.Response(
            200,
            json={
                "_embedded": {
                    "terms": [
                        {
                            "short_form": "MONDO_0004995",
                            "label": "X",
                            "description": "string-form description",
                            "synonyms": [
                                {"val": "Alt One"},
                                {"val": ""},  # filtered by `if s`
                                "Plain string",
                                None,  # neither str nor dict → loop continues
                            ],
                        }
                    ]
                }
            },
        ),
    )
    async with MONDOClient() as client:
        record = await client.lookup("MONDO:0004995")
    assert "Alt One" in record.synonyms
    assert "Plain string" in record.synonyms
    assert "" not in record.synonyms
    # description as a string falls through to `str(description)`
    assert record.definition == "string-form description"


async def test_lookup_not_found_raises_key_error(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://www.ebi.ac.uk/ols4/api/ontologies/mondo/terms").mock(
        return_value=httpx.Response(200, json={"_embedded": {"terms": []}}),
    )
    async with MONDOClient() as client:
        with pytest.raises(KeyError):
            await client.lookup("MONDO:9999999")


async def test_lookup_no_description_key(respx_mock: respx.MockRouter) -> None:
    """Missing description ⇒ ``[]`` falls into the ``str(description)`` branch."""
    respx_mock.get("https://www.ebi.ac.uk/ols4/api/ontologies/mondo/terms").mock(
        return_value=httpx.Response(
            200,
            json={
                "_embedded": {
                    "terms": [
                        {
                            "short_form": "MONDO_0004995",
                            "label": "Z",
                            "synonyms": None,  # exercise `or []`
                        }
                    ]
                }
            },
        ),
    )
    async with MONDOClient() as client:
        record = await client.lookup("MONDO:0004995")
    # Implementation falls back to str([]) when description is missing.
    assert record.definition == "[]"


# ---------------------------------------------------------------------------
# lookup_term
# ---------------------------------------------------------------------------


async def test_lookup_term_wraps_record(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://www.ebi.ac.uk/ols4/api/ontologies/mondo/terms").mock(
        return_value=httpx.Response(
            200,
            json={
                "_embedded": {
                    "terms": [
                        {
                            "short_form": "MONDO_0004995",
                            "label": "L",
                            "description": ["d"],
                            "synonyms": ["s"],
                            "annotation": {
                                "database_cross_reference": [
                                    "OMIM:1",
                                    "ICD10:A00",
                                    "Orphanet:2",
                                ]
                            },
                        }
                    ]
                }
            },
        ),
    )
    async with MONDOClient() as client:
        term = await client.lookup_term("MONDO:0004995")
    assert term.id == "MONDO:0004995"
    assert "OMIM:1" not in term.xrefs  # only stored codes, not full curies
    assert "A00" in term.xrefs


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


async def test_search_filters_non_mondo_and_parses_score(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://www.ebi.ac.uk/ols4/api/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "response": {
                    "docs": [
                        {
                            "short_form": "MONDO_0004995",
                            "label": "Cancer",
                            "description": ["d"],
                            "synonym": ["s"],
                            "score": "1.2",
                        },
                        # Skipped: non-MONDO short_form
                        {"short_form": "EFO_001", "label": "X", "score": 0.5},
                        # Skipped: empty short_form
                        {"label": "blank"},
                    ]
                }
            },
        ),
    )
    async with MONDOClient() as client:
        results = await client.search("breast", limit=999, obsolete=True)
    assert len(results) == 1
    assert results[0].label == "Cancer"


async def test_search_handles_missing_description(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://www.ebi.ac.uk/ols4/api/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "response": {
                    "docs": [
                        {
                            "short_form": "MONDO_001",
                            "label": "L",
                            # No description key → `(None or [""])[0]` = ""
                        }
                    ]
                }
            },
        ),
    )
    async with MONDOClient() as client:
        results = await client.search("foo", limit=0)
    assert results[0].description == ""


async def test_search_empty_response(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://www.ebi.ac.uk/ols4/api/search").mock(
        return_value=httpx.Response(200, json={}),
    )
    async with MONDOClient() as client:
        assert await client.search("nothing") == []


# ---------------------------------------------------------------------------
# Hierarchy
# ---------------------------------------------------------------------------


def _encoded_iri(short_form: str) -> str:
    return _url_encode(f"http://purl.obolibrary.org/obo/{short_form}")


async def test_ancestors(respx_mock: respx.MockRouter) -> None:
    iri = _encoded_iri("MONDO_0004995")
    respx_mock.get(f"https://www.ebi.ac.uk/ols4/api/ontologies/mondo/terms/{iri}/ancestors").mock(
        return_value=httpx.Response(
            200,
            json={
                "_embedded": {
                    "terms": [
                        {
                            "short_form": "MONDO_0000001",
                            "label": "disease",
                            "description": ["root"],
                            "synonyms": ["illness"],
                            "is_obsolete": False,
                        }
                    ]
                }
            },
        ),
    )
    async with MONDOClient() as client:
        results = await client.ancestors("MONDO:0004995")
    assert results[0].id == "MONDO:0000001"
    assert results[0].description == "root"


async def test_descendants_handles_non_list_description(
    respx_mock: respx.MockRouter,
) -> None:
    iri = _encoded_iri("MONDO_0004995")
    respx_mock.get(f"https://www.ebi.ac.uk/ols4/api/ontologies/mondo/terms/{iri}/descendants").mock(
        return_value=httpx.Response(
            200,
            json={
                "_embedded": {
                    "terms": [
                        {
                            "short_form": "MONDO_0123456",
                            "label": "child",
                            "description": None,
                            "synonyms": None,
                        }
                    ]
                }
            },
        ),
    )
    async with MONDOClient() as client:
        results = await client.descendants("MONDO:0004995")
    assert results[0].description == ""


async def test_children(respx_mock: respx.MockRouter) -> None:
    iri = _encoded_iri("MONDO_0004995")
    respx_mock.get(f"https://www.ebi.ac.uk/ols4/api/ontologies/mondo/terms/{iri}/children").mock(
        return_value=httpx.Response(
            200,
            json={"_embedded": {"terms": []}},
        ),
    )
    async with MONDOClient() as client:
        results = await client.children("MONDO:0004995")
    assert results == []


# ---------------------------------------------------------------------------
# Cross-ref lookups (thin wrappers around search)
# ---------------------------------------------------------------------------


async def test_from_icd10(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://www.ebi.ac.uk/ols4/api/search").mock(
        return_value=httpx.Response(200, json={}),
    )
    async with MONDOClient() as client:
        assert await client.from_icd10("G40") == []


async def test_from_omim(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://www.ebi.ac.uk/ols4/api/search").mock(
        return_value=httpx.Response(200, json={}),
    )
    async with MONDOClient() as client:
        assert await client.from_omim("114480") == []


async def test_from_orphanet(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://www.ebi.ac.uk/ols4/api/search").mock(
        return_value=httpx.Response(200, json={}),
    )
    async with MONDOClient() as client:
        assert await client.from_orphanet("524") == []
