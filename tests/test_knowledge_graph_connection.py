# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Connection-level tests for the local knowledge graph."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from alphafold_sovereign.storage.knowledge_graph import KnowledgeGraph

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
async def test_connect_applies_busy_timeout_to_each_connection(tmp_path: Path) -> None:
    """Every opened SQLite connection should wait briefly on write contention."""
    for index in range(2):
        db = KnowledgeGraph(db_path=tmp_path / f"busy-timeout-{index}.db")
        await db.connect()
        try:
            assert db._conn is not None
            row = db._conn.execute("PRAGMA busy_timeout").fetchone()
            assert row is not None
            assert row[0] == 5000
        finally:
            await db.close()
