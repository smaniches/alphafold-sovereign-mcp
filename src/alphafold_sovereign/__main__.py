# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Entry point for `python -m alphafold_sovereign` and the console script.

Launches the AlphaFold Sovereign MCP server over stdio transport
(suitable for Claude Desktop and other stdio-based MCP clients).
The Streamable HTTP transport lands in Wave 3.
"""

from __future__ import annotations

import sys


def main() -> int:
    """Start the AlphaFold Sovereign MCP server (stdio transport)."""
    # Deferred to avoid eagerly importing FastMCP + the full client tree
    # at module-import time (keeps ``alphafold_sovereign.__version__`` cheap).
    from alphafold_sovereign.server.stdio import run_stdio  # noqa: PLC0415

    run_stdio()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
