# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""AlphaFold Sovereign MCP — the sovereign, auditable MCP server for structural biology.

Fuses AlphaFold DB with 14 bio data sources under one MCP interface:
persistent-homology TDA, precision-medicine variant triage, defense-grade
sovereignty stack, and a local relational knowledge graph.

Apache 2.0 community edition.
Commercial Enterprise Edition → enterprise@topologica.ai

Mathematical foundation:
    Protein structure P exists in configuration manifold M.
    Topological invariants H_k(P) computed via Vietoris-Rips filtration.
    Betti numbers β₀, β₁, β₂ form a 64-dimensional fingerprint vector.
    Drift tensor R² = 0.9992 (patent-pending, TOPOLOGICA LLC).
"""
from __future__ import annotations

__version__ = "1.1.0"
__author__ = "Santiago Maniches"
__author_email__ = "santiago@topologica.ai"
__license__ = "Apache-2.0"
__orcid__ = "0009-0005-6480-1987"
__company__ = "TOPOLOGICA LLC"
__patent_status__ = "PENDING — drift tensor + topological fingerprint (see PATENTS.md)"

# Public re-exports from the legacy core (maintained for backwards compatibility
# during the Wave 1 monolith decomposition).
from alphafold_sovereign.parsers import AlphaFoldMetadata, AlphaFoldStructure, PDBParser
from alphafold_sovereign.core import SovereignAlphaFoldConfig, SovereignAlphaFoldConnector
from alphafold_sovereign.features import StructureFeatureExtractor, StructureFeatures
from alphafold_sovereign.topology import StructureTopologyAnalyzer, TopologicalFeatures
from alphafold_sovereign.cache import SovereignStructureCache
from alphafold_sovereign.fetcher import AlphaFoldFetcher

__all__ = [
    # version
    "__version__",
    "__author__",
    "__license__",
    # legacy core (deprecation-safe during decomposition)
    "PDBParser",
    "AlphaFoldStructure",
    "AlphaFoldMetadata",
    "SovereignAlphaFoldConnector",
    "SovereignAlphaFoldConfig",
    "StructureFeatureExtractor",
    "StructureFeatures",
    "StructureTopologyAnalyzer",
    "TopologicalFeatures",
    "SovereignStructureCache",
    "AlphaFoldFetcher",
]
