# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Stdio MCP transport entry-point.

Aggregates every FastMCP instance from the ``tools/`` subpackages into a
single server and runs it over stdio.  This is the transport used by
Claude Desktop and other stdio-only MCP clients; Streamable HTTP +
OAuth land in Wave 3 (``server/http.py``).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import structlog

logger = structlog.get_logger(__name__)


def _build_server() -> object:
    """Import each tool module so its `@mcp.tool()` decorators register.

    Each tool module owns its own ``FastMCP`` instance named ``mcp``; we
    pick the first one and rely on the side-effect imports of the others
    to register against it.  In a future wave, all tools migrate onto a
    single shared ``FastMCP`` instance owned by this module.
    """
    # Side-effect imports register each tool's @mcp.tool() decorators.
    # Deferred so module-level imports of `server.stdio` stay cheap.
    from alphafold_sovereign.tools import (  # noqa: F401, PLC0415
        disease,
        knowledge_graph_tools,
        precision_medicine,
        structure_intelligence,
    )

    # Use the precision-medicine module's FastMCP server as the primary entry
    # point — every other tool module decorates the same global namespace.
    return precision_medicine.mcp


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
    server = _build_server()
    # FastMCP exposes ``.run()`` for synchronous stdio loop.
    server.run()  # type: ignore[attr-defined]


if TYPE_CHECKING:
    # Re-export for `from alphafold_sovereign.server.stdio import run_stdio`
    __all__ = ["run_stdio"]
