# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""Canonical FastMCP application instance for AlphaFold Sovereign.

Every tool module under ``alphafold_sovereign.tools`` registers its
``@mcp.tool()`` decorators against the single ``mcp`` object defined here.
The stdio transport in ``server/stdio.py`` then serves that one object, so a
single MCP session exposes the full tool surface: precision-medicine,
structure-intelligence, disease-ontology, and knowledge-graph tools.

This module is intentionally a leaf in the import graph: it imports only
``fastmcp``. Any tool module can therefore do
``from alphafold_sovereign.server.app import mcp`` with no risk of a
circular import.
"""

from __future__ import annotations

from fastmcp import FastMCP

# The single MCP application. Tool modules decorate this; server/stdio.py
# serves it. Exactly one application instance exists per process.
mcp: FastMCP = FastMCP("alphafold-sovereign")
