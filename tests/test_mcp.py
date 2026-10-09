# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""MCP tool schema smoke tests — verify all tool modules import cleanly."""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_disease_tools_import() -> None:
    from alphafold_sovereign.tools import disease

    assert hasattr(disease, "mcp")


@pytest.mark.unit
def test_precision_medicine_tools_import() -> None:
    from alphafold_sovereign.tools import precision_medicine

    assert hasattr(precision_medicine, "mcp")


@pytest.mark.unit
def test_structure_intelligence_tools_import() -> None:
    from alphafold_sovereign.tools import structure_intelligence

    assert hasattr(structure_intelligence, "mcp")


@pytest.mark.unit
def test_knowledge_graph_tools_import() -> None:
    from alphafold_sovereign.tools import knowledge_graph_tools

    assert hasattr(knowledge_graph_tools, "mcp")


@pytest.mark.unit
def test_knowledge_graph_storage_import() -> None:
    from alphafold_sovereign.storage.knowledge_graph import KnowledgeGraph

    assert KnowledgeGraph is not None


@pytest.mark.asyncio
async def test_registered_tools_discoverable_over_mcp_protocol() -> None:
    """Exercise a real client/server MCP exchange, not only Python imports."""
    from fastmcp import Client

    from alphafold_sovereign.server.stdio import _build_server

    server = _build_server()
    async with Client(server) as client:
        tools = await client.list_tools()

    names = [tool.name for tool in tools]
    assert len(names) == 30
    assert len(names) == len(set(names))
    assert {
        "get_protein_structure",
        "analyze_structural_confidence",
        "generate_variant_clinical_report",
    }.issubset(names)
