# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Full-coverage tests for ``alphafold_sovereign.clients.clinvar``."""

from __future__ import annotations

import httpx
import pytest
import respx

from alphafold_sovereign.clients.clinvar import (
    ClinVarClient,
    _parse_classification,
)
from alphafold_sovereign.domain.disease import PathogenicityClass


# ---------------------------------------------------------------------------
# _parse_classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Pathogenic", PathogenicityClass.PATHOGENIC),
        ("Likely pathogenic", PathogenicityClass.LIKELY_PATHOGENIC),
        ("Uncertain significance", PathogenicityClass.UNCERTAIN),
        ("Likely benign", PathogenicityClass.LIKELY_BENIGN),
        ("Benign", PathogenicityClass.BENIGN),
        (
            "Conflicting interpretations of pathogenicity",
            PathogenicityClass.CONFLICTING,
        ),
        (
            "Conflicting classifications of pathogenicity",
            PathogenicityClass.CONFLICTING,
        ),
        ("   PATHOGENIC   ", PathogenicityClass.PATHOGENIC),
        ("totally unknown", PathogenicityClass.NOT_PROVIDED),
    ],
)
def test_parse_classification_variants(raw: str, expected: PathogenicityClass) -> None:
    assert _parse_classification(raw) == expected


# ---------------------------------------------------------------------------
# Constructor: env var / explicit API key behaviour
# ---------------------------------------------------------------------------


def test_init_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NCBI_API_KEY", raising=False)
    client = ClinVarClient()
    assert client._api_key == ""
    # Default config retains 3 calls/sec.
    assert client.config.calls_per_second == 3.0


def test_init_with_explicit_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NCBI_API_KEY", raising=False)
    client = ClinVarClient(ncbi_api_key="abc")
    assert client._api_key == "abc"
    # With API key, rate raises to 10/s.
    assert client.config.calls_per_second == 10.0


def test_init_with_env_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NCBI_API_KEY", "env-key")
    client = ClinVarClient()
    assert client._api_key == "env-key"
    assert client.config.calls_per_second == 10.0


# ---------------------------------------------------------------------------
# search_by_hgvs
# ---------------------------------------------------------------------------


_SUMMARY_RESULT_OK = {
    "result": {
        "12345": {
            "uid": "12345",
            "title": "NM_007294.3(BRCA1):c.181T>G (p.Cys61Gly)",
            "gene_sort": "BRCA1;ENSG00000012048",
            "germline_classification": {
                "description": "Pathogenic",
                "review_status": "criteria provided",
                "last_evaluated": "2023-01-01",
            },
            "trait_set": [
                {"trait_name": "Hereditary breast and ovarian cancer"},
                {"trait_name": ""},  # filtered out
            ],
            "variation_set": [
                {
                    "variation_loc": [
                        {"molecular_consequence": "missense_variant"},
                        {"molecular_consequence": ""},  # filtered out
                        {"molecular_consequence": "missense_variant"},  # dedup
                    ]
                }
            ],
        }
    }
}


async def test_search_by_hgvs_returns_parsed_summary(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
    ).mock(
        return_value=httpx.Response(
            200,
            json={"esearchresult": {"idlist": ["12345"]}},
        ),
    )
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
    ).mock(return_value=httpx.Response(200, json=_SUMMARY_RESULT_OK))

    async with ClinVarClient() as client:
        result = await client.search_by_hgvs("NM_007294.3:c.181T>G")
    assert len(result) == 1
    row = result[0]
    assert row["variation_id"] == "12345"
    assert row["gene_symbol"] == "BRCA1"
    assert row["classification"] == PathogenicityClass.PATHOGENIC.value
    assert row["review_status"] == "criteria provided"
    assert row["conditions"] == ["Hereditary breast and ovarian cancer"]
    assert row["molecular_consequence"] == ["missense_variant"]
    assert row["last_evaluated"] == "2023-01-01"


async def test_search_by_hgvs_empty_idlist(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
    ).mock(
        return_value=httpx.Response(
            200,
            json={"esearchresult": {"idlist": []}},
        ),
    )
    async with ClinVarClient() as client:
        assert await client.search_by_hgvs("FOO:c.1A>T") == []


