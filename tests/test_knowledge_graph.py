# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Unit tests for the local knowledge graph (SQLite provenance store)."""
from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

import pytest

from alphafold_sovereign.storage.knowledge_graph import KnowledgeGraph


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
async def akg(tmp_path: Path) -> AsyncIterator[KnowledgeGraph]:
    """Connected KnowledgeGraph backed by a temp file."""
    db = KnowledgeGraph(db_path=tmp_path / "test.db")
    await db.connect()
    yield db
    await db.close()


# ── Schema & connection ────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_connect_creates_tables(tmp_path: Path) -> None:
    """connect() must create all entity tables without error."""
    db = KnowledgeGraph(db_path=tmp_path / "kg.db")
    await db.connect()
    stats = await db.get_statistics()
    assert "entity_counts" in stats
    assert "proteins" in stats["entity_counts"]
    assert "variants" in stats["entity_counts"]
    await db.close()


@pytest.mark.unit
async def test_connect_idempotent(tmp_path: Path) -> None:
    """Calling connect() twice must not raise."""
    db = KnowledgeGraph(db_path=tmp_path / "kg2.db")
    await db.connect()
    await db.connect()
    await db.close()


# ── store_protein ──────────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_store_protein_round_trip(akg: KnowledgeGraph) -> None:
    uid = await akg.store_protein(
        uniprot_id="P04637",
        gene_symbol="TP53",
        protein_name="Cellular tumor antigen p53",
        mean_plddt=72.4,
        druggability_tier="WARM",
    )
    assert uid == "P04637"

    rows = await akg.query_proteins(druggability_tier="WARM")
    uniprot_ids = [r["uniprot_id"] for r in rows]
    assert "P04637" in uniprot_ids


@pytest.mark.unit
async def test_store_protein_upsert(akg: KnowledgeGraph) -> None:
    """Second store_protein call should update, not duplicate."""
    await akg.store_protein(uniprot_id="P12345", gene_symbol="BRCA1")
    await akg.store_protein(
        uniprot_id="P12345", gene_symbol="BRCA1", mean_plddt=80.0
    )
    rows = await akg.query_proteins(min_plddt=79.0)
    assert any(r["uniprot_id"] == "P12345" for r in rows)


# ── store_variant ──────────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_store_variant_basic(akg: KnowledgeGraph) -> None:
    hgvs = await akg.store_variant(
        hgvs="BRCA1:c.181T>G",
        gene_symbol="BRCA1",
        clinvar_class="Pathogenic",
        gnomad_af=0.0001,
        alphamissense_score=0.72,
        clinical_tier="TIER_1_PATHOGENIC",
    )
    assert hgvs == "BRCA1:c.181T>G"

    rows = await akg.query_variants(gene="BRCA1")
    assert len(rows) == 1
    assert rows[0]["clinical_tier"] == "TIER_1_PATHOGENIC"


@pytest.mark.unit
async def test_query_variants_by_tier(akg: KnowledgeGraph) -> None:
    await akg.store_variant(hgvs="VAR:1", gene_symbol="TP53", clinical_tier="HIGH")
    await akg.store_variant(hgvs="VAR:2", gene_symbol="EGFR", clinical_tier="LOW")

    high = await akg.query_variants(tier="HIGH")
    hgvs_list = [r["hgvs"] for r in high]
    assert "VAR:1" in hgvs_list
    assert all(r["clinical_tier"] == "HIGH" for r in high)


# ── store_disease / store_drug ─────────────────────────────────────────────────


@pytest.mark.unit
async def test_store_disease(akg: KnowledgeGraph) -> None:
    mid = await akg.store_disease(
        mondo_id="MONDO:0007254",
        name="breast carcinoma",
        definition="Malignant tumor of the breast.",
    )
    assert mid == "MONDO:0007254"
    stats = await akg.get_statistics()
    assert stats["entity_counts"]["diseases"] >= 1


@pytest.mark.unit
async def test_store_drug(akg: KnowledgeGraph) -> None:
    cid = await akg.store_drug(
        chembl_id="CHEMBL1201585",
        pref_name="OLAPARIB",
        max_phase=4,
        max_phase_label="Approved",
    )
    assert cid == "CHEMBL1201585"
    stats = await akg.get_statistics()
    assert stats["entity_counts"]["drugs"] >= 1


# ── audit trail ───────────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_log_tool_invocation(akg: KnowledgeGraph) -> None:
    row_id = await akg.log_tool_invocation(
        tool_name="test_tool",
        params={"uniprot_id": "P04637"},
        result={"status": "ok"},
        duration_ms=123,
    )
    assert isinstance(row_id, int)
    assert row_id > 0


@pytest.mark.unit
async def test_tool_invocation_counted(akg: KnowledgeGraph) -> None:
    await akg.log_tool_invocation(
        tool_name="get_structure",
        params={"uid": "P04637"},
        duration_ms=50,
    )
    stats = await akg.get_statistics()
    assert stats["entity_counts"]["tool_invocations"] >= 1


# ── export_to_dict ─────────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_export_to_dict(akg: KnowledgeGraph) -> None:
    await akg.store_protein(uniprot_id="Q99999", gene_symbol="TESTGENE")
    export = await akg.export_to_dict()
    assert "proteins" in export
    assert any(p["uniprot_id"] == "Q99999" for p in export["proteins"])


# ── datetime timezone ─────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_timestamps_are_tz_aware(akg: KnowledgeGraph) -> None:
    """Stored timestamps must contain timezone offset (not naive UTC)."""
    await akg.store_protein(uniprot_id="P99999", gene_symbol="TZ_CHECK")
    export = await akg.export_to_dict(tables=["proteins"])
    proteins = export.get("proteins", [])
    assert proteins
    ts_str: str = proteins[0].get("updated_at", "")
    # Timezone-aware ISO strings contain '+00:00' from datetime.timezone.utc
    assert "+00:00" in ts_str or ts_str.endswith("Z")
