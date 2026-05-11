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

from typing import TYPE_CHECKING, Any

__version__ = "1.1.0"
__author__ = "Santiago Maniches"
__author_email__ = "santiago@topologica.ai"
__license__ = "Apache-2.0"
__orcid__ = "0009-0005-6480-1987"
__company__ = "TOPOLOGICA LLC"
__patent_status__ = "PENDING — drift tensor + topological fingerprint (see PATENTS.md)"

# Legacy re-exports are resolved lazily via PEP 562 so that
# ``import alphafold_sovereign`` works even without the heavy scientific deps
# (numpy, scipy, gudhi, ripser).  The CI Build Distribution job installs the
# wheel with ``--no-deps`` and then runs ``import alphafold_sovereign`` to verify
# the package is importable — that path must not pull numpy.

_LAZY_EXPORTS: dict[str, str] = {
    "PDBParser": "alphafold_sovereign.parsers",
    "AlphaFoldStructure": "alphafold_sovereign.parsers",
    "AlphaFoldMetadata": "alphafold_sovereign.parsers",
    "SovereignAlphaFoldConnector": "alphafold_sovereign.core",
    "SovereignAlphaFoldConfig": "alphafold_sovereign.core",
    "StructureFeatureExtractor": "alphafold_sovereign.features",
    "StructureFeatures": "alphafold_sovereign.features",
    "StructureTopologyAnalyzer": "alphafold_sovereign.topology",
    "TopologicalFeatures": "alphafold_sovereign.topology",
    "SovereignStructureCache": "alphafold_sovereign.cache",
    "AlphaFoldFetcher": "alphafold_sovereign.fetcher",
}


def __getattr__(name: str) -> Any:
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module 'alphafold_sovereign' has no attribute {name!r}")
    import importlib

    module = importlib.import_module(module_path)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + list(_LAZY_EXPORTS.keys()))


if TYPE_CHECKING:
    from alphafold_sovereign.cache import SovereignStructureCache
    from alphafold_sovereign.core import SovereignAlphaFoldConfig, SovereignAlphaFoldConnector
    from alphafold_sovereign.features import StructureFeatureExtractor, StructureFeatures
    from alphafold_sovereign.fetcher import AlphaFoldFetcher
    from alphafold_sovereign.parsers import AlphaFoldMetadata, AlphaFoldStructure, PDBParser
    from alphafold_sovereign.topology import StructureTopologyAnalyzer, TopologicalFeatures

__all__ = [
    "__version__",
    "__author__",
    "__license__",
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
