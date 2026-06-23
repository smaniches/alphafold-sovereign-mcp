# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Unit tests for the local knowledge graph (SQLite provenance store)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from alphafold_sovereign.storage import knowledge_graph as kg_module
from alphafold_sovereign.storage.knowledge_graph import (
    KnowledgeGraph,
    _default_db_path,
    get_knowledge_graph,
)

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


@pytest.mark.unit
async def test_open_db_sets_busy_timeout(tmp_path: Path) -> None:
    """_open_db must set a non-zero busy_timeout so a concurrent writer waits
    for a contended lock instead of failing immediately with 'database is locked'."""
    db = KnowledgeGraph(db_path=tmp_path / "busy.db")
    await db.connect()
    try:
        assert db._conn is not None
        (timeout,) = db._conn.execute("PRAGMA busy_timeout").fetchone()
        assert timeout == 5000
    finally:
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
    await akg.store_protein(uniprot_id="P12345", gene_symbol="BRCA1", mean_plddt=80.0)
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


# ── _default_db_path env override ──────────────────────────────────────────────


@pytest.mark.unit
def test_default_db_path_falls_back_to_platformdirs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no env override, _default_db_path returns the platformdirs default."""
    monkeypatch.delenv("ALPHAFOLD_KG_PATH", raising=False)
    p = _default_db_path()
    # Same singleton constant returned when unset
    assert p == kg_module._DEFAULT_DB_PATH


@pytest.mark.unit
def test_default_db_path_honours_env_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ALPHAFOLD_KG_PATH must override the platformdirs default."""
    custom = tmp_path / "custom_kg.db"
    monkeypatch.setenv("ALPHAFOLD_KG_PATH", str(custom))
    assert _default_db_path() == Path(str(custom))


# ── async-context-manager lifecycle ────────────────────────────────────────────


@pytest.mark.unit
async def test_async_context_manager(tmp_path: Path) -> None:
    """`async with KnowledgeGraph(...)` must connect on entry and close on exit."""
    async with KnowledgeGraph(db_path=tmp_path / "ctx.db") as db:
        assert db._conn is not None
        stats = await db.get_statistics()
        assert "entity_counts" in stats
    # Exit must have closed the connection
    assert db._conn is None


@pytest.mark.unit
async def test_close_without_connection_is_noop(tmp_path: Path) -> None:
    """Closing a never-connected KnowledgeGraph must be a safe no-op (133->exit)."""
    db = KnowledgeGraph(db_path=tmp_path / "no_connect.db")
    # No connect() — _conn is still None
    await db.close()
    assert db._conn is None


# ── query_variants additional filter branches ─────────────────────────────────


@pytest.mark.unit
async def test_query_variants_by_min_am_score(akg: KnowledgeGraph) -> None:
    """min_am_score filter must exclude rows below the threshold."""
    await akg.store_variant(
        hgvs="AM:LOW",
        gene_symbol="GENE1",
        alphamissense_score=0.2,
        clinical_tier="LOW",
    )
    await akg.store_variant(
        hgvs="AM:HIGH",
        gene_symbol="GENE1",
        alphamissense_score=0.9,
        clinical_tier="HIGH",
    )
    rows = await akg.query_variants(min_am_score=0.5)
    hgvs_list = [r["hgvs"] for r in rows]
    assert "AM:HIGH" in hgvs_list
    assert "AM:LOW" not in hgvs_list


@pytest.mark.unit
async def test_query_variants_by_max_gnomad_af(akg: KnowledgeGraph) -> None:
    """max_gnomad_af must include rows where AF <= threshold (and NULLs)."""
    await akg.store_variant(
        hgvs="AF:RARE",
        gene_symbol="GENE2",
        gnomad_af=1e-5,
        clinical_tier="HIGH",
    )
    await akg.store_variant(
        hgvs="AF:COMMON",
        gene_symbol="GENE2",
        gnomad_af=0.1,
        clinical_tier="LOW",
    )
    rows = await akg.query_variants(max_gnomad_af=0.001)
    hgvs_list = [r["hgvs"] for r in rows]
    assert "AF:RARE" in hgvs_list
    assert "AF:COMMON" not in hgvs_list


@pytest.mark.unit
async def test_query_variants_by_clinvar_class(akg: KnowledgeGraph) -> None:
    """clinvar_class filter must restrict to rows matching the literal class."""
    await akg.store_variant(
        hgvs="CV:P",
        gene_symbol="GENEX",
        clinvar_class="Pathogenic",
        clinical_tier="HIGH",
    )
    await akg.store_variant(
        hgvs="CV:B",
        gene_symbol="GENEX",
        clinvar_class="Benign",
        clinical_tier="LOW",
    )
    rows = await akg.query_variants(clinvar_class="Pathogenic")
    hgvs_list = [r["hgvs"] for r in rows]
    assert "CV:P" in hgvs_list
    assert "CV:B" not in hgvs_list


# ── query_drug_landscape branches ─────────────────────────────────────────────