async def test_search_by_hgvs_with_api_key_passes_param(
    respx_mock: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NCBI_API_KEY", "secret")
    search_route = respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
    ).mock(
        return_value=httpx.Response(
            200, json={"esearchresult": {"idlist": ["77"]}}
        ),
    )
    summary_route = respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
    ).mock(
        return_value=httpx.Response(
            200,
            json={"result": {"77": {"uid": "77", "title": "x"}}},
        ),
    )
    async with ClinVarClient() as client:
        await client.search_by_hgvs("BRCA1:c.181T>G")
    assert "api_key=secret" in str(search_route.calls.last.request.url)
    assert "api_key=secret" in str(summary_route.calls.last.request.url)


# ---------------------------------------------------------------------------
# get_variant
# ---------------------------------------------------------------------------


async def test_get_variant_returns_first(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
    ).mock(return_value=httpx.Response(200, json=_SUMMARY_RESULT_OK))
    async with ClinVarClient() as client:
        v = await client.get_variant("12345")
    assert v["variation_id"] == "12345"


async def test_get_variant_raises_when_missing(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
    ).mock(return_value=httpx.Response(200, json={"result": {}}))
    async with ClinVarClient() as client:
        with pytest.raises(KeyError):
            await client.get_variant("999")


# ---------------------------------------------------------------------------
# search_gene
# ---------------------------------------------------------------------------


async def test_search_gene_filters_and_caps(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
    ).mock(
        return_value=httpx.Response(
            200,
            json={"esearchresult": {"idlist": ["12345", "67890"]}},
        ),
    )
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    "12345": {
                        "uid": "12345",
                        "title": "BRCA1 var 1",
                        "clinical_significance": {
                            "description": "Likely pathogenic",
                            "review_status": "reviewed",
                        },
                    },
                    "67890": {
                        "uid": "67890",
                        "title": "BRCA1 var 2",
                        "clinical_significance": {"description": "Pathogenic"},
                    },
                }
            },
        ),
    )
    async with ClinVarClient() as client:
        results = await client.search_gene("BRCA1", limit=2)
    assert len(results) == 2
    assert results[0]["classification"] == PathogenicityClass.LIKELY_PATHOGENIC.value


async def test_search_gene_empty(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
    ).mock(
        return_value=httpx.Response(
            200, json={"esearchresult": {"idlist": []}}
        ),
    )
    async with ClinVarClient() as client:
        assert await client.search_gene("UNKNOWNGENE") == []


async def test_search_gene_with_api_key(
    respx_mock: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NCBI_API_KEY", "k")
    search_route = respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
    ).mock(
        return_value=httpx.Response(
            200, json={"esearchresult": {"idlist": []}}
        ),
    )
    async with ClinVarClient() as client:
        assert await client.search_gene("BRCA1") == []
    assert "api_key=k" in str(search_route.calls.last.request.url)


# ---------------------------------------------------------------------------
# _parse_summary edge cases
# ---------------------------------------------------------------------------


async def test_parse_summary_missing_fields(respx_mock: respx.MockRouter) -> None:
    """A summary lacking germline_classification / trait_set still parses."""
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    "1": {
                        "uid": "1",
                        "title": "x",
                        "gene_sort": "",
                    }
                }
            },
        ),
    )
    async with ClinVarClient() as client:
        v = await client.get_variant("1")
    assert v["gene_symbol"] == ""
    assert v["classification"] == PathogenicityClass.NOT_PROVIDED.value
    assert v["conditions"] == []
    assert v["molecular_consequence"] == []
    assert v["review_status"] == ""
    assert v["last_evaluated"] == ""


async def test_parse_summary_skips_non_dict_payload(
    respx_mock: respx.MockRouter,
) -> None:
    """An ID present in `result` but whose value isn't a dict gets skipped."""
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
    ).mock(
        return_value=httpx.Response(
            200,
            json={"esearchresult": {"idlist": ["1", "2"]}},
        ),
    )
    respx_mock.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    "1": {"uid": "1", "title": "ok"},
                    "2": "not-a-dict",
                }
            },
        ),
    )
    async with ClinVarClient() as client:
        rows = await client.search_by_hgvs("BRCA1:c.1A>T")
    assert len(rows) == 1
    assert rows[0]["variation_id"] == "1"
