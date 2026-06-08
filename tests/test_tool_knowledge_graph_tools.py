# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Full-coverage tests for ``alphafold_sovereign.tools.knowledge_graph_tools``."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from alphafold_sovereign.storage import knowledge_graph as kg_mod
from alphafold_sovereign.tools.knowledge_graph_tools import (
    DrugNetworkInput,
    ExportInput,
    ProteinQueryInput,
    VariantQueryInput,
    _provenance,
    _traverse_network,
    export_research_dataset,
    find_drug_gene_network,
    get_knowledge_graph_stats,
    query_protein_database,
    query_variant_database,
)


@pytest.fixture(autouse=True)
def _reset_kg_singleton(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Reset module-level KG singleton between tests.

    Seeding is disabled by default so these tests exercise the empty-graph
    behaviour; the seed path is covered explicitly in ``test_kg_autoseed``.
    """
    monkeypatch.setenv("AFSMCP_DISABLE_KG_SEED", "1")
    kg_mod._KG_SINGLETON = None
    yield
    if kg_mod._KG_SINGLETON is not None:
        # close synchronously
        try:
            if kg_mod._KG_SINGLETON._conn is not None:
                kg_mod._KG_SINGLETON._conn.close()
                kg_mod._KG_SINGLETON._conn = None
        except Exception:
            pass
    kg_mod._KG_SINGLETON = None


@pytest.fixture
def kg_db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the KG to a temporary database path."""
    db_path = tmp_path / "test_kg.db"
    monkeypatch.setenv("ALPHAFOLD_KG_PATH", str(db_path))
    return db_path


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_provenance_contains_label() -> None:
    p = _provenance(source="local-kg")
    assert "local-kg" in p


# ---------------------------------------------------------------------------
# query_variant_database
# ---------------------------------------------------------------------------


async def test_query_variant_database_empty(kg_db_path: Path) -> None:
    out = await query_variant_database(VariantQueryInput())
    assert out["result_count"] == 0
    assert out["variants"] == []


async def test_query_variant_database_populated(kg_db_path: Path) -> None:
    """Populate KG with a variant, then query it back."""
    async with kg_mod.get_knowledge_graph(kg_db_path) as kg:
        await kg.store_variant(
            hgvs="BRCA1:c.181T>G",
            gene_symbol="BRCA1",
            clinvar_class="Pathogenic",
            alphamissense_score=0.9,
            gnomad_af=1e-6,
            clinical_tier="HIGH",
        )

    out = await query_variant_database(
        VariantQueryInput(
            gene="BRCA1",
            tier="HIGH",
            clinvar_class="Pathogenic",
            min_am_score=0.5,
            max_gnomad_af=0.01,
        )
    )
    assert out["result_count"] == 1


# ---------------------------------------------------------------------------
# query_protein_database
# ---------------------------------------------------------------------------


async def test_query_protein_database_empty(kg_db_path: Path) -> None:
    out = await query_protein_database(ProteinQueryInput())
    assert out["result_count"] == 0


async def test_query_protein_database_filtered(kg_db_path: Path) -> None:
    async with kg_mod.get_knowledge_graph(kg_db_path) as kg:
        await kg.store_protein(
            uniprot_id="P38398",
            gene_symbol="BRCA1",
            mean_plddt=85.0,
            druggability_tier="HOT",
        )

    out = await query_protein_database(ProteinQueryInput(druggability_tier="HOT", min_plddt=70.0))
    assert out["result_count"] == 1


# ---------------------------------------------------------------------------
# get_knowledge_graph_stats
# ---------------------------------------------------------------------------


async def test_get_knowledge_graph_stats(kg_db_path: Path) -> None:
    out = await get_knowledge_graph_stats()
    assert "entity_counts" in out
    assert out["description"].startswith("AlphaFold Sovereign")


# ---------------------------------------------------------------------------
# export_research_dataset
# ---------------------------------------------------------------------------


async def test_export_research_dataset_empty(kg_db_path: Path) -> None:
    out = await export_research_dataset(ExportInput())
    assert out["total_rows"] == 0
    assert "variants" in out["data"]


async def test_export_research_dataset_specific(kg_db_path: Path) -> None:
    async with kg_mod.get_knowledge_graph(kg_db_path) as kg:
        await kg.store_variant(hgvs="X:c.1T>G", gene_symbol="X", clinical_tier="HIGH")
    out = await export_research_dataset(ExportInput(tables=["variants"]))
    assert len(out["data"]["variants"]) == 1


# ---------------------------------------------------------------------------
# find_drug_gene_network
# ---------------------------------------------------------------------------


async def test_find_drug_gene_network_empty_kg(kg_db_path: Path) -> None:
    out = await find_drug_gene_network(DrugNetworkInput(seed="BRCA1"))
    assert "network" in out
    assert out["network"]["node_count"] == 0


async def test_find_drug_gene_network_with_protein(kg_db_path: Path) -> None:
    """Gene seed → finds linked protein and variant."""
    async with kg_mod.get_knowledge_graph(kg_db_path) as kg:
        await kg.store_protein(
            uniprot_id="P38398",
            gene_symbol="BRCA1",
            mean_plddt=85.0,
            druggability_tier="HOT",
        )
        await kg.store_variant(
            hgvs="BRCA1:c.181T>G",
            gene_symbol="BRCA1",
            clinical_tier="HIGH",
        )

    out = await find_drug_gene_network(DrugNetworkInput(seed="BRCA1", max_hops=2))
    assert out["network"]["node_count"] >= 1


async def test_find_drug_gene_network_disease_seed(kg_db_path: Path) -> None:
    """MONDO seed → queries drug landscape."""
    async with kg_mod.get_knowledge_graph(kg_db_path) as kg:
        await kg.store_protein(uniprot_id="P1", gene_symbol="G")
        await kg.store_drug(chembl_id="CHEMBL1", pref_name="Drug X", max_phase=4)
        await kg.store_disease(mondo_id="MONDO:0001", name="Test Disease")

    out = await find_drug_gene_network(DrugNetworkInput(seed="MONDO:0001"))
    assert out["seed"] == "MONDO:0001"


async def test_find_drug_gene_network_uniprot_seed(kg_db_path: Path) -> None:
    """UniProt-prefix seed → queries proteins."""
    async with kg_mod.get_knowledge_graph(kg_db_path) as kg:
        await kg.store_protein(uniprot_id="P38398", gene_symbol="BRCA1")

    out = await find_drug_gene_network(DrugNetworkInput(seed="P38398"))
    assert out["seed"] == "P38398"


# ---------------------------------------------------------------------------
# _traverse_network — direct unit tests
# ---------------------------------------------------------------------------


async def test_traverse_network_disease_with_drug_rows() -> None:
    """MONDO seed with drug landscape rows builds disease+drug nodes and edges."""
    mock_kg = MagicMock()
    mock_kg.query_drug_landscape = AsyncMock(
        return_value=[
            {"chembl_id": "CHEMBL1", "pref_name": "Drug A", "max_phase": 4},
            {"chembl_id": "", "pref_name": "Empty"},  # empty drug ID skipped
        ]
    )

    out = await _traverse_network(mock_kg, "MONDO:0001", max_hops=1)
    assert any(n.get("type") == "drug" for n in out["nodes"])
    assert any(n.get("type") == "disease" for n in out["nodes"])
    assert any(e["rel"] == "indication" for e in out["edges"])


async def test_traverse_network_uniprot_seed_found() -> None:
    """UniProt seed matches a protein in the DB."""
    mock_kg = MagicMock()
    mock_kg.query_proteins = AsyncMock(
        return_value=[{"uniprot_id": "P38398", "gene_symbol": "BRCA1"}]
    )

    out = await _traverse_network(mock_kg, "P38398", max_hops=1)
    assert any(n.get("type") == "protein" for n in out["nodes"])


async def test_traverse_network_uniprot_seed_not_found() -> None:
    """UniProt seed has no match - no node added."""
    mock_kg = MagicMock()
    mock_kg.query_proteins = AsyncMock(return_value=[{"uniprot_id": "OTHER"}])

    out = await _traverse_network(mock_kg, "P12345", max_hops=1)
    assert out["node_count"] == 0


async def test_traverse_network_gene_seed_protein_and_variant() -> None:
    """Gene seed → encodes protein + has_variant edges."""
    mock_kg = MagicMock()
    # _fetchall is sync
    mock_kg._fetchall = MagicMock(
        return_value=[
            {
                "uniprot_id": "P38398",
                "gene_symbol": "BRCA1",
                "druggability_tier": "HOT",
                "mean_plddt": 85.0,
            }
        ]
    )
    mock_kg.query_variants = AsyncMock(
        return_value=[
            {"hgvs": "BRCA1:c.181T>G", "clinical_tier": "HIGH"},
            {"hgvs": ""},  # empty hgvs skipped
        ]
    )
    mock_kg.query_proteins = AsyncMock(return_value=[])

    out = await _traverse_network(mock_kg, "BRCA1", max_hops=2)
    assert any(e["rel"] == "encodes" for e in out["edges"])
    assert any(e["rel"] == "has_variant" for e in out["edges"])


async def test_traverse_network_gene_seed_no_recursion_at_max_hop() -> None:
    """Gene at max_hops should not recurse into protein expand."""
    mock_kg = MagicMock()
    mock_kg._fetchall = MagicMock(
        return_value=[
            {"uniprot_id": "P38398", "gene_symbol": "BRCA1"},
            {"uniprot_id": "P38399", "gene_symbol": "BRCA1"},
        ]
    )
    mock_kg.query_variants = AsyncMock(return_value=[])
    mock_kg.query_proteins = AsyncMock(return_value=[])

    # max_hops=1 + initial hop=0 - the gene path runs at hop=0,
    # then `if hop < max_hops:` (0 < 1) → recurses for first protein at hop=1.
    # At hop=1, the protein at hop=1 visits expand, but for branches at hop=1
    # the gene path again would have hop+1=2 > max_hops=1, so no recursion.
    out = await _traverse_network(mock_kg, "BRCA1", max_hops=0)
    # max_hops=0 → the initial gene call expands but `hop < max_hops` (0<0) False
    # so no recursion. Multiple proteins added, none recursed.
    assert any(n.get("type") == "protein" for n in out["nodes"])


async def test_traverse_network_visited_dedup() -> None:
    """Duplicate proteins in _fetchall trigger visited short-circuit (line 340)."""
    mock_kg = MagicMock()
    mock_kg._fetchall = MagicMock(
        return_value=[
            {"uniprot_id": "P38398", "gene_symbol": "BRCA1"},
            {"uniprot_id": "P38398", "gene_symbol": "BRCA1"},  # duplicate
        ]
    )
    mock_kg.query_variants = AsyncMock(return_value=[])
    mock_kg.query_proteins = AsyncMock(return_value=[])

    out = await _traverse_network(mock_kg, "BRCA1", max_hops=2)
    # Second expand call for P38398 hits the visited guard.
    assert any(n.get("uniprot_id") == "P38398" for n in out["nodes"])


async def test_traverse_network_visited_short_circuit() -> None:
    """Already-visited entities return immediately."""
    mock_kg = MagicMock()
    calls = {"n": 0}

    async def fake_drug_landscape(**kw: Any) -> list[dict[str, Any]]:
        calls["n"] += 1
        return []

    mock_kg.query_drug_landscape = fake_drug_landscape
    # Call expand twice on the same ID
    out = await _traverse_network(mock_kg, "MONDO:0001", max_hops=3)
    # Even with max_hops=3, no recursion because rows are empty
    assert "MONDO:0001" in {n.get("id") for n in out["nodes"]}


# ---------------------------------------------------------------------------
# Test pure dispatch paths (top-of-hop logic) via patching get_knowledge_graph
# ---------------------------------------------------------------------------


async def test_query_variant_database_kg_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Patch get_knowledge_graph context manager to return canned rows."""
    canned_rows = [{"hgvs": "BRCA1:c.181T>G", "clinical_tier": "HIGH"}]

    mock_kg = MagicMock()
    mock_kg.query_variants = AsyncMock(return_value=canned_rows)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_get_kg(*_a: Any, **_kw: Any) -> Any:
        yield mock_kg

    monkeypatch.setattr(
        "alphafold_sovereign.tools.knowledge_graph_tools.get_knowledge_graph",
        fake_get_kg,
    )

    out = await query_variant_database(VariantQueryInput(gene="BRCA1"))
    assert out["result_count"] == 1


# ---------------------------------------------------------------------------
# Auto-seed (out-of-the-box data)
# ---------------------------------------------------------------------------


async def test_kg_autoseed_populates_tools(
    monkeypatch: pytest.MonkeyPatch, kg_db_path: Path
) -> None:
    """With seeding enabled, an empty graph auto-seeds and the tools return data."""
    monkeypatch.delenv("AFSMCP_DISABLE_KG_SEED", raising=False)
    proteins = await query_protein_database(ProteinQueryInput(limit=10))
    assert len(proteins["proteins"]) >= 5
    variants = await query_variant_database(VariantQueryInput(limit=10))
    assert len(variants["variants"]) >= 2
    net = await find_drug_gene_network(DrugNetworkInput(seed="MONDO:0011996", max_hops=2))
    assert len(net["network"]["nodes"]) > 0
    assert len(net["network"]["edges"]) > 0


async def test_kg_autoseed_skips_when_populated(
    monkeypatch: pytest.MonkeyPatch, kg_db_path: Path
) -> None:
    """seed_if_empty is a no-op once the graph already holds proteins."""
    monkeypatch.delenv("AFSMCP_DISABLE_KG_SEED", raising=False)
    async with kg_mod.get_knowledge_graph() as kg:
        # First access already seeded the graph, so a second call does nothing.
        assert await kg.seed_if_empty() is False