@pytest.mark.unit
async def test_query_drug_landscape_min_phase_only(akg: KnowledgeGraph) -> None:
    """min_phase filter on its own returns approved drugs across diseases."""
    # Seed: protein, disease, drug, and edges linking them
    await akg.store_protein(uniprot_id="P38398", gene_symbol="BRCA1")
    await akg.store_drug(
        chembl_id="CHEMBL1201585",
        pref_name="OLAPARIB",
        max_phase=4,
        max_phase_label="Approved",
    )
    await akg.store_disease(mondo_id="MONDO:0007254", name="breast carcinoma")

    # Edges: protein↔drug and protein↔disease so drug_landscape view joins
    import datetime as _dt

    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    assert akg._conn is not None
    akg._conn.execute(
        "INSERT INTO protein_drug (uniprot_id, chembl_id, target_chembl_id, "
        "activity_type, created_at) VALUES (?,?,?,?,?)",
        ["P38398", "CHEMBL1201585", "CHEMBL_T1", "IC50", now],
    )
    akg._conn.execute(
        "INSERT INTO protein_disease (uniprot_id, mondo_id, source, created_at) VALUES (?,?,?,?)",
        ["P38398", "MONDO:0007254", "opentargets", now],
    )
    akg._conn.commit()

    rows = await akg.query_drug_landscape(min_phase=4)
    chembl_ids = [r["chembl_id"] for r in rows]
    assert "CHEMBL1201585" in chembl_ids


@pytest.mark.unit
async def test_query_drug_landscape_with_mondo_filter(akg: KnowledgeGraph) -> None:
    """mondo_id filter restricts results to drugs linked to the disease."""
    # Seed an approved drug + protein + two diseases
    await akg.store_protein(uniprot_id="P38398", gene_symbol="BRCA1")
    await akg.store_drug(
        chembl_id="CHEMBL1201585",
        pref_name="OLAPARIB",
        max_phase=4,
    )
    await akg.store_disease(mondo_id="MONDO:0007254", name="breast carcinoma")
    await akg.store_disease(mondo_id="MONDO:0008170", name="ovarian carcinoma")

    import datetime as _dt

    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    assert akg._conn is not None
    akg._conn.execute(
        "INSERT INTO protein_drug (uniprot_id, chembl_id, target_chembl_id, "
        "activity_type, created_at) VALUES (?,?,?,?,?)",
        ["P38398", "CHEMBL1201585", "CHEMBL_T1", "IC50", now],
    )
    # Only link to breast carcinoma
    akg._conn.execute(
        "INSERT INTO protein_disease (uniprot_id, mondo_id, source, created_at) VALUES (?,?,?,?)",
        ["P38398", "MONDO:0007254", "opentargets", now],
    )
    akg._conn.commit()

    breast_rows = await akg.query_drug_landscape(mondo_id="MONDO:0007254", min_phase=4)
    assert any(r["chembl_id"] == "CHEMBL1201585" for r in breast_rows)

    ovarian_rows = await akg.query_drug_landscape(mondo_id="MONDO:0008170", min_phase=4)
    assert all(r["chembl_id"] != "CHEMBL1201585" for r in ovarian_rows)


# ── export_to_dict — explicit `tables` arg + allowlist enforcement ────────────


@pytest.mark.unit
async def test_export_to_dict_with_explicit_tables(akg: KnowledgeGraph) -> None:
    """Caller-supplied ``tables=`` must limit the export to listed tables only."""
    await akg.store_protein(uniprot_id="P_T1", gene_symbol="EXP_T1")
    await akg.store_disease(mondo_id="MONDO:0000001", name="test disease")

    export = await akg.export_to_dict(tables=["proteins"])
    assert set(export.keys()) == {"proteins"}
    # Verify our protein is in there
    assert any(p["uniprot_id"] == "P_T1" for p in export["proteins"])


@pytest.mark.unit
async def test_export_to_dict_rejects_unknown_table(akg: KnowledgeGraph) -> None:
    """An unlisted table name must raise ValueError (allowlist guard)."""
    with pytest.raises(ValueError, match="Unknown table"):
        await akg.export_to_dict(tables=["evil"])


@pytest.mark.unit
async def test_export_to_dict_rejects_sql_injection_attempt(
    akg: KnowledgeGraph,
) -> None:
    """SQL-injection-style identifiers must be rejected, not interpolated."""
    with pytest.raises(ValueError, match="Unknown table"):
        await akg.export_to_dict(tables=["proteins; DROP TABLE proteins"])


# ── get_knowledge_graph singleton ─────────────────────────────────────────────


@pytest.mark.unit
async def test_get_knowledge_graph_singleton_reuses_connection(
    tmp_path: Path,
) -> None:
    """First call creates the singleton; second call with same path reuses it."""
    # Reset module-level singleton to ensure hermetic test
    if kg_module._KG_SINGLETON is not None:
        await kg_module._KG_SINGLETON.close()
        kg_module._KG_SINGLETON = None

    db = tmp_path / "singleton.db"
    async with get_knowledge_graph(db_path=db) as kg1:
        first_id = id(kg1)
    async with get_knowledge_graph(db_path=db) as kg2:
        assert id(kg2) == first_id

    # Cleanup
    if kg_module._KG_SINGLETON is not None:
        await kg_module._KG_SINGLETON.close()
        kg_module._KG_SINGLETON = None


@pytest.mark.unit
async def test_get_knowledge_graph_switches_on_new_path(tmp_path: Path) -> None:
    """A different db_path must produce a fresh singleton (and close the old)."""
    # Reset module-level singleton
    if kg_module._KG_SINGLETON is not None:
        await kg_module._KG_SINGLETON.close()
        kg_module._KG_SINGLETON = None

    async with get_knowledge_graph(db_path=tmp_path / "a.db") as kg_a:
        a_id = id(kg_a)
    async with get_knowledge_graph(db_path=tmp_path / "b.db") as kg_b:
        # Different path -> new instance
        assert id(kg_b) != a_id
        assert str(kg_b._db_path).endswith("b.db")

    # Cleanup
    if kg_module._KG_SINGLETON is not None:
        await kg_module._KG_SINGLETON.close()
        kg_module._KG_SINGLETON = None
