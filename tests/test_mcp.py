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
