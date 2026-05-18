# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""AlphaFold Sovereign MCP.

A Model Context Protocol server that wraps AlphaFold DB and 13 other
public biomedical data sources behind MCP tool calls, and persists
each result to a local SQLite knowledge graph for later querying.

Licensed under Apache 2.0.  See `LICENSE`.
"""

from __future__ import annotations

__version__ = "1.1.7"
__author__ = "Santiago Maniches"
__author_email__ = "santiago@topologica.ai"
__license__ = "Apache-2.0"
__orcid__ = "0009-0005-6480-1987"

__all__ = [
    "__author__",
    "__author_email__",
    "__license__",
    "__orcid__",
    "__version__",
]
