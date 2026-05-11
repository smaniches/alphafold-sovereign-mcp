# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Entry point for `python -m alphafold_sovereign` and the `alphafold-sovereign-mcp` console script."""
from __future__ import annotations

import sys


def main() -> None:
    """Start the AlphaFold Sovereign MCP server (stdio transport)."""
    from alphafold_sovereign.alphafold_mcp import mcp  # type: ignore[attr-defined]

    mcp.run()


if __name__ == "__main__":
    sys.exit(main())  # type: ignore[arg-type]
