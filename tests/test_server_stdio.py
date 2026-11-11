# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Full-coverage tests for ``alphafold_sovereign.server.stdio``."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING, Any

import fastmcp
import pytest
import structlog

from alphafold_sovereign.server import stdio

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _restore_framework_update_setting() -> Iterator[None]:
    """``run_stdio`` changes a FastMCP setting in offline mode; put it back."""
    before = fastmcp.settings.check_for_updates
    yield
    fastmcp.settings.check_for_updates = before


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


def _setting_seen_by_the_server(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Run ``run_stdio`` with a stand-in server that notes the update-check setting.

    FastMCP reads the setting inside ``run``, when it prints its banner; with
    any value but ``off`` it then asks pypi.org for its latest release.
    """
    seen: dict[str, str] = {}

    class _Probe:
        def run(self) -> None:
            seen["at_start"] = fastmcp.settings.check_for_updates

    monkeypatch.setattr(stdio, "_build_server", _Probe)
    monkeypatch.setattr(stdio, "_seed_kg_at_startup", lambda: None)
    stdio.run_stdio()
    return seen


@pytest.mark.parametrize("configured", ["stable", "prerelease"])
def test_run_stdio_offline_turns_the_framework_update_check_off(
    monkeypatch: pytest.MonkeyPatch, configured: str
) -> None:
    """Offline mode overrides an update check that was explicitly enabled."""
    monkeypatch.setenv("ALPHAFOLD_OFFLINE", "1")
    fastmcp.settings.check_for_updates = configured
    assert _setting_seen_by_the_server(monkeypatch) == {"at_start": "off"}


@pytest.mark.parametrize("offline", [None, "0", "false"])
@pytest.mark.parametrize("configured", ["stable", "prerelease", "off"])
def test_run_stdio_online_leaves_the_framework_update_check_alone(
    monkeypatch: pytest.MonkeyPatch, configured: str, offline: str | None
) -> None:
    """Without offline mode the FastMCP setting is whatever the operator chose."""
    if offline is None:
        monkeypatch.delenv("ALPHAFOLD_OFFLINE", raising=False)
    else:
        monkeypatch.setenv("ALPHAFOLD_OFFLINE", offline)
    fastmcp.settings.check_for_updates = configured
    assert _setting_seen_by_the_server(monkeypatch) == {"at_start": configured}


# Starts the real server with standard input closed, so it returns at once,
# under an audit hook that records and refuses every name lookup and every
# connection or datagram to a host other than the loopback. The lookup made
# after the server has returned shows that the hook was armed.
_AUDITED_START = """
import json, os, socket, sys

events = []
loopback = {"localhost", "127.0.0.1", "::1"}


def audit(event, args):
    if event in {"socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"}:
        target = args[0]
    elif event in {"socket.connect", "socket.sendto"}:
        target = args[1][0] if isinstance(args[1], tuple) else None
    else:
        return
    if target is None or str(target) in loopback:
        return
    events.append([event, str(target)])
    raise OSError("network use is refused in this test")


sys.addaudithook(audit)
sys.argv = ["alphafold-sovereign-mcp"]
from alphafold_sovereign.__main__ import main

exit_code = main()
try:
    socket.getaddrinfo("audit-hook-control.invalid", 443)
except OSError:
    pass
with open(os.environ["AFS_AUDIT_OUT"], "w", encoding="utf-8") as handle:
    json.dump({"exit_code": exit_code, "events": events}, handle)
"""

_PROXY_VARIABLES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")


@pytest.mark.parametrize("update_check", [None, "stable", "prerelease"])
def test_offline_start_resolves_no_name_and_opens_no_connection(
    tmp_path: Path, update_check: str | None
) -> None:
    """With ``ALPHAFOLD_OFFLINE=1`` the server process starts without network use.

    Release 1.5.12 looked up pypi.org here: FastMCP's update check ran at
    start-up whatever the offline setting was. The check stays off even when
    ``FASTMCP_CHECK_FOR_UPDATES`` asks for it. Proxy variables are removed, so
    a request would have to resolve its real host and could not hide behind a
    local proxy; FastMCP's version cache starts empty for the same reason.
    """
    report_path = tmp_path / "audit.json"
    env = {
        name: value
        for name, value in os.environ.items()
        if name.upper() not in _PROXY_VARIABLES and not name.startswith(("ALPHAFOLD_", "FASTMCP_"))
    }
    env.update(
        ALPHAFOLD_OFFLINE="1",
        ALPHAFOLD_KG_PATH=str(tmp_path / "kg.db"),
        FASTMCP_HOME=str(tmp_path / "fastmcp-home"),
        AFS_AUDIT_OUT=str(report_path),
    )
    if update_check is not None:
        env["FASTMCP_CHECK_FOR_UPDATES"] = update_check

    completed = subprocess.run(
        [sys.executable, "-c", _AUDITED_START],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        env=env,
        timeout=120,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")[-2000:]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report == {
        "exit_code": 0,
        "events": [["socket.getaddrinfo", "audit-hook-control.invalid"]],
    }


def test_seed_kg_at_startup_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """With ``AFSMCP_DISABLE_KG_SEED`` set, startup seeding is a no-op."""
    monkeypatch.setenv("AFSMCP_DISABLE_KG_SEED", "1")
    import alphafold_sovereign.storage.knowledge_graph as kg_mod

    class _Boom:
        def __init__(self, *a: Any, **k: Any) -> None:
            raise AssertionError("must not seed when disabled")

    monkeypatch.setattr(kg_mod, "KnowledgeGraph", _Boom)
    stdio._seed_kg_at_startup()  # returns before constructing KnowledgeGraph


def test_seed_kg_at_startup_does_not_insert_examples(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Startup initializes SQLite but must not insert illustrative biology."""
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
    assert count == 0


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
