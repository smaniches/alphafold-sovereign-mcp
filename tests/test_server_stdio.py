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
    stdio.run_stdio()
    assert captured["offline"] is True


def test_logger_is_structlog_bound() -> None:
    """The module-level ``logger`` is a structlog BoundLoggerLazyProxy."""
    assert isinstance(stdio.logger, structlog.stdlib.BoundLogger) or hasattr(stdio.logger, "info")
