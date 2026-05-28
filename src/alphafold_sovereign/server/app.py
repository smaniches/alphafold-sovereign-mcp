# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""Canonical FastMCP application instance for AlphaFold Sovereign.

Every tool module under ``alphafold_sovereign.tools`` registers its
``@mcp.tool()`` decorators against the single ``mcp`` object defined here.
The stdio transport in ``server/stdio.py`` then serves that one object, so a
single MCP session exposes the full tool surface: precision-medicine,
structure-intelligence, disease-ontology, and knowledge-graph tools.

This module is intentionally a leaf in the import graph: it imports only
``fastmcp`` and the package ``__version__`` constant (a trivial,
cycle-free read from the already-initialised top-level package). Any tool
module can therefore do ``from alphafold_sovereign.server.app import mcp``
with no risk of a circular import.
"""

from __future__ import annotations

from fastmcp import FastMCP

from alphafold_sovereign import __version__

# The single MCP application. Tool modules decorate this; server/stdio.py
# serves it. Exactly one application instance exists per process.
# ``version`` is surfaced to clients in the MCP ``initialize`` handshake,
# so it must be the package version rather than FastMCP's own default.
mcp: FastMCP = FastMCP("alphafold-sovereign", version=__version__)
