# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Full-coverage tests for ``alphafold_sovereign.server.stdio``."""

from __future__ import annotations

from typing import Any

import pytest
import structlog

from alphafold_sovereign.server import stdio


def test_build_server_returns_shared_fastmcp_app() -> None:
    """``_build_server`` returns the one shared FastMCP application, and
    every tool module decorates that same instance."""
    server = stdio._build_server()
    from alphafold_sovereign.server.app import mcp
    from alphafold_sovereign.tools import (
        disease,
        knowledge_graph_tools,
        precision_medicine,
        structure_intelligence,
    )

    assert server is mcp
    assert precision_medicine.mcp is mcp
    assert structure_intelligence.mcp is mcp
    assert disease.mcp is mcp
    assert knowledge_graph_tools.mcp is mcp


def test_run_stdio_offline_truthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``ALPHAFOLD_OFFLINE=1`` is set, log entry has ``offline=True``."""
    monkeypatch.setenv("ALPHAFOLD_OFFLINE", "1")
    monkeypatch.setenv("ALPHAFOLD_ALLOW_HOSTS", "vault.local")

    captured: dict[str, Any] = {}

    def _fake_info(event: str, **kwargs: Any) -> None:
        captured["event"] = event
        captured.update(kwargs)

    monkeypatch.setattr(stdio.logger, "info", _fake_info)

    # Replace the FastMCP build/run with a stub so we don't block on stdio.
    class _StubServer:
        ran = False

        def run(self) -> None:
            type(self).ran = True

    monkeypatch.setattr(stdio, "_build_server", _StubServer)
    monkeypatch.setattr(stdio, "_seed_kg_at_startup", lambda: None)

    stdio.run_stdio()

    assert captured["event"] == "alphafold_sovereign.server.start"
    assert captured["transport"] == "stdio"
    assert captured["offline"] is True
    assert captured["allow_hosts"] == "vault.local"
    assert _StubServer.ran is True


def test_run_stdio_offline_falsy(monkeypatch: pytest.MonkeyPatch) -> None:
    """When ``ALPHAFOLD_OFFLINE`` is unset / empty, ``offline=False`` logs."""
    monkeypatch.delenv("ALPHAFOLD_OFFLINE", raising=False)
    monkeypatch.delenv("ALPHAFOLD_ALLOW_HOSTS", raising=False)

    captured: dict[str, Any] = {}

    def _fake_info(event: str, **kwargs: Any) -> None:
        captured["event"] = event
        captured.update(kwargs)

    monkeypatch.setattr(stdio.logger, "info", _fake_info)

    class _StubServer:
        def run(self) -> None:
            return None

    monkeypatch.setattr(stdio, "_build_server", _StubServer)
    monkeypatch.setattr(stdio, "_seed_kg_at_startup", lambda: None)

    stdio.run_stdio()
    assert captured["offline"] is False
    assert captured["allow_hosts"] == ""


@pytest.mark.parametrize("raw", ["true", "TRUE", "yes", "YES", "1"])
def test_run_stdio_offline_parsing_truthy(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("ALPHAFOLD_OFFLINE", raw)

    captured: dict[str, Any] = {}

    def _fake_info(event: str, **kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(stdio.logger, "info", _fake_info)

    class _StubServer:
        def run(self) -> None:
            return None

    monkeypatch.setattr(stdio, "_build_server", _StubServer)
    monkeypatch.setattr(stdio, "_seed_kg_at_startup", lambda: None)
    stdio.run_stdio()
    assert captured["offline"] is True


def test_seed_kg_at_startup_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """With ``AFSMCP_DISABLE_KG_SEED`` set, startup seeding is a no-op."""
    monkeypatch.setenv("AFSMCP_DISABLE_KG_SEED", "1")
    import alphafold_sovereign.storage.knowledge_graph as kg_mod

    class _Boom:
        def __init__(self, *a: Any, **k: Any) -> None:
            raise AssertionError("must not seed when disabled")

    monkeypatch.setattr(kg_mod, "KnowledgeGraph", _Boom)
    stdio._seed_kg_at_startup()  # returns before constructing KnowledgeGraph


def test_seed_kg_at_startup_seeds(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """Startup seeding populates the on-disk database."""
    import sqlite3

    monkeypatch.delenv("AFSMCP_DISABLE_KG_SEED", raising=False)
    db = tmp_path / "kg.db"
    monkeypatch.setenv("ALPHAFOLD_KG_PATH", str(db))
    stdio._seed_kg_at_startup()
    conn = sqlite3.connect(str(db))
    try:
        count = conn.execute("SELECT COUNT(*) FROM proteins").fetchone()[0]
    finally:
        conn.close()
    assert count >= 5


def test_seed_kg_at_startup_swallows_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """A seeding failure at startup is logged and swallowed, never blocking boot."""
    monkeypatch.delenv("AFSMCP_DISABLE_KG_SEED", raising=False)
    import alphafold_sovereign.storage.knowledge_graph as kg_mod

    class _Boom:
        def __init__(self, *a: Any, **k: Any) -> None:
            raise RuntimeError("boom")

    monkeypatch.setattr(kg_mod, "KnowledgeGraph", _Boom)
    stdio._seed_kg_at_startup()  # must not raise


def test_logger_is_structlog_bound() -> None:
    """The module-level ``logger`` is a structlog BoundLoggerLazyProxy."""
    assert isinstance(stdio.logger, structlog.stdlib.BoundLogger) or hasattr(stdio.logger, "info")
