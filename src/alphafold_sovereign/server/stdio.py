# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""Stdio MCP transport entry-point.

Aggregates every FastMCP instance from the ``tools/`` subpackages into a
single server and runs it over stdio.  This is the transport used by
Claude Desktop and other stdio-only MCP clients; Streamable HTTP +
OAuth land in Wave 3 (``server/http.py``).
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

import structlog

# Redirect all structlog output to stderr so stdout carries only MCP
# JSON-RPC frames. Claude Desktop treats ANY non-JSON byte on stdout
# as a protocol error.
structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=sys.stderr))

logger = structlog.get_logger(__name__)


def _build_server() -> object:
    """Import every tool module, then return the shared FastMCP application.

    All four tool modules (``precision_medicine``, ``structure_intelligence``,
    ``disease``, ``knowledge_graph_tools``) decorate the single ``mcp``
    instance defined in ``alphafold_sovereign.server.app``. Importing the
    modules here is a deliberate side-effecting import: it runs their
    ``@mcp.tool()`` decorators, populating the shared application's tool
    registry. The imports are deferred so module-level imports of
    ``server.stdio`` stay cheap.
    """
    from alphafold_sovereign.server.app import mcp  # noqa: PLC0415
    from alphafold_sovereign.tools import (  # noqa: F401, PLC0415
        disease,
        knowledge_graph_tools,
        precision_medicine,
        structure_intelligence,
    )

    return mcp


def run_stdio() -> None:
    """Boot the stdio MCP server.

    Honours ``ALPHAFOLD_OFFLINE`` (refuses every outbound call) and
    ``ALPHAFOLD_ALLOW_HOSTS`` (comma-separated allowlist for sovereign
    air-gap deployments).  Logs server start at INFO so operators can
    correlate against upstream tool-invocation logs.
    """
    offline = os.environ.get("ALPHAFOLD_OFFLINE", "").lower() in {"1", "true", "yes"}
    logger.info(
        "alphafold_sovereign.server.start",
        transport="stdio",
        offline=offline,
        allow_hosts=os.environ.get("ALPHAFOLD_ALLOW_HOSTS", ""),
    )
    _seed_kg_at_startup()
    server = _build_server()
    # FastMCP exposes ``.run()`` for synchronous stdio loop.
    server.run()  # type: ignore[attr-defined]


def _seed_kg_at_startup() -> None:
    """Load the curated knowledge-graph seed once, before serving requests.

    Seeding at boot (rather than lazily on first tool call) keeps the KG
    query/export tools genuinely read-only. Uses a throwaway instance so the
    on-disk DB is populated without binding the request-time singleton's lock
    to this transient event loop. Honours ``AFSMCP_DISABLE_KG_SEED`` and never
    blocks startup on failure.
    """
    import asyncio  # noqa: PLC0415

    from alphafold_sovereign.storage.knowledge_graph import KnowledgeGraph  # noqa: PLC0415

    if os.environ.get("AFSMCP_DISABLE_KG_SEED"):
        return

    async def _seed() -> None:
        async with KnowledgeGraph() as kg:
            await kg.seed_if_empty()

    try:
        asyncio.run(_seed())
    except Exception as exc:
        logger.warning("alphafold_sovereign.kg.seed_startup_failed", exc=str(exc))


if TYPE_CHECKING:
    # Re-export for `from alphafold_sovereign.server.stdio import run_stdio`
    __all__ = ["run_stdio"]
