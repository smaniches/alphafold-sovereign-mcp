# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Full-coverage tests for ``alphafold_sovereign.clients.disgenet``."""

from __future__ import annotations

import httpx
import pytest
import respx

from alphafold_sovereign.clients.disgenet import DisGeNETClient


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


def test_init_warns_when_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISGENET_API_KEY", raising=False)
    client = DisGeNETClient()
    assert client._api_key == ""


def test_init_explicit_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISGENET_API_KEY", raising=False)
    client = DisGeNETClient(api_key="abc")
    assert client._api_key == "abc"


def test_init_env_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISGENET_API_KEY", "envkey")
    client = DisGeNETClient()
    assert client._api_key == "envkey"


# ---------------------------------------------------------------------------
# gene_disease_associations
# ---------------------------------------------------------------------------


async def test_gda_dict_payload_with_filter(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://api.disgenet.com/api/v1/gda/gene").mock(
        return_value=httpx.Response(
            200,
            json={
                "payload": [
                    {
                        "gene_symbol": "BRCA1",
                        "disease_id": "C0001",
                        "disease_name": "Cancer",
                        "score": 0.95,
                        "n_pmids": 100,
                        "n_snps": 50,
                        "source": "CURATED",
                        "disease_class": ["C04"],
                        "disease_semantictype": ["Disease or Syndrome"],
                        "year_initial": 1990,
                        "year_final": 2024,
                    },
                    {
                        "gene_symbol": "BRCA1",
                        "disease_id": "C0002",
                        "disease_name": "Low score",
                        "score": 0.10,
                    },
                    "not-a-dict",
                ]
            },
        ),
    )
    async with DisGeNETClient(api_key="k") as client:
        rows = await client.gene_disease_associations("BRCA1", min_score=0.5, limit=10)
    assert len(rows) == 1
    assert rows[0]["disease_id"] == "C0001"
    assert rows[0]["score"] == 0.95
    assert rows[0]["year_initial"] == 1990


async def test_gda_list_shaped_response_handled(
    respx_mock: respx.MockRouter,
) -> None:
    """A top-level JSON list is treated as a payload list (no ``payload`` wrapper)."""
    respx_mock.get("https://api.disgenet.com/api/v1/gda/gene").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "gene_symbol": "TP53",
                    "disease_id": "C0003",
                    "disease_name": "Tumor",
                    "score": 0.7,
                }
            ],
        ),
    )
    async with DisGeNETClient(api_key="k") as client:
        results = await client.gene_disease_associations("TP53")
    assert len(results) == 1
    assert results[0]["gene_symbol"] == "TP53"
    assert results[0]["disease_id"] == "C0003"


