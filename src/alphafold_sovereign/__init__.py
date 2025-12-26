"""
SOVEREIGN ALPHAFOLD CONNECTOR - PRIVATE FRAMEWORK
==================================================

PROPRIETARY AND CONFIDENTIAL
Patent-pending framework by Santiago Maniches (ORCID: 0009-0005-6480-1987)
TOPOLOGICA LLC - All Rights Reserved

THIS SOFTWARE IS NOT FOR PUBLIC DISTRIBUTION.
Unauthorized copying, modification, or distribution is strictly prohibited.

Architecture:
    HYBRID OPERATION MODE:
    1. PRIMARY: Local filesystem access (sovereign, no network)
    2. FALLBACK: AlphaFold Database online fetch (no API key required)
    
    This ensures complete coverage while maintaining sovereignty
    over cached data.

Mathematical Foundation:
    Protein structure P exists in configuration manifold M
    P: Sequence Space S -> Configuration Space C subset R^(3N)
    
    Topological invariants H_k(P) computed via:
    - Vietoris-Rips filtration VR(X, epsilon)
    - Persistent homology tracking birth/death of features
    - Betti numbers beta_0, beta_1, beta_2
"""

from .parsers import PDBParser, AlphaFoldStructure, AlphaFoldMetadata
from .core import SovereignAlphaFoldConnector, SovereignAlphaFoldConfig
from .features import StructureFeatureExtractor, StructureFeatures
from .topology import StructureTopologyAnalyzer, TopologicalFeatures
from .cache import SovereignStructureCache
from .fetcher import AlphaFoldFetcher

__version__ = "1.0.0-private"
__author__ = "Santiago Maniches (ORCID: 0009-0005-6480-1987)"
__license__ = "PROPRIETARY - NOT FOR PUBLIC DISTRIBUTION"
__patent_status__ = "PENDING"
__company__ = "TOPOLOGICA LLC"

# PRIVATE FRAMEWORK - NO PUBLIC EXPORTS
# All classes available for internal use only