async def test_gda_no_api_key(
    respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ``if self._api_key`` False branch."""
    monkeypatch.delenv("DISGENET_API_KEY", raising=False)
    route = respx_mock.get("https://api.disgenet.com/api/v1/gda/gene").mock(
        return_value=httpx.Response(200, json={"payload": []}),
    )
    async with DisGeNETClient() as client:
        await client.gene_disease_associations("BRCA1")
    assert "api_key" not in str(route.calls.last.request.url)


async def test_gda_handles_error_returns_empty(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("https://api.disgenet.com/api/v1/gda/gene").mock(
        return_value=httpx.Response(500),
    )
    async with DisGeNETClient(api_key="k") as client:
        rows = await client.gene_disease_associations("BRCA1")
    assert rows == []


async def test_gda_empty_payload(respx_mock: respx.MockRouter) -> None:
    """Empty dict (no 'payload', not a list) yields no results."""
    respx_mock.get("https://api.disgenet.com/api/v1/gda/gene").mock(
        return_value=httpx.Response(200, json={}),
    )
    async with DisGeNETClient(api_key="k") as client:
        rows = await client.gene_disease_associations("BRCA1")
    assert rows == []


# ---------------------------------------------------------------------------
# disease_gene_associations
# ---------------------------------------------------------------------------


async def test_disease_gene_associations(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://api.disgenet.com/api/v1/gda/disease").mock(
        return_value=httpx.Response(
            200,
            json={
                "payload": [
                    {
                        "gene_symbol": "BRCA1",
                        "gene_id": 672,
                        "disease_id": "C0001",
                        "disease_name": "Cancer",
                        "score": 0.8,
                        "n_pmids": 25,
                        "source": "CURATED",
                    },
                    {
                        "gene_symbol": "TP53",
                        "score": 0.05,  # filtered by min_score=0.1
                    },
                    None,  # skipped
                ]
            },
        ),
    )
    async with DisGeNETClient(api_key="k") as client:
        rows = await client.disease_gene_associations("C0001", limit=10)
    assert len(rows) == 1
    assert rows[0]["gene_symbol"] == "BRCA1"


async def test_disease_gene_associations_no_api_key(
    respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DISGENET_API_KEY", raising=False)
    route = respx_mock.get("https://api.disgenet.com/api/v1/gda/disease").mock(
        return_value=httpx.Response(200, json={"payload": []})
    )
    async with DisGeNETClient() as client:
        await client.disease_gene_associations("C1")
    assert "api_key" not in str(route.calls.last.request.url)


async def test_disease_gene_associations_error(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://api.disgenet.com/api/v1/gda/disease").mock(
        return_value=httpx.Response(500),
    )
    async with DisGeNETClient(api_key="k") as client:
        assert await client.disease_gene_associations("C1") == []


# ---------------------------------------------------------------------------
# variant_disease_associations
# ---------------------------------------------------------------------------


async def test_vda_payload(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://api.disgenet.com/api/v1/vda/variant").mock(
        return_value=httpx.Response(
            200,
            json={
                "payload": [
                    {
                        "variant_id": "rs1",
                        "disease_id": "C1",
                        "disease_name": "X",
                        "score": 0.6,
                        "n_pmids": 2,
                        "p_value": 0.001,
                        "odds_ratio": 1.5,
                        "beta": 0.3,
                        "source": "GWASCAT",
                    },
                    "skip-me",
                ]
            },
        ),
    )
    async with DisGeNETClient(api_key="k") as client:
        rows = await client.variant_disease_associations("rs1", limit=5)
    assert len(rows) == 1
    assert rows[0]["odds_ratio"] == 1.5


async def test_vda_no_api_key(
    respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DISGENET_API_KEY", raising=False)
    route = respx_mock.get("https://api.disgenet.com/api/v1/vda/variant").mock(
        return_value=httpx.Response(200, json={"payload": []})
    )
    async with DisGeNETClient() as client:
        await client.variant_disease_associations("rs1")
    assert "api_key" not in str(route.calls.last.request.url)


async def test_vda_error(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://api.disgenet.com/api/v1/vda/variant").mock(
        return_value=httpx.Response(500),
    )
    async with DisGeNETClient(api_key="k") as client:
        assert await client.variant_disease_associations("rs1") == []


# ---------------------------------------------------------------------------
# enrichment
# ---------------------------------------------------------------------------


async def test_enrichment_empty_inputs() -> None:
    async with DisGeNETClient(api_key="k") as client:
        assert await client.enrichment([]) == []


async def test_enrichment_with_p_filter(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://api.disgenet.com/api/v1/enrichment/gene").mock(
        return_value=httpx.Response(
            200,
            json={
                "payload": [
                    {
                        "disease_id": "C1",
                        "disease_name": "X",
                        "p_value": 0.001,
                        "fdr": 0.01,
                        "expected": 1.0,
                        "observed": 5,
                        "ratio": 5.0,
                    },
                    {
                        "disease_id": "C2",
                        "p_value": 0.5,  # above default 0.05 threshold
                    },
                    "skip",
                ]
            },
        ),
    )
    async with DisGeNETClient(api_key="k") as client:
        rows = await client.enrichment(["BRCA1", "TP53"], limit=5)
    assert len(rows) == 1
    assert rows[0]["disease_id"] == "C1"


async def test_enrichment_no_api_key(
    respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DISGENET_API_KEY", raising=False)
    route = respx_mock.get("https://api.disgenet.com/api/v1/enrichment/gene").mock(
        return_value=httpx.Response(200, json={"payload": []})
    )
    async with DisGeNETClient() as client:
        await client.enrichment(["BRCA1"])
    assert "api_key" not in str(route.calls.last.request.url)


async def test_enrichment_error(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://api.disgenet.com/api/v1/enrichment/gene").mock(
        return_value=httpx.Response(500),
    )
    async with DisGeNETClient(api_key="k") as client:
        assert await client.enrichment(["BRCA1"]) == []


async def test_enrichment_caps_at_100_inputs(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("https://api.disgenet.com/api/v1/enrichment/gene").mock(
        return_value=httpx.Response(200, json={"payload": []})
    )
    async with DisGeNETClient(api_key="k") as client:
        # Pass 150 genes — should be truncated to 100.
        await client.enrichment([f"G{i}" for i in range(150)])
    sent = str(route.calls.last.request.url)
    assert sent.count("G99") == 1
    assert "G100" not in sent  # truncated


# ---------------------------------------------------------------------------
# shared_genes
# ---------------------------------------------------------------------------


async def test_shared_genes_intersection(respx_mock: respx.MockRouter) -> None:
    responses = [
        httpx.Response(
            200,
            json={
                "payload": [
                    {"gene_symbol": "BRCA1", "score": 0.9, "disease_id": "C1"},
                    {"gene_symbol": "TP53", "score": 0.8, "disease_id": "C1"},
                    {"gene_symbol": "", "score": 0.5, "disease_id": "C1"},
                ]
            },
        ),
        httpx.Response(
            200,
            json={
                "payload": [
                    {"gene_symbol": "TP53", "score": 0.7, "disease_id": "C2"},
                    {"gene_symbol": "EGFR", "score": 0.7, "disease_id": "C2"},
                ]
            },
        ),
    ]
    respx_mock.get("https://api.disgenet.com/api/v1/gda/disease").mock(side_effect=responses)

    async with DisGeNETClient(api_key="k") as client:
        shared = await client.shared_genes("C1", "C2", min_score=0.1)
    assert shared == ["TP53"]
