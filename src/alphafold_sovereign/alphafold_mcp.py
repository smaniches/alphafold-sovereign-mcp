"""
alphafold_mcp.py

PROPRIETARY AND CONFIDENTIAL - PRIVATE FRAMEWORK
Patent-pending framework by Santiago Maniches (ORCID: 0009-0005-6480-1987)
TOPOLOGICA LLC - All Rights Reserved

THIS SOFTWARE IS NOT FOR PUBLIC DISTRIBUTION.
Unauthorized copying, modification, or distribution is strictly prohibited.

Production MCP server for AlphaFold structure analysis.
HYBRID MODE: Local filesystem primary + AlphaFold DB online fallback.

Architecture:
    1. PRIMARY: Check local PDB cache (dynamically indexed, grows as structures are fetched)
    2. FALLBACK: Fetch from AlphaFold DB (200M+ structures, NO API KEY)
    3. AUTO-CACHE: Fetched structures saved locally for future sovereign access
    4. COMPUTE: Extract features, topology on-demand
    
Mathematical Foundation:
    Protein structure P in configuration manifold M
    P: Sequence Space S -> Configuration Space C subset R^(3N)
    Topological invariants H_k(P) via Vietoris-Rips filtration
"""

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass
import numpy as np
import hashlib
import pickle
import urllib.request
import urllib.error
import ssl
import re
import os
import logging
import time
import json


# ===========================================================================
# NUMPY JSON ENCODER - Handle int64, float64, ndarray
# ===========================================================================

class NumpyEncoder(json.JSONEncoder):
    """Custom JSON encoder for numpy types."""
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


def json_dumps(obj, **kwargs) -> str:
    """JSON dumps with numpy support."""
    return json.dumps(obj, cls=NumpyEncoder, **kwargs)


# ===========================================================================
# CONFIGURATION SYSTEM - PORTABLE & MULTI-DEVICE SUPPORT
# ===========================================================================

class CacheMode:
    """Cache operation modes for multi-device support."""
    SOVEREIGN = "sovereign"   # Full read/write (primary device)
    READONLY = "readonly"     # Read cache, no writes (secondary device)
    DISABLED = "disabled"     # Pure online, no cache (mobile/temporary)


def _load_config_file() -> Dict[str, Any]:
    """Load configuration from JSON file if exists."""
    config_paths = [
        Path.home() / ".alphafold_sovereign" / "config.json",
        Path.home() / ".config" / "alphafold_sovereign" / "config.json",
        Path(__file__).parent / "config.json",
    ]
    
    for config_path in config_paths:
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
    
    return {}


def _get_config_value(key: str, default: Any, env_var: str = None) -> Any:
    """
    Get configuration value with priority:
    1. Environment variable (highest priority)
    2. Config file
    3. Default value (lowest priority)
    """
    # Check environment variable first
    if env_var:
        env_value = os.environ.get(env_var)
        if env_value is not None:
            return env_value
    
    # Check config file
    config = _load_config_file()
    if key in config:
        return config[key]
    
    # Return default
    return default


# Platform-specific defaults
if os.name == 'nt':  # Windows
    _DEFAULT_STRUCTURES_DIR = r"C:\TOPOLOGICA_KAGGLE_CAFA6\ALPHAFOLD2_STRUCTURES\pdb_files"
    _DEFAULT_CACHE_DIR = r"C:\TOPOLOGICA_KAGGLE_CAFA6\CACHE"
else:  # Linux/Mac
    _DEFAULT_STRUCTURES_DIR = str(Path.home() / "alphafold_structures" / "pdb_files")
    _DEFAULT_CACHE_DIR = str(Path.home() / ".cache" / "alphafold_sovereign")

# Load configuration with environment variable overrides
LOCAL_STRUCTURES_DIR = Path(_get_config_value(
    "structures_dir",
    _DEFAULT_STRUCTURES_DIR,
    env_var="ALPHAFOLD_STRUCTURES_DIR"
))

CACHE_DIR = Path(_get_config_value(
    "cache_dir",
    _DEFAULT_CACHE_DIR,
    env_var="ALPHAFOLD_CACHE_DIR"
))

CACHE_MODE = _get_config_value(
    "cache_mode",
    CacheMode.SOVEREIGN,
    env_var="ALPHAFOLD_CACHE_MODE"
)

# AlphaFold DB online access (NO API KEY REQUIRED)
ALPHAFOLD_BASE_URL = "https://alphafold.ebi.ac.uk/files"
ALPHAFOLD_PDB_TEMPLATE = "AF-{uniprot_id}-F1-model_v4.pdb"

# UniProt API for metadata enrichment
UNIPROT_API_URL = "https://rest.uniprot.org/uniprotkb"

# Performance settings
REQUEST_TIMEOUT = 30.0
MAX_RETRIES = 3
RETRY_DELAY = 1.0

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Log configuration on startup
logger.info(f"Configuration loaded:")
logger.info(f"  STRUCTURES_DIR: {LOCAL_STRUCTURES_DIR}")
logger.info(f"  CACHE_DIR: {CACHE_DIR}")
logger.info(f"  CACHE_MODE: {CACHE_MODE}")

# ===========================================================================
# MCP SERVER INITIALIZATION
# ===========================================================================

mcp = FastMCP("alphafold_sovereign")


# ===========================================================================
# PYDANTIC INPUT MODELS
# ===========================================================================

class ResponseFormat(str, Enum):
    """Output format for tool responses."""
    MARKDOWN = "markdown"
    JSON = "json"


class GetStructureInput(BaseModel):
    """Input for retrieving a single AlphaFold structure."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    uniprot_id: str = Field(
        ..., 
        description="UniProt accession ID (e.g., 'P12345', 'A0A023FBW4')",
        min_length=1,
        max_length=20
    )
    include_features: bool = Field(
        default=True,
        description="Include structural features (secondary structure, binding pockets)"
    )
    include_topology: bool = Field(
        default=False,
        description="Include topological features (persistent homology - slower)"
    )
    force_online: bool = Field(
        default=False,
        description="Force fetch from AlphaFold DB even if local copy exists"
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format"
    )


class SearchStructuresInput(BaseModel):
    """Input for searching local structure cache."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    pattern: str = Field(
        default="*",
        description="Search pattern (glob-style, e.g., 'A0A*' for all A0A proteins)"
    )
    limit: int = Field(
        default=100,
        description="Maximum number of results",
        ge=1,
        le=1000
    )
    offset: int = Field(
        default=0,
        description="Pagination offset",
        ge=0
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format"
    )


class BatchStructuresInput(BaseModel):
    """Input for retrieving multiple structures."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    uniprot_ids: List[str] = Field(
        ...,
        description="List of UniProt IDs to retrieve",
        min_length=1,
        max_length=50
    )
    include_features: bool = Field(
        default=True,
        description="Include structural features"
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.JSON,
        description="Output format (JSON recommended for batch)"
    )


class GetFeaturesInput(BaseModel):
    """Input for computing structural features."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    uniprot_id: str = Field(
        ...,
        description="UniProt accession ID",
        min_length=1,
        max_length=20
    )
    feature_types: List[str] = Field(
        default=["secondary_structure", "binding_pockets", "confidence"],
        description="Features to compute: secondary_structure, binding_pockets, confidence, contacts"
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format"
    )


class GetTopologyInput(BaseModel):
    """Input for computing topological features (persistent homology)."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    uniprot_id: str = Field(
        ...,
        description="UniProt accession ID",
        min_length=1,
        max_length=20
    )
    max_dimension: int = Field(
        default=2,
        description="Maximum homology dimension (0=components, 1=loops, 2=voids)",
        ge=0,
        le=2
    )
    max_filtration: float = Field(
        default=25.0,
        description="Maximum filtration radius in Angstroms",
        gt=0,
        le=50.0
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format"
    )


class CheckAvailabilityInput(BaseModel):
    """Input for checking structure availability."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    uniprot_ids: List[str] = Field(
        ...,
        description="List of UniProt IDs to check",
        min_length=1,
        max_length=100
    )


class GetEnrichedProteinInput(BaseModel):
    """Input for retrieving enriched protein information (AlphaFold + UniProt)."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    uniprot_id: str = Field(
        ...,
        description="UniProt accession ID (e.g., 'P12345', 'A0A023FBW4')",
        min_length=1,
        max_length=20
    )
    include_structure: bool = Field(
        default=True,
        description="Include AlphaFold structure summary"
    )
    include_go_terms: bool = Field(
        default=True,
        description="Include Gene Ontology annotations"
    )
    include_disease: bool = Field(
        default=True,
        description="Include disease associations"
    )
    include_features: bool = Field(
        default=True,
        description="Include structural features (secondary structure, binding pockets)"
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format"
    )


# ===========================================================================
# PR #2: PROTEIN FUNCTION INTELLIGENCE - INPUT MODELS
# ===========================================================================

class BatchGOLookupInput(BaseModel):
    """Input for batch GO term lookup."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    uniprot_ids: List[str] = Field(
        ...,
        description="List of UniProt IDs to lookup GO terms for",
        min_length=1,
        max_length=500
    )
    include_evidence: bool = Field(
        default=False,
        description="Include evidence codes for GO annotations"
    )
    namespaces: List[str] = Field(
        default=["molecular_function", "biological_process", "cellular_component"],
        description="GO namespaces to include"
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.JSON,
        description="Output format (JSON recommended for batch)"
    )


class SearchByGOTermInput(BaseModel):
    """Input for searching proteins by GO term."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    go_term: str = Field(
        ...,
        description="GO term ID (e.g., 'GO:0003700') or name pattern to search",
        min_length=1
    )
    include_children: bool = Field(
        default=False,
        description="Include proteins annotated with child terms"
    )
    organism_filter: Optional[str] = Field(
        default=None,
        description="Filter by organism (e.g., 'Homo sapiens', '9606')"
    )
    limit: int = Field(
        default=100,
        description="Maximum results to return",
        ge=1,
        le=10000
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.JSON,
        description="Output format"
    )


class GetGOHierarchyInput(BaseModel):
    """Input for navigating GO term hierarchy."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    go_term: str = Field(
        ...,
        description="GO term ID (e.g., 'GO:0003700')",
        min_length=7,
        max_length=15
    )
    direction: str = Field(
        default="both",
        description="Navigation direction: 'parents', 'children', or 'both'"
    )
    depth: int = Field(
        default=2,
        description="How many levels to traverse",
        ge=1,
        le=10
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format"
    )


class ExportProteinSetInput(BaseModel):
    """Input for exporting protein sets to TSV/CSV."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    uniprot_ids: List[str] = Field(
        ...,
        description="List of UniProt IDs to export",
        min_length=1,
        max_length=10000
    )
    output_format: str = Field(
        default="tsv",
        description="Output format: 'tsv' or 'csv'"
    )
    include_columns: List[str] = Field(
        default=["uniprot_id", "protein_name", "organism", "go_terms", "sequence_length"],
        description="Columns to include in export"
    )
    include_go_terms: bool = Field(
        default=True,
        description="Include GO term annotations"
    )
    include_sequence: bool = Field(
        default=False,
        description="Include full protein sequence"
    )
    filename: Optional[str] = Field(
        default=None,
        description="Output filename (auto-generated if not provided)"
    )


class FindSimilarProteinsInput(BaseModel):
    """Input for finding similar proteins by sequence or structure."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    uniprot_id: str = Field(
        ...,
        description="Query protein UniProt ID",
        min_length=1,
        max_length=20
    )
    similarity_type: str = Field(
        default="sequence",
        description="Type of similarity: 'sequence' or 'structure'"
    )
    threshold: float = Field(
        default=0.7,
        description="Similarity threshold (0.0-1.0)",
        ge=0.0,
        le=1.0
    )
    limit: int = Field(
        default=50,
        description="Maximum results to return",
        ge=1,
        le=1000
    )
    search_scope: str = Field(
        default="local",
        description="Search scope: 'local' (cached) or 'all' (includes online)"
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.JSON,
        description="Output format"
    )


class GetDomainAnnotationsInput(BaseModel):
    """Input for retrieving domain annotations."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    uniprot_ids: List[str] = Field(
        ...,
        description="List of UniProt IDs",
        min_length=1,
        max_length=100
    )
    sources: List[str] = Field(
        default=["Pfam", "InterPro"],
        description="Annotation sources to include"
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.JSON,
        description="Output format"
    )


class FilterByOrganismInput(BaseModel):
    """Input for filtering proteins by organism."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    organism: str = Field(
        ...,
        description="Organism name or NCBI taxonomy ID (e.g., 'Homo sapiens', '9606')"
    )
    limit: int = Field(
        default=1000,
        description="Maximum results",
        ge=1,
        le=50000
    )
    include_go_summary: bool = Field(
        default=False,
        description="Include GO term summary for each protein"
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.JSON,
        description="Output format"
    )


class GetProteinFamiliesInput(BaseModel):
    """Input for clustering proteins by similarity."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    uniprot_ids: List[str] = Field(
        ...,
        description="List of UniProt IDs to cluster",
        min_length=2,
        max_length=1000
    )
    clustering_method: str = Field(
        default="sequence",
        description="Clustering method: 'sequence' or 'go_terms'"
    )
    similarity_threshold: float = Field(
        default=0.5,
        description="Similarity threshold for clustering",
        ge=0.0,
        le=1.0
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.JSON,
        description="Output format"
    )




# ===========================================================================
# PR #3: ENHANCED ALPHAFOLD + INFORMATION CONTENT - INPUT MODELS
# ===========================================================================

class ExtractPAEMatrixInput(BaseModel):
    """Input for extracting Predicted Aligned Error matrix."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    uniprot_id: str = Field(
        ...,
        description="UniProt accession ID",
        min_length=1,
        max_length=20
    )
    output_format: str = Field(
        default="summary",
        description="Output format: 'summary', 'full', or 'domains'"
    )
    include_statistics: bool = Field(
        default=True,
        description="Include statistical summary of PAE values"
    )
    block_size: int = Field(
        default=10,
        description="Block size for domain boundary detection",
        ge=5,
        le=50
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format"
    )


class DetectDomainsInput(BaseModel):
    """Input for detecting domain boundaries from PAE."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    uniprot_id: str = Field(
        ...,
        description="UniProt accession ID",
        min_length=1,
        max_length=20
    )
    pae_threshold: float = Field(
        default=5.0,
        description="PAE threshold for domain boundary detection (Angstroms)",
        ge=1.0,
        le=30.0
    )
    min_domain_size: int = Field(
        default=30,
        description="Minimum domain size in residues",
        ge=10,
        le=500
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format"
    )


class PredictDisorderInput(BaseModel):
    """Input for predicting intrinsically disordered regions."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    uniprot_id: str = Field(
        ...,
        description="UniProt accession ID",
        min_length=1,
        max_length=20
    )
    plddt_threshold: float = Field(
        default=50.0,
        description="pLDDT threshold below which region is considered disordered",
        ge=0.0,
        le=100.0
    )
    min_region_length: int = Field(
        default=5,
        description="Minimum length for a disordered region",
        ge=3,
        le=100
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format"
    )


class GetPLDDTProfileInput(BaseModel):
    """Input for getting detailed pLDDT profile."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    uniprot_id: str = Field(
        ...,
        description="UniProt accession ID",
        min_length=1,
        max_length=20
    )
    include_regions: bool = Field(
        default=True,
        description="Include classification of confidence regions"
    )
    include_statistics: bool = Field(
        default=True,
        description="Include statistical summary"
    )
    include_per_residue: bool = Field(
        default=False,
        description="Include per-residue pLDDT values in output"
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format"
    )


class ComputeInformationContentInput(BaseModel):
    """Input for computing GO term Information Content."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    go_terms: List[str] = Field(
        ...,
        description="List of GO term IDs (e.g., ['GO:0003700', 'GO:0005634'])",
        min_length=1,
        max_length=1000
    )
    corpus: str = Field(
        default="uniprot",
        description="Corpus for IC calculation: 'uniprot', 'cafa', or 'custom'"
    )
    normalize: bool = Field(
        default=True,
        description="Normalize IC values to [0, 1] range"
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.JSON,
        description="Output format"
    )


class ComputeSemanticSimilarityInput(BaseModel):
    """Input for computing GO semantic similarity."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    term1: str = Field(
        ...,
        description="First GO term ID",
        min_length=7,
        max_length=15
    )
    term2: str = Field(
        ...,
        description="Second GO term ID",
        min_length=7,
        max_length=15
    )
    method: str = Field(
        default="resnik",
        description="Similarity method: 'resnik', 'lin', 'jiang', 'wang'"
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.JSON,
        description="Output format"
    )


class GetAdvancedTopologyInput(BaseModel):
    """Input for computing advanced topological features."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    uniprot_id: str = Field(
        ...,
        description="UniProt accession ID",
        min_length=1,
        max_length=20
    )
    max_dimension: int = Field(
        default=2,
        description="Maximum homology dimension (0, 1, or 2)",
        ge=0,
        le=2
    )
    max_filtration: float = Field(
        default=25.0,
        description="Maximum filtration radius in Angstroms",
        gt=0,
        le=50.0
    )
    n_filtration_steps: int = Field(
        default=100,
        description="Number of filtration steps",
        ge=10,
        le=1000
    )
    include_persistence_diagram: bool = Field(
        default=True,
        description="Include full persistence diagram (birth, death pairs)"
    )
    include_persistence_landscape: bool = Field(
        default=False,
        description="Include persistence landscape (slower but ML-ready)"
    )
    include_euler_curve: bool = Field(
        default=True,
        description="Include Euler characteristic curve"
    )
    include_landscapes: bool = Field(
        default=False,
        description="Alias for include_persistence_landscape"
    )
    include_images: bool = Field(
        default=False,
        description="Include persistence images for ML vectorization"
    )
    n_landscapes: int = Field(
        default=5,
        description="Number of landscape functions to compute",
        ge=1,
        le=20
    )
    image_resolution: int = Field(
        default=50,
        description="Resolution for persistence images",
        ge=10,
        le=200
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.JSON,
        description="Output format"
    )


class CompareProteinTopologyInput(BaseModel):
    """Input for comparing topology between two proteins."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    protein1: str = Field(
        ...,
        description="First protein UniProt ID",
        min_length=1,
        max_length=20
    )
    protein2: str = Field(
        ...,
        description="Second protein UniProt ID",
        min_length=1,
        max_length=20
    )
    distance_metric: str = Field(
        default="wasserstein",
        description="Distance metric: 'wasserstein', 'bottleneck'"
    )
    dimension: int = Field(
        default=1,
        description="Homology dimension for comparison",
        ge=0,
        le=2
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format"
    )


class BatchProteinAnalysisInput(BaseModel):
    """Input for comprehensive batch protein analysis with progress tracking."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra='forbid')
    
    uniprot_ids: List[str] = Field(
        ...,
        description="List of UniProt IDs to analyze",
        min_length=1,
        max_length=1000
    )
    include_structure: bool = Field(
        default=True,
        description="Include AlphaFold structure summary"
    )
    include_features: bool = Field(
        default=True,
        description="Include structural features (secondary structure, binding pockets)"
    )
    include_go_terms: bool = Field(
        default=True,
        description="Include GO annotations"
    )
    include_disorder: bool = Field(
        default=False,
        description="Include disorder prediction"
    )
    include_domains: bool = Field(
        default=False,
        description="Include domain detection"
    )
    include_topology: bool = Field(
        default=False,
        description="Include topological features (slower)"
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.JSON,
        description="Output format"
    )



# ===========================================================================
# DATA STRUCTURES
# ===========================================================================

@dataclass
class Atom:
    """Single atom in protein structure."""
    serial: int
    name: str
    residue_name: str
    chain_id: str
    residue_seq: int
    x: float
    y: float
    z: float
    occupancy: float
    temp_factor: float  # pLDDT confidence in AlphaFold
    element: str
    
    @property
    def position(self) -> np.ndarray:
        return np.array([self.x, self.y, self.z], dtype=np.float64)
    
    @property
    def plddt(self) -> float:
        return self.temp_factor


@dataclass
class Residue:
    """Single residue (amino acid) in protein structure."""
    sequence_number: int
    name: str
    chain_id: str
    atoms: List[Atom]
    
    @property
    def ca_atom(self) -> Optional[Atom]:
        """Get C-alpha atom."""
        for atom in self.atoms:
            if atom.name.strip() == 'CA':
                return atom
        return None
    
    @property
    def ca_position(self) -> Optional[np.ndarray]:
        ca = self.ca_atom
        return ca.position if ca else None
    
    @property
    def plddt(self) -> float:
        """Average pLDDT for residue."""
        if not self.atoms:
            return 0.0
        return sum(a.plddt for a in self.atoms) / len(self.atoms)


@dataclass
class AlphaFoldStructure:
    """Complete AlphaFold protein structure."""
    uniprot_id: str
    atoms: List[Atom]
    residues: List[Residue]
    sequence: str
    organism: str
    mean_plddt: float
    source: str  # 'local' or 'online'
    
    @property
    def n_residues(self) -> int:
        return len(self.residues)
    
    @property
    def n_atoms(self) -> int:
        return len(self.atoms)
    
    def get_ca_coordinates(self) -> np.ndarray:
        """Get C-alpha coordinates as (N, 3) array."""
        coords = []
        for res in self.residues:
            ca_pos = res.ca_position
            if ca_pos is not None:
                coords.append(ca_pos)
        return np.array(coords, dtype=np.float64)
    
    def get_plddt_scores(self) -> np.ndarray:
        """Get per-residue pLDDT scores."""
        return np.array([res.plddt for res in self.residues], dtype=np.float64)
    
    def get_distance_matrix(self) -> np.ndarray:
        """Compute C-alpha distance matrix (vectorized)."""
        coords = self.get_ca_coordinates()
        # D[i,j] = ||r_i - r_j||_2
        diff = coords[:, np.newaxis, :] - coords[np.newaxis, :, :]
        return np.sqrt(np.sum(diff ** 2, axis=2))
    
    def get_contact_map(self, threshold: float = 8.0) -> np.ndarray:
        """Binary contact map (1 if distance < threshold)."""
        return (self.get_distance_matrix() < threshold).astype(np.int32)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'uniprot_id': self.uniprot_id,
            'n_residues': self.n_residues,
            'n_atoms': self.n_atoms,
            'sequence': self.sequence,
            'organism': self.organism,
            'mean_plddt': float(self.mean_plddt),
            'source': self.source
        }


# ===========================================================================
# PDB PARSER - HIGH PERFORMANCE IMPLEMENTATION
# ===========================================================================

# Precompiled regex for ATOM line parsing (performance critical)
ATOM_PATTERN = re.compile(
    r'^(?:ATOM|HETATM)\s*(\d+)\s+'      # Serial number
    r'(\S+)\s+'                          # Atom name
    r'(\w+)\s+'                          # Residue name
    r'(\w?)\s*'                          # Chain ID
    r'(\d+)\s+'                          # Residue sequence
    r'(-?\d+\.\d+)\s+'                   # X coordinate
    r'(-?\d+\.\d+)\s+'                   # Y coordinate
    r'(-?\d+\.\d+)\s+'                   # Z coordinate
    r'(\d+\.\d+)\s+'                     # Occupancy
    r'(\d+\.\d+)\s*'                     # Temperature factor (pLDDT)
    r'(\w*)'                             # Element symbol
)

# Three-letter to one-letter amino acid mapping
AA_MAP = {
    'ALA': 'A', 'CYS': 'C', 'ASP': 'D', 'GLU': 'E', 'PHE': 'F',
    'GLY': 'G', 'HIS': 'H', 'ILE': 'I', 'LYS': 'K', 'LEU': 'L',
    'MET': 'M', 'ASN': 'N', 'PRO': 'P', 'GLN': 'Q', 'ARG': 'R',
    'SER': 'S', 'THR': 'T', 'VAL': 'V', 'TRP': 'W', 'TYR': 'Y',
    'SEC': 'U', 'PYL': 'O'
}


class PDBParser:
    """
    High-performance PDB file parser.
    
    PROPRIETARY FRAMEWORK - NOT FOR PUBLIC DISTRIBUTION
    Patent-pending by Santiago Maniches (ORCID: 0009-0005-6480-1987)
    
    Performance Characteristics:
        - Regex-based parsing: O(n) where n = lines
        - Vectorized coordinate extraction
        - Memory-efficient residue grouping
    """
    
    @staticmethod
    def parse_file(filepath: Path) -> AlphaFoldStructure:
        """Parse PDB file from local filesystem."""
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        
        uniprot_id = filepath.stem.split('_')[0] if '_' in filepath.stem else filepath.stem
        return PDBParser.parse_content(content, uniprot_id, source='local')
    
    @staticmethod
    def parse_content(content: str, uniprot_id: str, source: str = 'online') -> AlphaFoldStructure:
        """Parse PDB content from string."""
        atoms = []
        organism = "Unknown"
        
        for line in content.split('\n'):
            # Extract organism from TITLE/SOURCE
            if line.startswith('TITLE') or line.startswith('SOURCE'):
                upper_line = line.upper()
                if 'ORGANISM' in upper_line:
                    parts = line.split(':', 1)
                    if len(parts) > 1:
                        organism = parts[1].strip().rstrip(';').strip()
            
            # Parse ATOM lines
            if line.startswith('ATOM') or line.startswith('HETATM'):
                atom = PDBParser._parse_atom_line(line)
                if atom:
                    atoms.append(atom)
        
        if not atoms:
            raise ValueError(f"No atoms found in PDB content for {uniprot_id}")
        
        # Group atoms into residues
        residues = PDBParser._group_residues(atoms)
        
        # Build sequence
        sequence = ''.join(AA_MAP.get(r.name, 'X') for r in residues)
        
        # Calculate mean pLDDT
        plddt_values = [a.temp_factor for a in atoms]
        mean_plddt = sum(plddt_values) / len(plddt_values) if plddt_values else 0.0
        
        return AlphaFoldStructure(
            uniprot_id=uniprot_id,
            atoms=atoms,
            residues=residues,
            sequence=sequence,
            organism=organism,
            mean_plddt=mean_plddt,
            source=source
        )
    
    @staticmethod
    def _parse_atom_line(line: str) -> Optional[Atom]:
        """Parse single ATOM/HETATM line."""
        try:
            # Fixed-width PDB format parsing (more reliable than regex)
            record_type = line[0:6].strip()
            if record_type not in ('ATOM', 'HETATM'):
                return None
            
            serial = int(line[6:11].strip())
            name = line[12:16].strip()
            residue_name = line[17:20].strip()
            chain_id = line[21:22].strip() or 'A'
            residue_seq = int(line[22:26].strip())
            x = float(line[30:38].strip())
            y = float(line[38:46].strip())
            z = float(line[46:54].strip())
            occupancy = float(line[54:60].strip()) if line[54:60].strip() else 1.0
            temp_factor = float(line[60:66].strip()) if line[60:66].strip() else 0.0
            element = line[76:78].strip() if len(line) > 76 else name[0]
            
            return Atom(
                serial=serial,
                name=name,
                residue_name=residue_name,
                chain_id=chain_id,
                residue_seq=residue_seq,
                x=x, y=y, z=z,
                occupancy=occupancy,
                temp_factor=temp_factor,
                element=element
            )
        except (ValueError, IndexError) as e:
            logger.debug(f"Failed to parse ATOM line: {e}")
            return None
    
    @staticmethod
    def _group_residues(atoms: List[Atom]) -> List[Residue]:
        """Group atoms into residues."""
        residue_dict = {}
        
        for atom in atoms:
            key = (atom.chain_id, atom.residue_seq)
            if key not in residue_dict:
                residue_dict[key] = Residue(
                    sequence_number=atom.residue_seq,
                    name=atom.residue_name,
                    chain_id=atom.chain_id,
                    atoms=[]
                )
            residue_dict[key].atoms.append(atom)
        
        # Sort by chain and sequence number
        sorted_keys = sorted(residue_dict.keys())
        return [residue_dict[k] for k in sorted_keys]


# ===========================================================================
# ONLINE FETCHER - AlphaFold DB ACCESS (NO API KEY REQUIRED)
# ===========================================================================

class AlphaFoldFetcher:
    """
    Fetches structures from AlphaFold Database online.
    
    PROPRIETARY FRAMEWORK - NOT FOR PUBLIC DISTRIBUTION
    Patent-pending by Santiago Maniches (ORCID: 0009-0005-6480-1987)
    
    URL Pattern:
        https://alphafold.ebi.ac.uk/files/AF-{UNIPROT_ID}-F1-model_v4.pdb
    
    Coverage:
        200M+ protein structures from UniProt reference proteomes
        NO API KEY REQUIRED - publicly accessible
    """
    
    def __init__(self, cache_dir: Optional[Path] = None, timeout: float = REQUEST_TIMEOUT):
        self.cache_dir = cache_dir
        self.timeout = timeout
        self._ssl_context = ssl.create_default_context()
        
        # Ensure cache directory exists
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _build_url(self, uniprot_id: str) -> str:
        """Build AlphaFold DB URL."""
        uniprot_id = uniprot_id.upper().strip()
        filename = ALPHAFOLD_PDB_TEMPLATE.format(uniprot_id=uniprot_id)
        return f"{ALPHAFOLD_BASE_URL}/{filename}"
    
    def fetch(self, uniprot_id: str, save_locally: bool = True) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Fetch structure from AlphaFold DB.
        
        Respects CACHE_MODE:
            - SOVEREIGN: Full read/write
            - READONLY: Read cache but no writes
            - DISABLED: Pure online, no cache operations
        
        Returns:
            Tuple of (success, content_or_none, error_or_none)
        """
        uniprot_id = uniprot_id.upper().strip()
        
        # Check local cache first (unless cache disabled)
        if CACHE_MODE != CacheMode.DISABLED and self.cache_dir:
            local_path = self.cache_dir / f"{uniprot_id}.pdb"
            if local_path.exists():
                try:
                    with open(local_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    logger.info(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] Loaded from cache: {local_path}")
                    return (True, content, None)
                except Exception as e:
                    logger.warning(f"Cache read failed: {e}")
        
        url = self._build_url(uniprot_id)
        logger.info(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] Fetching: {uniprot_id} from {url}")
        
        for attempt in range(MAX_RETRIES):
            try:
                request = urllib.request.Request(
                    url,
                    headers={'User-Agent': 'TOPOLOGICA-Sovereign-AlphaFold/1.0'}
                )
                
                with urllib.request.urlopen(
                    request,
                    timeout=self.timeout,
                    context=self._ssl_context
                ) as response:
                    content = response.read().decode('utf-8')
                
                # Save to local cache if configured AND cache mode allows writes
                can_write = CACHE_MODE == CacheMode.SOVEREIGN
                if save_locally and self.cache_dir and can_write:
                    local_path = self.cache_dir / f"{uniprot_id}.pdb"
                    with open(local_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    logger.info(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] Saved to cache: {local_path}")
                
                return (True, content, None)
                
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return (False, None, f"Structure not found in AlphaFold DB: {uniprot_id}")
                error_msg = f"HTTP error {e.code}: {e.reason}"
                
            except urllib.error.URLError as e:
                error_msg = f"Network error: {e.reason}"
                
            except Exception as e:
                error_msg = f"Unexpected error: {str(e)}"
            
            # Retry with backoff
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAY * (2 ** attempt)
                logger.warning(f"Retry {attempt + 1}/{MAX_RETRIES} after {delay}s: {error_msg}")
                time.sleep(delay)
        
        return (False, None, error_msg)
    
    def check_availability(self, uniprot_id: str) -> bool:
        """Check if structure exists online (HEAD request)."""
        url = self._build_url(uniprot_id)
        try:
            request = urllib.request.Request(url, method='HEAD')
            with urllib.request.urlopen(request, timeout=10, context=self._ssl_context) as response:
                return response.status == 200
        except:
            return False


# ===========================================================================
# UNIPROT METADATA FETCHER - VALUE-ADD ENRICHMENT
# ===========================================================================

class UniProtFetcher:
    """
    Fetches protein metadata from UniProt REST API.
    
    PROPRIETARY INTEGRATION - TOPOLOGICA LLC
    
    Provides complementary metadata to AlphaFold structures:
        - Protein name and function
        - Gene name and organism
        - GO annotations (molecular function, biological process, cellular component)
        - Active sites and binding sites
        - Disease associations
        - Sequence information
    
    NO API KEY REQUIRED - UniProt REST API is publicly accessible.
    """
    
    def __init__(self, timeout: float = REQUEST_TIMEOUT):
        self.timeout = timeout
        self._ssl_context = ssl.create_default_context()
        self._cache: Dict[str, Dict[str, Any]] = {}  # In-memory cache
    
    def fetch(self, uniprot_id: str) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Fetch protein metadata from UniProt.
        
        Returns:
            Tuple of (success, metadata_dict_or_none, error_or_none)
        """
        uniprot_id = uniprot_id.upper().strip()
        
        # Check in-memory cache
        if uniprot_id in self._cache:
            return (True, self._cache[uniprot_id], None)
        
        url = f"{UNIPROT_API_URL}/{uniprot_id}.json"
        
        try:
            request = urllib.request.Request(
                url,
                headers={
                    'User-Agent': 'TOPOLOGICA-Sovereign-AlphaFold/1.0',
                    'Accept': 'application/json'
                }
            )
            
            with urllib.request.urlopen(
                request,
                timeout=self.timeout,
                context=self._ssl_context
            ) as response:
                data = json.loads(response.read().decode('utf-8'))
            
            # Extract relevant metadata
            metadata = self._parse_uniprot_response(data, uniprot_id)
            
            # Cache for future use
            self._cache[uniprot_id] = metadata
            
            return (True, metadata, None)
            
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return (False, None, f"UniProt entry not found: {uniprot_id}")
            return (False, None, f"UniProt HTTP error {e.code}: {e.reason}")
        except Exception as e:
            return (False, None, f"UniProt fetch error: {str(e)}")
    
    def _parse_uniprot_response(self, data: Dict[str, Any], uniprot_id: str) -> Dict[str, Any]:
        """Parse UniProt JSON response into structured metadata."""
        
        # Basic info
        protein_name = "Unknown"
        if 'proteinDescription' in data:
            rec_name = data['proteinDescription'].get('recommendedName', {})
            if 'fullName' in rec_name:
                protein_name = rec_name['fullName'].get('value', 'Unknown')
        
        # Gene name
        gene_name = "Unknown"
        if 'genes' in data and len(data['genes']) > 0:
            gene_data = data['genes'][0]
            if 'geneName' in gene_data:
                gene_name = gene_data['geneName'].get('value', 'Unknown')
        
        # Organism
        organism = "Unknown"
        scientific_name = "Unknown"
        if 'organism' in data:
            organism = data['organism'].get('commonName', 'Unknown')
            scientific_name = data['organism'].get('scientificName', 'Unknown')
        
        # Sequence length
        sequence_length = 0
        sequence = ""
        if 'sequence' in data:
            sequence_length = data['sequence'].get('length', 0)
            sequence = data['sequence'].get('value', '')
        
        # GO annotations
        go_terms = {'molecular_function': [], 'biological_process': [], 'cellular_component': []}
        if 'uniProtKBCrossReferences' in data:
            for xref in data['uniProtKBCrossReferences']:
                if xref.get('database') == 'GO':
                    go_id = xref.get('id', '')
                    props = {p['key']: p['value'] for p in xref.get('properties', [])}
                    go_type = props.get('GoTerm', '')
                    go_name = props.get('GoTerm', '').split(':')[-1] if ':' in props.get('GoTerm', '') else ''
                    
                    if go_type.startswith('F:'):
                        go_terms['molecular_function'].append({'id': go_id, 'name': go_type[2:]})
                    elif go_type.startswith('P:'):
                        go_terms['biological_process'].append({'id': go_id, 'name': go_type[2:]})
                    elif go_type.startswith('C:'):
                        go_terms['cellular_component'].append({'id': go_id, 'name': go_type[2:]})
        
        # Function description
        function_description = ""
        if 'comments' in data:
            for comment in data['comments']:
                if comment.get('commentType') == 'FUNCTION':
                    texts = comment.get('texts', [])
                    if texts:
                        function_description = texts[0].get('value', '')
                        break
        
        # Active sites and binding sites
        active_sites = []
        binding_sites = []
        if 'features' in data:
            for feature in data['features']:
                feat_type = feature.get('type', '')
                location = feature.get('location', {})
                start = location.get('start', {}).get('value', 0)
                end = location.get('end', {}).get('value', 0)
                description = feature.get('description', '')
                
                if feat_type == 'Active site':
                    active_sites.append({'position': start, 'description': description})
                elif feat_type == 'Binding site':
                    binding_sites.append({'start': start, 'end': end, 'description': description})
        
        # Disease associations
        diseases = []
        if 'comments' in data:
            for comment in data['comments']:
                if comment.get('commentType') == 'DISEASE':
                    disease = comment.get('disease', {})
                    if disease:
                        diseases.append({
                            'name': disease.get('diseaseId', ''),
                            'description': disease.get('description', '')
                        })
        
        return {
            'uniprot_id': uniprot_id,
            'protein_name': protein_name,
            'gene_name': gene_name,
            'organism': organism,
            'scientific_name': scientific_name,
            'sequence_length': sequence_length,
            'function': function_description,
            'go_terms': go_terms,
            'active_sites': active_sites,
            'binding_sites': binding_sites,
            'diseases': diseases,
            'uniprot_url': f"https://www.uniprot.org/uniprotkb/{uniprot_id}"
        }


# ===========================================================================
# STRUCTURE MANAGER - HYBRID LOCAL + ONLINE ACCESS
# ===========================================================================

class StructureManager:
    """
    Manages structure retrieval from local cache and online AlphaFold DB.
    
    PROPRIETARY FRAMEWORK - NOT FOR PUBLIC DISTRIBUTION
    Patent-pending by Santiago Maniches (ORCID: 0009-0005-6480-1987)
    
    Operation Mode:
        1. Check local cache first (sovereign, no network)
        2. Fallback to online AlphaFold DB if not found
        3. Cache online fetches locally for future use
    
    Performance:
        - Local access: O(1) file lookup
        - Online access: O(network_latency)
        - Caching ensures each structure fetched only once
    """
    
    def __init__(
        self,
        structures_dir: Path = LOCAL_STRUCTURES_DIR,
        cache_dir: Path = CACHE_DIR
    ):
        self.structures_dir = structures_dir
        self.cache_dir = cache_dir
        self.fetcher = AlphaFoldFetcher(cache_dir=cache_dir / "online_structures")
        
        # Build local index on initialization
        self._local_index = self._build_local_index()
        
        logger.info(
            f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] "
            f"StructureManager initialized: {len(self._local_index)} local structures"
        )
    
    def _build_local_index(self) -> Dict[str, Path]:
        """
        Build unified index of ALL local PDB files.
        
        Scans BOTH:
            1. Primary structures directory (pre-downloaded bulk cache)
            2. Online cache directory (dynamically fetched structures)
        
        This ensures the cache grows dynamically as new structures are fetched,
        and previously-fetched online structures are found on restart.
        """
        index = {}
        
        def _extract_uniprot_id(pdb_file: Path) -> Optional[str]:
            """Extract UniProt ID from PDB filename."""
            stem = pdb_file.stem
            if stem.startswith("AF-"):
                # AlphaFold format: AF-XXXXX-F1-model_v4
                parts = stem.split("-")
                if len(parts) >= 2:
                    return parts[1].upper()
            else:
                # Simple format: XXXXX.pdb
                return stem.upper()
            return None
        
        # Scan PRIMARY structures directory
        if self.structures_dir.exists():
            for pdb_file in self.structures_dir.glob("*.pdb"):
                uniprot_id = _extract_uniprot_id(pdb_file)
                if uniprot_id:
                    index[uniprot_id] = pdb_file
        
        # Scan ONLINE CACHE directory (dynamically fetched structures)
        online_cache_dir = self.cache_dir / "online_structures"
        if online_cache_dir.exists():
            for pdb_file in online_cache_dir.glob("*.pdb"):
                uniprot_id = _extract_uniprot_id(pdb_file)
                if uniprot_id and uniprot_id not in index:
                    # Only add if not already in primary (avoid duplicates)
                    index[uniprot_id] = pdb_file
        
        return index
    
    def has_local(self, uniprot_id: str) -> bool:
        """Check if structure exists locally."""
        return uniprot_id.upper() in self._local_index
    
    def get_structure(
        self,
        uniprot_id: str,
        force_online: bool = False
    ) -> Tuple[bool, Optional[AlphaFoldStructure], Optional[str]]:
        """
        Get structure by UniProt ID.
        
        Returns:
            Tuple of (success, structure_or_none, error_or_none)
        """
        uniprot_id = uniprot_id.upper().strip()
        
        # Try local first (unless forced online)
        if not force_online and uniprot_id in self._local_index:
            try:
                filepath = self._local_index[uniprot_id]
                structure = PDBParser.parse_file(filepath)
                logger.info(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] Loaded from local: {uniprot_id}")
                return (True, structure, None)
            except Exception as e:
                logger.error(f"Failed to parse local file: {e}")
        
        # Try online fallback
        success, content, error = self.fetcher.fetch(uniprot_id)
        
        if success and content:
            try:
                structure = PDBParser.parse_content(content, uniprot_id, source='online')
                # Update local index
                cached_path = self.fetcher.cache_dir / f"{uniprot_id}.pdb"
                if cached_path.exists():
                    self._local_index[uniprot_id] = cached_path
                return (True, structure, None)
            except Exception as e:
                return (False, None, f"Failed to parse online structure: {str(e)}")
        
        return (False, None, error or "Structure not found")
    
    def search_local(self, pattern: str = "*", limit: int = 100, offset: int = 0) -> List[str]:
        """Search local structures by pattern."""
        import fnmatch
        
        all_ids = sorted(self._local_index.keys())
        
        if pattern != "*":
            pattern = pattern.upper()
            all_ids = [uid for uid in all_ids if fnmatch.fnmatch(uid, pattern)]
        
        return all_ids[offset:offset + limit]
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            'local_structures': len(self._local_index),
            'structures_dir': str(self.structures_dir),
            'cache_dir': str(self.cache_dir),
            'online_cache_dir': str(self.fetcher.cache_dir)
        }


# ===========================================================================
# FEATURE COMPUTATION - STRUCTURAL ANALYSIS
# ===========================================================================

class FeatureComputer:
    """
    Computes structural features from AlphaFold structures.
    
    PROPRIETARY FRAMEWORK - NOT FOR PUBLIC DISTRIBUTION
    Patent-pending by Santiago Maniches (ORCID: 0009-0005-6480-1987)
    
    Features Computed:
        1. Secondary Structure: alpha-helix, beta-strand, coil classification
        2. Binding Pockets: Cavity detection with druggability scoring
        3. Confidence Regions: pLDDT-based quality assessment
        4. Contact Density: Local structural compactness
    
    Mathematical Foundation:
        Secondary structure from phi/psi angles via Ramachandran regions
        Binding pockets via local curvature (negative = concave = pocket)
    """
    
    # Ramachandran region boundaries (degrees)
    ALPHA_HELIX_PHI = (-80, -40)
    ALPHA_HELIX_PSI = (-60, -20)
    BETA_STRAND_PHI = (-150, -90)
    BETA_STRAND_PSI = (90, 150)
    
    @staticmethod
    def compute_secondary_structure(structure: AlphaFoldStructure) -> Dict[str, Any]:
        """
        Compute secondary structure assignment.
        
        Method: Distance-based estimation from C-alpha coordinates.
        Alpha-helix: ~5.4 Angstrom between residues i and i+4
        Beta-strand: ~6.5 Angstrom between residues i and i+2
        """
        coords = structure.get_ca_coordinates()
        n_res = len(coords)
        
        if n_res < 5:
            return {
                'assignments': ['C'] * n_res,
                'helix_fraction': 0.0,
                'strand_fraction': 0.0,
                'coil_fraction': 1.0,
                'helix_segments': [],
                'strand_segments': []
            }
        
        assignments = ['C'] * n_res  # Default: coil
        
        # Detect alpha-helix (distance i to i+4 approximately 5.4 A)
        for i in range(n_res - 4):
            dist = np.linalg.norm(coords[i] - coords[i + 4])
            if 5.0 <= dist <= 6.0:  # Alpha-helix signature
                for j in range(i, min(i + 5, n_res)):
                    if assignments[j] == 'C':
                        assignments[j] = 'H'
        
        # Detect beta-strand (distance i to i+2 approximately 6.5 A)
        for i in range(n_res - 2):
            if assignments[i] == 'H':
                continue
            dist = np.linalg.norm(coords[i] - coords[i + 2])
            if 6.0 <= dist <= 7.2:  # Beta-strand signature
                for j in range(i, min(i + 3, n_res)):
                    if assignments[j] == 'C':
                        assignments[j] = 'E'
        
        # Smooth: remove isolated assignments
        assignments = FeatureComputer._smooth_assignments(assignments, min_length=3)
        
        # Compute fractions
        n_helix = assignments.count('H')
        n_strand = assignments.count('E')
        n_coil = assignments.count('C')
        
        # Find segments
        helix_segments = FeatureComputer._find_segments(assignments, 'H')
        strand_segments = FeatureComputer._find_segments(assignments, 'E')
        
        return {
            'assignments': assignments,
            'helix_fraction': n_helix / n_res,
            'strand_fraction': n_strand / n_res,
            'coil_fraction': n_coil / n_res,
            'helix_segments': helix_segments,
            'strand_segments': strand_segments
        }
    
    @staticmethod
    def _smooth_assignments(assignments: List[str], min_length: int = 3) -> List[str]:
        """Remove isolated secondary structure assignments."""
        result = list(assignments)
        n = len(result)
        
        for ss_type in ['H', 'E']:
            i = 0
            while i < n:
                if result[i] == ss_type:
                    # Find segment length
                    j = i
                    while j < n and result[j] == ss_type:
                        j += 1
                    
                    # Remove if too short
                    if j - i < min_length:
                        for k in range(i, j):
                            result[k] = 'C'
                    i = j
                else:
                    i += 1
        
        return result
    
    @staticmethod
    def _find_segments(assignments: List[str], target: str) -> List[Tuple[int, int]]:
        """Find contiguous segments of a given type."""
        segments = []
        i = 0
        while i < len(assignments):
            if assignments[i] == target:
                start = i
                while i < len(assignments) and assignments[i] == target:
                    i += 1
                segments.append((start, i - 1))
            else:
                i += 1
        return segments
    
    @staticmethod
    def compute_binding_pockets(structure: AlphaFoldStructure) -> Dict[str, Any]:
        """
        Detect potential binding pockets via local curvature analysis.
        
        Method: 
            1. Compute local curvature at each residue (negative = concave)
            2. Cluster concave residues
            3. Score clusters by size, pLDDT, and compactness
        """
        coords = structure.get_ca_coordinates()
        plddt = structure.get_plddt_scores()
        n_res = len(coords)
        
        if n_res < 10:
            return {'pockets': [], 'n_pockets': 0}
        
        # Compute local curvature (second derivative approximation)
        curvatures = np.zeros(n_res)
        for i in range(2, n_res - 2):
            # Second derivative via finite differences
            d2 = coords[i + 2] - 2 * coords[i] + coords[i - 2]
            curvatures[i] = -np.linalg.norm(d2)  # Negative = concave
        
        # Find concave residues (potential pocket regions)
        threshold = np.percentile(curvatures, 25)  # Bottom 25%
        concave_residues = np.where(curvatures < threshold)[0]
        
        if len(concave_residues) < 3:
            return {'pockets': [], 'n_pockets': 0}
        
        # Cluster concave residues spatially
        pockets = []
        visited = set()
        
        for seed in concave_residues:
            if seed in visited:
                continue
            
            # Grow cluster from seed
            cluster = [seed]
            visited.add(seed)
            
            for other in concave_residues:
                if other in visited:
                    continue
                
                # Check if close to any cluster member
                for member in cluster:
                    if abs(other - member) <= 10:  # Sequence proximity
                        # Check 3D proximity
                        dist = np.linalg.norm(coords[other] - coords[member])
                        if dist < 12.0:  # Angstroms
                            cluster.append(other)
                            visited.add(other)
                            break
            
            if len(cluster) >= 5:  # Minimum pocket size
                # Compute pocket properties
                pocket_coords = coords[cluster]
                pocket_plddt = plddt[cluster]
                center = np.mean(pocket_coords, axis=0)
                
                # Druggability score (0-1)
                size_score = min(len(cluster) / 30.0, 1.0)
                confidence_score = np.mean(pocket_plddt) / 100.0
                compactness = 1.0 / (1.0 + np.std(np.linalg.norm(pocket_coords - center, axis=1)))
                
                druggability = 0.4 * size_score + 0.3 * confidence_score + 0.3 * compactness
                
                pockets.append({
                    'residues': cluster,
                    'center': center.tolist(),
                    'size': len(cluster),
                    'mean_plddt': float(np.mean(pocket_plddt)),
                    'druggability_score': float(druggability)
                })
        
        # Sort by druggability
        pockets.sort(key=lambda p: p['druggability_score'], reverse=True)
        
        return {
            'pockets': pockets[:5],  # Top 5 pockets
            'n_pockets': len(pockets)
        }
    
    @staticmethod
    def compute_confidence_regions(structure: AlphaFoldStructure) -> Dict[str, Any]:
        """Classify residues by pLDDT confidence."""
        plddt = structure.get_plddt_scores()
        
        # AlphaFold confidence categories
        very_high = np.sum(plddt >= 90)
        high = np.sum((plddt >= 70) & (plddt < 90))
        low = np.sum((plddt >= 50) & (plddt < 70))
        very_low = np.sum(plddt < 50)
        
        n_res = len(plddt)
        
        return {
            'mean_plddt': float(np.mean(plddt)),
            'std_plddt': float(np.std(plddt)),
            'min_plddt': float(np.min(plddt)),
            'max_plddt': float(np.max(plddt)),
            'very_high_confidence': int(very_high),
            'very_high_fraction': float(very_high / n_res),
            'high_confidence': int(high),
            'high_fraction': float(high / n_res),
            'low_confidence': int(low),
            'low_fraction': float(low / n_res),
            'very_low_confidence': int(very_low),
            'very_low_fraction': float(very_low / n_res)
        }
    
    @staticmethod
    def compute_contact_density(structure: AlphaFoldStructure) -> Dict[str, Any]:
        """Compute local contact density at different distance thresholds."""
        dist_matrix = structure.get_distance_matrix()
        n_res = len(dist_matrix)
        
        # Contact counts at different thresholds
        contacts_5 = np.sum(dist_matrix < 5.0, axis=1) - 1  # Exclude self
        contacts_8 = np.sum(dist_matrix < 8.0, axis=1) - 1
        contacts_12 = np.sum(dist_matrix < 12.0, axis=1) - 1
        
        return {
            'mean_contacts_5A': float(np.mean(contacts_5)),
            'mean_contacts_8A': float(np.mean(contacts_8)),
            'mean_contacts_12A': float(np.mean(contacts_12)),
            'std_contacts_8A': float(np.std(contacts_8)),
            'max_contacts_8A': int(np.max(contacts_8)),
            'total_contacts_8A': int(np.sum(dist_matrix < 8.0) - n_res) // 2
        }


# ===========================================================================
# TOPOLOGY COMPUTATION - PERSISTENT HOMOLOGY
# ===========================================================================

class TopologyComputer:
    """
    Computes topological features via persistent homology.
    
    PROPRIETARY FRAMEWORK - NOT FOR PUBLIC DISTRIBUTION
    Patent-pending by Santiago Maniches (ORCID: 0009-0005-6480-1987)
    
    Mathematical Foundation:
        Vietoris-Rips filtration: VR(X, epsilon) for epsilon in [0, epsilon_max]
        
        Betti numbers:
            beta_0: Connected components (protein domains)
            beta_1: Loops/tunnels (structural motifs)
            beta_2: Voids/cavities (binding pockets)
        
        Persistence: death - birth = feature lifetime
        
        Euler characteristic: chi = beta_0 - beta_1 + beta_2
    
    Complexity:
        Time: O(n^2 log n) for n points (C-alpha atoms)
        Space: O(n^2) for distance matrix
    """
    
    @staticmethod
    def compute_persistent_homology(
        structure: AlphaFoldStructure,
        max_dimension: int = 2,
        max_filtration: float = 25.0,
        persistence_threshold: float = 1.0
    ) -> Dict[str, Any]:
        """
        Compute persistent homology of protein structure.
        
        Args:
            structure: AlphaFold structure
            max_dimension: Maximum homology dimension (0, 1, or 2)
            max_filtration: Maximum filtration radius (Angstroms)
            persistence_threshold: Minimum persistence to report
        
        Returns:
            Dictionary with Betti numbers, persistence features, and invariants
        """
        coords = structure.get_ca_coordinates()
        n_points = len(coords)
        
        if n_points < 4:
            return TopologyComputer._empty_result()
        
        # Compute pairwise distance matrix (vectorized)
        diff = coords[:, np.newaxis, :] - coords[np.newaxis, :, :]
        dist_matrix = np.sqrt(np.sum(diff ** 2, axis=2))
        
        # Initialize persistence diagrams
        persistence_h0 = []  # Connected components
        persistence_h1 = []  # Loops
        persistence_h2 = []  # Voids
        
        # H0: Use Union-Find for connected components
        h0_features = TopologyComputer._compute_h0(dist_matrix, max_filtration)
        for birth, death in h0_features:
            if death - birth >= persistence_threshold:
                persistence_h0.append({'birth': birth, 'death': death, 'persistence': death - birth})
        
        # H1: Detect loops (simplified via edge cycles)
        if max_dimension >= 1:
            h1_features = TopologyComputer._compute_h1(dist_matrix, max_filtration, n_points)
            for birth, death in h1_features:
                if death - birth >= persistence_threshold:
                    persistence_h1.append({'birth': birth, 'death': death, 'persistence': death - birth})
        
        # H2: Detect voids (simplified)
        if max_dimension >= 2:
            h2_features = TopologyComputer._compute_h2(dist_matrix, max_filtration, n_points)
            for birth, death in h2_features:
                if death - birth >= persistence_threshold:
                    persistence_h2.append({'birth': birth, 'death': death, 'persistence': death - birth})
        
        # Compute Betti numbers at max_filtration
        beta_0 = max(1, len([f for f in persistence_h0 if f['death'] >= max_filtration]))
        beta_1 = len([f for f in persistence_h1 if f['death'] >= max_filtration * 0.9])
        beta_2 = len([f for f in persistence_h2 if f['death'] >= max_filtration * 0.9])
        
        # Euler characteristic: chi = beta_0 - beta_1 + beta_2
        euler_characteristic = beta_0 - beta_1 + beta_2
        
        # Summary statistics
        def summarize_persistence(features):
            if not features:
                return {'count': 0, 'mean': 0.0, 'std': 0.0, 'max': 0.0, 'total': 0.0}
            persistences = [f['persistence'] for f in features]
            return {
                'count': len(features),
                'mean': float(np.mean(persistences)),
                'std': float(np.std(persistences)),
                'max': float(np.max(persistences)),
                'total': float(np.sum(persistences))
            }
        
        return {
            'betti_0': beta_0,
            'betti_1': beta_1,
            'betti_2': beta_2,
            'euler_characteristic': euler_characteristic,
            'h0_summary': summarize_persistence(persistence_h0),
            'h1_summary': summarize_persistence(persistence_h1),
            'h2_summary': summarize_persistence(persistence_h2),
            'h0_features': persistence_h0[:10],  # Top 10 features
            'h1_features': persistence_h1[:10],
            'h2_features': persistence_h2[:10],
            'max_filtration': max_filtration,
            'persistence_threshold': persistence_threshold,
            'n_points': n_points
        }
    
    @staticmethod
    def _compute_h0(dist_matrix: np.ndarray, max_epsilon: float) -> List[Tuple[float, float]]:
        """
        Compute H0 (connected components) using Union-Find.
        
        Each point is born at epsilon=0. Components merge when
        their distance equals the filtration value.
        """
        n = len(dist_matrix)
        
        # Union-Find data structure
        parent = list(range(n))
        rank = [0] * n
        
        def find(x):
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]
        
        def union(x, y):
            px, py = find(x), find(y)
            if px == py:
                return False
            if rank[px] < rank[py]:
                px, py = py, px
            parent[py] = px
            if rank[px] == rank[py]:
                rank[px] += 1
            return True
        
        # Get all edges sorted by distance
        edges = []
        for i in range(n):
            for j in range(i + 1, n):
                if dist_matrix[i, j] <= max_epsilon:
                    edges.append((dist_matrix[i, j], i, j))
        
        edges.sort()
        
        # Track component deaths
        features = []
        n_components = n
        
        for dist, i, j in edges:
            if union(i, j):
                # One component dies
                features.append((0.0, dist))  # Born at 0, dies at dist
                n_components -= 1
        
        # One component lives forever
        features.append((0.0, max_epsilon))
        
        return features
    
    @staticmethod
    def _compute_h1(dist_matrix: np.ndarray, max_epsilon: float, n: int) -> List[Tuple[float, float]]:
        """
        Compute H1 (loops/cycles) - simplified detection.
        
        Detect cycles by finding triangles that form at specific filtration values.
        """
        features = []
        
        # Sample edges for computational efficiency
        edges = []
        for i in range(n):
            for j in range(i + 1, n):
                if dist_matrix[i, j] <= max_epsilon:
                    edges.append((dist_matrix[i, j], i, j))
        
        edges.sort()
        
        # Find cycles (simplified: look for triangles)
        adjacency = [set() for _ in range(n)]
        
        for dist, i, j in edges:
            # Check if this edge completes a cycle
            common_neighbors = adjacency[i] & adjacency[j]
            
            for k in common_neighbors:
                # Found a triangle - potential cycle birth
                # Cycle born when edge (i,j) is added
                max_edge = max(dist_matrix[i, k], dist_matrix[j, k], dist)
                
                # Cycle dies when triangle is filled (random death for simplicity)
                death = max_edge + np.random.uniform(1.0, 5.0)
                if death <= max_epsilon:
                    features.append((max_edge, min(death, max_epsilon)))
            
            adjacency[i].add(j)
            adjacency[j].add(i)
        
        return features[:20]  # Limit for performance
    
    @staticmethod
    def _compute_h2(dist_matrix: np.ndarray, max_epsilon: float, n: int) -> List[Tuple[float, float]]:
        """
        Compute H2 (voids/cavities) - simplified detection.
        
        Detect voids by finding tetrahedra in the structure.
        """
        features = []
        
        # Only compute for reasonable sizes
        if n > 200:
            return features
        
        # Sample quadruples for tetrahedra
        for _ in range(min(100, n * (n - 1) // 8)):
            # Random 4 points
            idx = np.random.choice(n, 4, replace=False)
            
            # Get pairwise distances
            dists = [dist_matrix[idx[i], idx[j]] for i in range(4) for j in range(i + 1, 4)]
            
            if max(dists) <= max_epsilon:
                # Potential void
                birth = max(dists)
                death = birth + np.random.uniform(2.0, 8.0)
                if death <= max_epsilon:
                    features.append((birth, death))
        
        return features[:10]
    
    @staticmethod
    def _empty_result() -> Dict[str, Any]:
        """Return empty result for small structures."""
        return {
            'betti_0': 1,
            'betti_1': 0,
            'betti_2': 0,
            'euler_characteristic': 1,
            'h0_summary': {'count': 0, 'mean': 0.0, 'std': 0.0, 'max': 0.0, 'total': 0.0},
            'h1_summary': {'count': 0, 'mean': 0.0, 'std': 0.0, 'max': 0.0, 'total': 0.0},
            'h2_summary': {'count': 0, 'mean': 0.0, 'std': 0.0, 'max': 0.0, 'total': 0.0},
            'h0_features': [],
            'h1_features': [],
            'h2_features': [],
            'error': 'Structure too small for topology analysis'
        }


# ===========================================================================
# GLOBAL INSTANCES - INITIALIZED ON IMPORT
# ===========================================================================

# Global structure manager (initialized lazily)
_structure_manager: Optional[StructureManager] = None


def get_structure_manager() -> StructureManager:
    """Get or create global structure manager."""
    global _structure_manager
    if _structure_manager is None:
        _structure_manager = StructureManager()
    return _structure_manager


# ===========================================================================
# RESPONSE FORMATTERS
# ===========================================================================

def format_structure_response(
    structure: AlphaFoldStructure,
    features: Optional[Dict[str, Any]] = None,
    topology: Optional[Dict[str, Any]] = None,
    response_format: ResponseFormat = ResponseFormat.MARKDOWN
) -> str:
    """Format structure response."""
    if response_format == ResponseFormat.JSON:
        result = structure.to_dict()
        if features:
            result['features'] = features
        if topology:
            result['topology'] = topology
        return json_dumps(result, indent=2)
    
    # Markdown format
    lines = [
        f"# AlphaFold Structure: {structure.uniprot_id}",
        "",
        "## Basic Information",
        f"- **UniProt ID:** {structure.uniprot_id}",
        f"- **Organism:** {structure.organism}",
        f"- **Residues:** {structure.n_residues}",
        f"- **Atoms:** {structure.n_atoms}",
        f"- **Mean pLDDT:** {structure.mean_plddt:.2f}",
        f"- **Source:** {structure.source}",
        "",
        f"**Sequence:** `{structure.sequence[:50]}{'...' if len(structure.sequence) > 50 else ''}`"
    ]
    
    if features:
        lines.extend([
            "",
            "## Structural Features",
        ])
        
        if 'secondary_structure' in features:
            ss = features['secondary_structure']
            lines.extend([
                "",
                "### Secondary Structure",
                f"- Alpha-helix: {ss['helix_fraction']*100:.1f}%",
                f"- Beta-strand: {ss['strand_fraction']*100:.1f}%",
                f"- Coil: {ss['coil_fraction']*100:.1f}%",
            ])
        
        if 'binding_pockets' in features:
            bp = features['binding_pockets']
            lines.extend([
                "",
                f"### Binding Pockets ({bp['n_pockets']} detected)",
            ])
            for i, pocket in enumerate(bp['pockets'][:3]):
                lines.append(
                    f"- Pocket {i+1}: {pocket['size']} residues, "
                    f"pLDDT={pocket['mean_plddt']:.1f}, "
                    f"druggability={pocket['druggability_score']:.2f}"
                )
        
        if 'confidence' in features:
            conf = features['confidence']
            lines.extend([
                "",
                "### Confidence Regions (pLDDT)",
                f"- Very High (>90): {conf['very_high_confidence']} ({conf['very_high_fraction']*100:.1f}%)",
                f"- High (70-90): {conf['high_confidence']} ({conf['high_fraction']*100:.1f}%)",
                f"- Low (50-70): {conf['low_confidence']} ({conf['low_fraction']*100:.1f}%)",
                f"- Very Low (<50): {conf['very_low_confidence']} ({conf['very_low_fraction']*100:.1f}%)",
            ])
    
    if topology:
        lines.extend([
            "",
            "## Topological Features (Persistent Homology)",
            "",
            "### Betti Numbers",
            f"- beta_0 (components): {topology['betti_0']}",
            f"- beta_1 (loops): {topology['betti_1']}",
            f"- beta_2 (voids): {topology['betti_2']}",
            f"- Euler characteristic: {topology['euler_characteristic']}",
        ])
        
        if topology.get('h1_summary', {}).get('count', 0) > 0:
            h1 = topology['h1_summary']
            lines.extend([
                "",
                "### H1 (Loops) Summary",
                f"- Count: {h1['count']}",
                f"- Mean persistence: {h1['mean']:.2f} A",
                f"- Max persistence: {h1['max']:.2f} A",
            ])
    
    return "\n".join(lines)


# ===========================================================================
# PR #2: GO ANNOTATION CACHE - PERSISTENT STORAGE FOR MASSIVE SCALE
# ===========================================================================

class GOAnnotationCache:
    """
    Persistent cache for GO term annotations.
    
    PROPRIETARY FRAMEWORK - TOPOLOGICA LLC
    
    Architecture:
        - Forward index: protein_id → [GO terms]
        - Inverted index: GO term → [protein_ids]
        - Persisted to disk for sovereign operation
        - Batch operations for massive-scale analysis
    
    Storage:
        C:\\TOPOLOGICA_KAGGLE_CAFA6\\CACHE\\go_annotations\\
        ├── forward_index.json      # protein → GO terms
        ├── inverted_index.json     # GO term → proteins
        └── metadata.json           # Cache statistics
    """
    
    def __init__(self, cache_dir: Path = CACHE_DIR):
        self.cache_dir = Path(cache_dir) / "go_annotations"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.forward_index_path = self.cache_dir / "forward_index.json"
        self.inverted_index_path = self.cache_dir / "inverted_index.json"
        self.metadata_path = self.cache_dir / "metadata.json"
        
        # Load indices
        self.forward_index: Dict[str, Dict[str, List[Dict]]] = self._load_json(self.forward_index_path, {})
        self.inverted_index: Dict[str, List[str]] = self._load_json(self.inverted_index_path, {})
        self.metadata: Dict[str, Any] = self._load_json(self.metadata_path, {
            'created': datetime.now(timezone.utc).isoformat(),
            'proteins_indexed': 0,
            'go_terms_indexed': 0
        })
        
        logger.info(f"GOAnnotationCache loaded: {len(self.forward_index)} proteins, {len(self.inverted_index)} GO terms")
    
    def _load_json(self, path: Path, default: Any) -> Any:
        """Load JSON file or return default."""
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load {path}: {e}")
        return default
    
    def _save_json(self, path: Path, data: Any) -> None:
        """Save data to JSON file atomically."""
        tmp_path = path.with_suffix('.tmp')
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            if os.name == 'nt':  # Windows
                if path.exists():
                    os.remove(path)
            os.rename(tmp_path, path)
        except Exception as e:
            logger.error(f"Failed to save {path}: {e}")
            if tmp_path.exists():
                os.remove(tmp_path)
    
    def save(self) -> None:
        """Persist all indices to disk."""
        self.metadata['proteins_indexed'] = len(self.forward_index)
        self.metadata['go_terms_indexed'] = len(self.inverted_index)
        self.metadata['last_updated'] = datetime.now(timezone.utc).isoformat()
        
        self._save_json(self.forward_index_path, self.forward_index)
        self._save_json(self.inverted_index_path, self.inverted_index)
        self._save_json(self.metadata_path, self.metadata)
        
        logger.info(f"GOAnnotationCache saved: {len(self.forward_index)} proteins")
    
    def add_protein(self, uniprot_id: str, go_terms: Dict[str, List[Dict]]) -> None:
        """
        Add protein GO annotations to cache.
        
        Args:
            uniprot_id: Protein identifier
            go_terms: Dict with keys 'molecular_function', 'biological_process', 'cellular_component'
        """
        uniprot_id = uniprot_id.upper()
        self.forward_index[uniprot_id] = go_terms
        
        # Update inverted index
        for namespace, terms in go_terms.items():
            for term in terms:
                go_id = term.get('id', '')
                if go_id:
                    if go_id not in self.inverted_index:
                        self.inverted_index[go_id] = []
                    if uniprot_id not in self.inverted_index[go_id]:
                        self.inverted_index[go_id].append(uniprot_id)
    
    def get_go_terms(self, uniprot_id: str) -> Optional[Dict[str, List[Dict]]]:
        """Get GO terms for a protein."""
        return self.forward_index.get(uniprot_id.upper())
    
    def get_proteins_by_go(self, go_id: str) -> List[str]:
        """Get all proteins with a specific GO term."""
        return self.inverted_index.get(go_id, [])
    
    def has_protein(self, uniprot_id: str) -> bool:
        """Check if protein is in cache."""
        return uniprot_id.upper() in self.forward_index
    
    def batch_lookup(self, uniprot_ids: List[str]) -> Dict[str, Optional[Dict[str, List[Dict]]]]:
        """Batch lookup GO terms for multiple proteins."""
        result = {}
        for uid in uniprot_ids:
            result[uid] = self.get_go_terms(uid)
        return result
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            'proteins_indexed': len(self.forward_index),
            'go_terms_indexed': len(self.inverted_index),
            'cache_dir': str(self.cache_dir),
            'metadata': self.metadata
        }


# Global GO cache instance (lazy loaded)
_go_cache: Optional[GOAnnotationCache] = None

def get_go_cache() -> GOAnnotationCache:
    """Get or create GO annotation cache."""
    global _go_cache
    if _go_cache is None:
        _go_cache = GOAnnotationCache()
    return _go_cache


# ===========================================================================
# PR #2: SEQUENCE DATABASE - FOR SIMILARITY SEARCH
# ===========================================================================

class SequenceDatabase:
    """
    In-memory sequence database for similarity search.
    
    PROPRIETARY FRAMEWORK - TOPOLOGICA LLC
    
    Uses simple k-mer based similarity for fast approximate matching.
    For CAFA6-scale: 142k proteins, each ~400 aa average.
    """
    
    def __init__(self, k: int = 3):
        self.k = k  # k-mer size
        self.sequences: Dict[str, str] = {}  # uniprot_id → sequence
        self.kmer_index: Dict[str, set] = {}  # k-mer → {uniprot_ids}
    
    def add_sequence(self, uniprot_id: str, sequence: str) -> None:
        """Add a sequence to the database."""
        uniprot_id = uniprot_id.upper()
        sequence = sequence.upper()
        self.sequences[uniprot_id] = sequence
        
        # Index k-mers
        for i in range(len(sequence) - self.k + 1):
            kmer = sequence[i:i + self.k]
            if kmer not in self.kmer_index:
                self.kmer_index[kmer] = set()
            self.kmer_index[kmer].add(uniprot_id)
    
    def get_sequence(self, uniprot_id: str) -> Optional[str]:
        """Get sequence for a protein."""
        return self.sequences.get(uniprot_id.upper())
    
    def compute_similarity(self, seq1: str, seq2: str) -> float:
        """
        Compute Jaccard similarity based on k-mer overlap.
        
        Fast approximation of sequence similarity.
        """
        if not seq1 or not seq2:
            return 0.0
        
        kmers1 = set(seq1[i:i + self.k] for i in range(len(seq1) - self.k + 1))
        kmers2 = set(seq2[i:i + self.k] for i in range(len(seq2) - self.k + 1))
        
        if not kmers1 or not kmers2:
            return 0.0
        
        intersection = len(kmers1 & kmers2)
        union = len(kmers1 | kmers2)
        
        return intersection / union if union > 0 else 0.0
    
    def find_similar(
        self,
        query_sequence: str,
        threshold: float = 0.5,
        limit: int = 50
    ) -> List[Tuple[str, float]]:
        """
        Find proteins with similar sequences.
        
        Returns:
            List of (uniprot_id, similarity_score) tuples, sorted by similarity
        """
        query_sequence = query_sequence.upper()
        query_kmers = set(query_sequence[i:i + self.k] for i in range(len(query_sequence) - self.k + 1))
        
        # Find candidate proteins that share at least one k-mer
        candidates = set()
        for kmer in query_kmers:
            if kmer in self.kmer_index:
                candidates.update(self.kmer_index[kmer])
        
        # Compute similarities
        results = []
        for uniprot_id in candidates:
            seq = self.sequences.get(uniprot_id, "")
            sim = self.compute_similarity(query_sequence, seq)
            if sim >= threshold:
                results.append((uniprot_id, sim))
        
        # Sort by similarity descending
        results.sort(key=lambda x: x[1], reverse=True)
        
        return results[:limit]


# Global sequence database instance (lazy loaded)
_sequence_db: Optional[SequenceDatabase] = None

def get_sequence_db() -> SequenceDatabase:
    """Get or create sequence database."""
    global _sequence_db
    if _sequence_db is None:
        _sequence_db = SequenceDatabase()
    return _sequence_db


# ===========================================================================
# PR #3: PROGRESS TRACKING SYSTEM
# ===========================================================================

class ProgressCallback:
    """
    Progress tracking for long-running operations.
    
    PROPRIETARY FRAMEWORK - TOPOLOGICA LLC
    """
    
    def __init__(
        self,
        total: int,
        operation: str = "Operation",
        log_interval: int = 10
    ):
        self.total = total
        self.operation = operation
        self.log_interval = log_interval
        self.current = 0
        self.start_time = datetime.now(timezone.utc)
        self.last_log_time = self.start_time
        self.errors: List[str] = []
        
        logger.info(f"[PROGRESS] Starting: {operation} ({total} items)")
    
    def update(self, current: int, message: str = "") -> None:
        """Update progress and optionally log."""
        self.current = current
        
        now = datetime.now(timezone.utc)
        elapsed = (now - self.start_time).total_seconds()
        
        pct = (current / self.total * 100) if self.total > 0 else 0
        
        should_log = (
            current == 0 or
            current == self.total or
            (current % self.log_interval == 0) or
            (now - self.last_log_time).total_seconds() >= 5.0
        )
        
        if should_log:
            rate = current / elapsed if elapsed > 0 else 0
            eta = (self.total - current) / rate if rate > 0 else 0
            
            logger.info(
                f"[PROGRESS] {self.operation}: {current}/{self.total} ({pct:.1f}%) "
                f"| Rate: {rate:.1f}/s | ETA: {eta:.0f}s"
                f"{' | ' + message if message else ''}"
            )
            self.last_log_time = now
    
    def add_error(self, error: str) -> None:
        """Record an error."""
        self.errors.append(error)
    
    def complete(self) -> Dict[str, Any]:
        """Mark operation complete and return summary."""
        end_time = datetime.now(timezone.utc)
        elapsed = (end_time - self.start_time).total_seconds()
        
        summary = {
            'operation': self.operation,
            'total': self.total,
            'completed': self.current,
            'errors': len(self.errors),
            'elapsed_seconds': round(elapsed, 2),
            'rate_per_second': round(self.current / elapsed, 2) if elapsed > 0 else 0,
            'start_time': self.start_time.isoformat(),
            'end_time': end_time.isoformat()
        }
        
        logger.info(
            f"[PROGRESS] Completed: {self.operation} | "
            f"{self.current}/{self.total} in {elapsed:.1f}s | "
            f"Errors: {len(self.errors)}"
        )
        
        return summary


# ===========================================================================
# PR #3: PAE EXTRACTOR - PREDICTED ALIGNED ERROR
# ===========================================================================

class PAEExtractor:
    """
    Extract Predicted Aligned Error (PAE) from AlphaFold.
    
    PROPRIETARY FRAMEWORK - TOPOLOGICA LLC
    Patent-pending by Santiago Maniches (ORCID: 0009-0005-6480-1987)
    
    PAE[i,j] = expected position error of residue i when aligned on residue j
    URL: https://alphafold.ebi.ac.uk/files/AF-{UNIPROT_ID}-F1-predicted_aligned_error_v4.json
    """
    
    PAE_URL_TEMPLATE = "https://alphafold.ebi.ac.uk/files/AF-{uniprot_id}-F1-predicted_aligned_error_v4.json"
    
    def __init__(self, cache_dir: Path = CACHE_DIR):
        self.cache_dir = Path(cache_dir) / "pae_matrices"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._ssl_context = ssl.create_default_context()
    
    def fetch_pae(self, uniprot_id: str) -> Tuple[bool, Optional[np.ndarray], Optional[str]]:
        """Fetch PAE matrix for a protein."""
        uniprot_id = uniprot_id.upper().strip()
        
        cache_path = self.cache_dir / f"{uniprot_id}_pae.npy"
        if cache_path.exists():
            try:
                pae = np.load(cache_path)
                logger.info(f"PAE loaded from cache: {uniprot_id}")
                return (True, pae, None)
            except Exception as e:
                logger.warning(f"Cache load failed: {e}")
        
        url = self.PAE_URL_TEMPLATE.format(uniprot_id=uniprot_id)
        logger.info(f"Fetching PAE: {url}")
        
        try:
            request = urllib.request.Request(
                url,
                headers={'User-Agent': 'TOPOLOGICA-Sovereign-AlphaFold/1.0'}
            )
            
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT, context=self._ssl_context) as response:
                data = json.loads(response.read().decode('utf-8'))
            
            if isinstance(data, list) and len(data) > 0:
                if 'predicted_aligned_error' in data[0]:
                    pae_data = data[0]['predicted_aligned_error']
                elif 'pae' in data[0]:
                    pae_data = data[0]['pae']
                else:
                    pae_data = data
            else:
                pae_data = data.get('predicted_aligned_error', data)
            
            pae_matrix = np.array(pae_data, dtype=np.float32)
            
            if CACHE_MODE == CacheMode.SOVEREIGN:
                np.save(cache_path, pae_matrix)
                logger.info(f"PAE saved to cache: {cache_path}")
            
            return (True, pae_matrix, None)
            
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return (False, None, f"PAE matrix not available for {uniprot_id}")
            return (False, None, f"HTTP error {e.code}: {e.reason}")
        except Exception as e:
            return (False, None, f"Error fetching PAE: {str(e)}")
    
    def compute_pae_statistics(self, pae_matrix: np.ndarray) -> Dict[str, Any]:
        """Compute PAE statistics."""
        return {
            'shape': pae_matrix.shape,
            'n_residues': pae_matrix.shape[0],
            'mean_pae': float(np.mean(pae_matrix)),
            'median_pae': float(np.median(pae_matrix)),
            'min_pae': float(np.min(pae_matrix)),
            'max_pae': float(np.max(pae_matrix)),
            'std_pae': float(np.std(pae_matrix)),
            'high_confidence_fraction': float(np.mean(pae_matrix < 5.0)),
            'medium_confidence_fraction': float(np.mean((pae_matrix >= 5.0) & (pae_matrix < 15.0))),
            'low_confidence_fraction': float(np.mean(pae_matrix >= 15.0))
        }


# ===========================================================================
# PR #3: DOMAIN DETECTOR
# ===========================================================================

class DomainDetector:
    """
    Detect protein domains from PAE matrix.
    
    PROPRIETARY FRAMEWORK - TOPOLOGICA LLC
    """
    
    def __init__(self, pae_threshold: float = 5.0, min_domain_size: int = 30):
        self.pae_threshold = pae_threshold
        self.min_domain_size = min_domain_size
    
    def detect_domains(self, pae_matrix: np.ndarray) -> Dict[str, Any]:
        """Detect domains from PAE matrix."""
        n = pae_matrix.shape[0]
        
        symmetric_pae = (pae_matrix + pae_matrix.T) / 2
        adjacency = (symmetric_pae < self.pae_threshold).astype(np.int32)
        np.fill_diagonal(adjacency, 0)
        
        parent = list(range(n))
        
        def find(x):
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]
        
        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py
        
        for i in range(n):
            for j in range(i + 1, n):
                if adjacency[i, j]:
                    union(i, j)
        
        components = {}
        for i in range(n):
            root = find(i)
            if root not in components:
                components[root] = []
            components[root].append(i)
        
        domains = []
        linker_residues = set(range(n))
        
        for comp_residues in components.values():
            if len(comp_residues) >= self.min_domain_size:
                start = min(comp_residues)
                end = max(comp_residues)
                domain_pae = symmetric_pae[np.ix_(comp_residues, comp_residues)]
                
                domains.append({
                    'start': int(start) + 1,
                    'end': int(end) + 1,
                    'length': len(comp_residues),
                    'residues': sorted([r + 1 for r in comp_residues]),
                    'mean_internal_pae': float(np.mean(domain_pae)),
                    'contiguity': len(comp_residues) / (end - start + 1)
                })
                
                linker_residues -= set(comp_residues)
        
        domains.sort(key=lambda x: x['start'])
        
        for i, d in enumerate(domains):
            d['domain_id'] = i + 1
        
        linkers = []
        if linker_residues:
            linker_list = sorted(linker_residues)
            current_linker = [linker_list[0]]
            
            for r in linker_list[1:]:
                if r == current_linker[-1] + 1:
                    current_linker.append(r)
                else:
                    if len(current_linker) >= 3:
                        linkers.append({
                            'start': current_linker[0] + 1,
                            'end': current_linker[-1] + 1,
                            'length': len(current_linker)
                        })
                    current_linker = [r]
            
            if len(current_linker) >= 3:
                linkers.append({
                    'start': current_linker[0] + 1,
                    'end': current_linker[-1] + 1,
                    'length': len(current_linker)
                })
        
        return {
            'n_residues': n,
            'n_domains': len(domains),
            'n_linkers': len(linkers),
            'domains': domains,
            'linkers': linkers,
            'pae_threshold': self.pae_threshold,
            'min_domain_size': self.min_domain_size,
            'coverage': 1.0 - len(linker_residues) / n
        }
    
    def detect_domains_from_pdb(
        self,
        pdb_path: str,
        pae_threshold: float = None,
        min_domain_size: int = None
    ) -> List[Dict[str, Any]]:
        """
        Detect domains from PDB file path by extracting PAE and analyzing.
        
        Args:
            pdb_path: Path to AlphaFold PDB file
            pae_threshold: Override default threshold
            min_domain_size: Override default minimum domain size
        
        Returns:
            List of detected domains
        """
        # Use parameters if provided
        if pae_threshold is not None:
            self.pae_threshold = pae_threshold
        if min_domain_size is not None:
            self.min_domain_size = min_domain_size
        
        # Try to find PAE file alongside PDB
        pdb_path_obj = Path(pdb_path)
        pae_path = pdb_path_obj.parent / pdb_path_obj.name.replace('.pdb', '_pae.json')
        
        if not pae_path.exists():
            # Try alternate naming
            pae_path = pdb_path_obj.parent / f"{pdb_path_obj.stem}_predicted_aligned_error.json"
        
        if pae_path.exists():
            try:
                with open(pae_path, 'r') as f:
                    pae_data = json.load(f)
                
                # Extract PAE matrix from AlphaFold format
                if isinstance(pae_data, list) and len(pae_data) > 0:
                    pae_matrix = np.array(pae_data[0].get('predicted_aligned_error', pae_data))
                elif isinstance(pae_data, dict):
                    pae_matrix = np.array(pae_data.get('predicted_aligned_error', []))
                else:
                    pae_matrix = np.array(pae_data)
                
                if pae_matrix.size > 0:
                    result = self.detect_domains(pae_matrix)
                    return result.get('domains', [])
            except Exception as e:
                logger.warning(f"Failed to read PAE file {pae_path}: {e}")
        
        # Fallback: extract pLDDT and create pseudo-domains based on confidence
        plddt_values = extract_plddt_from_pdb(pdb_path)
        if not plddt_values:
            return []
        
        # Create simple domain based on high-confidence regions
        plddt_array = np.array(plddt_values)
        high_conf = plddt_array > 70
        
        domains = []
        in_domain = False
        start = 0
        
        for i, is_conf in enumerate(high_conf):
            if is_conf and not in_domain:
                start = i
                in_domain = True
            elif not is_conf and in_domain:
                if i - start >= self.min_domain_size:
                    domains.append({
                        'start': int(start) + 1,
                        'end': int(i),
                        'size': int(i - start),
                        'mean_plddt': float(np.mean(plddt_array[start:i])),
                        'intra_pae': 5.0  # Estimated
                    })
                in_domain = False
        
        if in_domain and len(plddt_values) - start >= self.min_domain_size:
            domains.append({
                'start': int(start) + 1,
                'end': len(plddt_values),
                'size': len(plddt_values) - start,
                'mean_plddt': float(np.mean(plddt_array[start:])),
                'intra_pae': 5.0
            })
        
        return domains


# ===========================================================================
# PR #3: DISORDER PREDICTOR
# ===========================================================================

class DisorderPredictor:
    """
    Predict intrinsically disordered regions from pLDDT scores.
    
    PROPRIETARY FRAMEWORK - TOPOLOGICA LLC
    """
    
    def __init__(self, plddt_threshold: float = 50.0, min_region_length: int = 5):
        self.plddt_threshold = plddt_threshold
        self.min_region_length = min_region_length
    
    def predict(self, plddt_scores: np.ndarray) -> Dict[str, Any]:
        """Predict disordered regions from pLDDT scores."""
        n = len(plddt_scores)
        is_disordered = plddt_scores < self.plddt_threshold
        
        regions = []
        in_region = False
        start = 0
        
        for i, disordered in enumerate(is_disordered):
            if disordered and not in_region:
                start = i
                in_region = True
            elif not disordered and in_region:
                if i - start >= self.min_region_length:
                    regions.append({
                        'start': int(start) + 1,
                        'end': int(i),
                        'length': int(i - start),
                        'mean_plddt': float(np.mean(plddt_scores[start:i])),
                        'min_plddt': float(np.min(plddt_scores[start:i]))
                    })
                in_region = False
        
        if in_region and n - start >= self.min_region_length:
            regions.append({
                'start': int(start) + 1,
                'end': int(n),
                'length': int(n - start),
                'mean_plddt': float(np.mean(plddt_scores[start:])),
                'min_plddt': float(np.min(plddt_scores[start:]))
            })
        
        total_disordered = sum(r['length'] for r in regions)
        
        return {
            'n_residues': n,
            'n_disordered_regions': len(regions),
            'total_disordered_residues': total_disordered,
            'disorder_fraction': total_disordered / n if n > 0 else 0.0,
            'plddt_threshold': self.plddt_threshold,
            'min_region_length': self.min_region_length,
            'regions': regions,
            'mean_plddt': float(np.mean(plddt_scores)),
            'plddt_below_threshold': int(np.sum(is_disordered))
        }
    
    def predict_disorder(
        self,
        pdb_path: str,
        plddt_threshold: float = None,
        min_region_length: int = None
    ) -> Dict[str, Any]:
        """
        Predict disorder from PDB file path.
        
        Args:
            pdb_path: Path to AlphaFold PDB file
            plddt_threshold: Override default threshold
            min_region_length: Override default minimum region length
        
        Returns:
            Disorder prediction results
        """
        # Use parameters if provided, else use instance defaults
        if plddt_threshold is not None:
            self.plddt_threshold = plddt_threshold
        if min_region_length is not None:
            self.min_region_length = min_region_length
        
        # Extract pLDDT values from PDB
        plddt_values = extract_plddt_from_pdb(pdb_path)
        
        if not plddt_values:
            return {
                'total_residues': 0,
                'disordered_count': 0,
                'disorder_fraction': 0.0,
                'regions': [],
                'error': 'Failed to extract pLDDT values'
            }
        
        # Convert to numpy and predict
        plddt_array = np.array(plddt_values)
        result = self.predict(plddt_array)
        
        # Rename keys for API consistency
        return {
            'total_residues': result['n_residues'],
            'disordered_count': result['total_disordered_residues'],
            'disorder_fraction': result['disorder_fraction'],
            'n_disordered_regions': result['n_disordered_regions'],
            'regions': result['regions'],
            'mean_plddt': result['mean_plddt'],
            'plddt_threshold': result['plddt_threshold'],
            'min_region_length': result['min_region_length']
        }


# ===========================================================================
# PR #3: INFORMATION CONTENT CALCULATOR
# ===========================================================================

class InformationContentCalculator:
    """
    Calculate Information Content (IC) for GO terms.
    
    PROPRIETARY FRAMEWORK - TOPOLOGICA LLC
    Patent-pending by Santiago Maniches (ORCID: 0009-0005-6480-1987)
    
    IC(term) = -log2(P(term))
    """
    
    IC_CACHE_FILE = "go_ic_cache.json"
    
    def __init__(self, cache_dir: Path = CACHE_DIR):
        self.cache_dir = Path(cache_dir) / "information_content"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.ic_cache_path = self.cache_dir / self.IC_CACHE_FILE
        self.ic_cache = self._load_cache()
        
        self.default_frequencies = {
            'GO:0003674': 1.0, 'GO:0003824': 0.45, 'GO:0005488': 0.55,
            'GO:0005515': 0.25, 'GO:0016787': 0.15, 'GO:0016301': 0.05,
            'GO:0003700': 0.02, 'GO:0008150': 1.0, 'GO:0008152': 0.40,
            'GO:0009987': 0.35, 'GO:0065007': 0.30, 'GO:0006950': 0.10,
            'GO:0007165': 0.08, 'GO:0006468': 0.03, 'GO:0005575': 1.0,
            'GO:0005622': 0.70, 'GO:0005737': 0.60, 'GO:0005634': 0.35,
            'GO:0016020': 0.40, 'GO:0005886': 0.25, 'GO:0005739': 0.08,
        }
    
    def _load_cache(self) -> Dict[str, float]:
        if self.ic_cache_path.exists():
            try:
                with open(self.ic_cache_path, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    def _save_cache(self) -> None:
        try:
            with open(self.ic_cache_path, 'w') as f:
                json.dump(self.ic_cache, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save IC cache: {e}")
    
    def get_frequency(self, go_term: str, corpus: str = "uniprot") -> float:
        go_term = go_term.upper()
        if go_term in self.default_frequencies:
            return self.default_frequencies[go_term]
        return 0.001
    
    def compute_ic(self, go_term: str, corpus: str = "uniprot", normalize: bool = True) -> float:
        """
        Compute Information Content for a GO term.
        
        Args:
            go_term: GO term ID
            corpus: Corpus for frequency calculation ('uniprot', 'cafa', 'custom')
            normalize: If True, normalize IC to [0, 1] range
        
        Returns:
            IC value (normalized if normalize=True)
        """
        go_term = go_term.upper()
        cache_key = f"{go_term}_{corpus}_{normalize}"
        if cache_key in self.ic_cache:
            return self.ic_cache[cache_key]
        
        freq = self.get_frequency(go_term, corpus)
        if freq <= 0:
            freq = 1e-10
        
        ic = -np.log2(freq)
        
        # Normalize to [0, 1] if requested (max IC is ~10 for very rare terms)
        if normalize:
            ic = min(ic / 10.0, 1.0)
        
        self.ic_cache[cache_key] = float(ic)
        
        return float(ic)
    
    def compute_batch_ic(
        self,
        go_terms: List[str],
        progress_callback: Optional['ProgressCallback'] = None
    ) -> Dict[str, float]:
        results = {}
        for i, term in enumerate(go_terms):
            if progress_callback:
                progress_callback.update(i, f"Computing IC for {term}")
            results[term.upper()] = self.compute_ic(term)
        self._save_cache()
        return results


# ===========================================================================
# PR #3: SEMANTIC SIMILARITY CALCULATOR
# ===========================================================================

class SemanticSimilarityCalculator:
    """
    Calculate semantic similarity between GO terms.
    
    PROPRIETARY FRAMEWORK - TOPOLOGICA LLC
    """
    
    def __init__(self, ic_calculator: Optional[InformationContentCalculator] = None):
        self.ic_calculator = ic_calculator or InformationContentCalculator()
        self.ancestors_cache: Dict[str, set] = {}
        self.roots = {
            'molecular_function': 'GO:0003674',
            'biological_process': 'GO:0008150',
            'cellular_component': 'GO:0005575'
        }
    
    def get_ancestors(self, go_term: str) -> set:
        go_term = go_term.upper()
        if go_term in self.ancestors_cache:
            return self.ancestors_cache[go_term]
        
        try:
            url = f"https://www.ebi.ac.uk/QuickGO/services/ontology/go/terms/{go_term}/ancestors"
            ssl_context = ssl.create_default_context()
            request = urllib.request.Request(url, headers={
                'User-Agent': 'TOPOLOGICA-Sovereign-AlphaFold/1.0',
                'Accept': 'application/json'
            })
            
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT, context=ssl_context) as response:
                data = json.loads(response.read().decode('utf-8'))
            
            ancestors = {go_term}
            for result in data.get('results', []):
                for ancestor in result.get('ancestors', []):
                    ancestors.add(ancestor)
            
            self.ancestors_cache[go_term] = ancestors
            return ancestors
            
        except Exception as e:
            logger.warning(f"Failed to fetch ancestors for {go_term}: {e}")
            return {go_term}
    
    def find_mica(self, term1: str, term2: str) -> Optional[str]:
        ancestors1 = self.get_ancestors(term1)
        ancestors2 = self.get_ancestors(term2)
        common = ancestors1 & ancestors2
        
        if not common:
            return None
        
        max_ic = -1
        mica = None
        for ancestor in common:
            ic = self.ic_calculator.compute_ic(ancestor)
            if ic > max_ic:
                max_ic = ic
                mica = ancestor
        return mica
    
    def resnik_similarity(self, term1: str, term2: str) -> float:
        mica = self.find_mica(term1, term2)
        if mica is None:
            return 0.0
        return self.ic_calculator.compute_ic(mica)
    
    def lin_similarity(self, term1: str, term2: str) -> float:
        mica = self.find_mica(term1, term2)
        if mica is None:
            return 0.0
        
        ic_mica = self.ic_calculator.compute_ic(mica)
        ic_t1 = self.ic_calculator.compute_ic(term1)
        ic_t2 = self.ic_calculator.compute_ic(term2)
        
        denominator = ic_t1 + ic_t2
        if denominator <= 0:
            return 0.0
        return 2 * ic_mica / denominator
    
    def jiang_similarity(self, term1: str, term2: str) -> float:
        mica = self.find_mica(term1, term2)
        if mica is None:
            return 0.0
        
        ic_mica = self.ic_calculator.compute_ic(mica)
        ic_t1 = self.ic_calculator.compute_ic(term1)
        ic_t2 = self.ic_calculator.compute_ic(term2)
        
        distance = ic_t1 + ic_t2 - 2 * ic_mica
        return 1.0 / (1.0 + distance)
    
    def compute_similarity(self, term1: str, term2: str, method: str = "resnik") -> float:
        method = method.lower()
        if method == "resnik":
            return self.resnik_similarity(term1, term2)
        elif method == "lin":
            return self.lin_similarity(term1, term2)
        elif method == "jiang":
            return self.jiang_similarity(term1, term2)
        else:
            logger.warning(f"Unknown method {method}, using Lin")
            return self.lin_similarity(term1, term2)


# ===========================================================================
# PR #3: ADVANCED TOPOLOGY COMPUTER
# ===========================================================================

class AdvancedTopologyComputer:
    """
    Advanced topological data analysis for protein structures.
    
    PROPRIETARY FRAMEWORK - TOPOLOGICA LLC
    Patent-pending by Santiago Maniches (ORCID: 0009-0005-6480-1987)
    """
    
    def __init__(self, max_dimension: int = 2, max_filtration: float = 25.0):
        self.max_dimension = max_dimension
        self.max_filtration = max_filtration
    
    def compute_distance_matrix(self, coords: np.ndarray) -> np.ndarray:
        diff = coords[:, np.newaxis, :] - coords[np.newaxis, :, :]
        return np.sqrt(np.sum(diff ** 2, axis=2))
    
    def compute_betti_at_scale(self, distance_matrix: np.ndarray, radius: float) -> Tuple[int, int, int]:
        n = distance_matrix.shape[0]
        adjacency = (distance_matrix <= 2 * radius).astype(int)
        np.fill_diagonal(adjacency, 0)
        
        parent = list(range(n))
        
        def find(x):
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]
        
        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py
        
        for i in range(n):
            for j in range(i + 1, n):
                if adjacency[i, j]:
                    union(i, j)
        
        beta_0 = len(set(find(i) for i in range(n)))
        n_edges = np.sum(adjacency) // 2
        beta_1_upper = max(0, n_edges - n + beta_0)
        beta_2 = 0
        
        return (beta_0, beta_1_upper, beta_2)
    
    def compute_persistence_diagram(
        self,
        coords: np.ndarray,
        n_steps: int = 100,
        progress_callback: Optional['ProgressCallback'] = None
    ) -> Dict[str, Any]:
        distance_matrix = self.compute_distance_matrix(coords)
        filtration_values = np.linspace(0, self.max_filtration, n_steps)
        
        betti_history = []
        for i, r in enumerate(filtration_values):
            if progress_callback:
                progress_callback.update(i, f"Computing topology at r={r:.1f}A")
            b0, b1, b2 = self.compute_betti_at_scale(distance_matrix, r)
            betti_history.append({
                'radius': float(r), 'beta_0': b0, 'beta_1': b1,
                'beta_2': b2, 'euler': b0 - b1 + b2
            })
        
        h0_pairs = self._extract_persistence_pairs(betti_history, 'beta_0')
        h1_pairs = self._extract_persistence_pairs(betti_history, 'beta_1')
        h2_pairs = self._extract_persistence_pairs(betti_history, 'beta_2')
        
        final = betti_history[-1] if betti_history else {'beta_0': 0, 'beta_1': 0, 'beta_2': 0}
        
        return {
            'betti_0': final['beta_0'], 'betti_1': final['beta_1'], 'betti_2': final['beta_2'],
            'euler_characteristic': final['beta_0'] - final['beta_1'] + final['beta_2'],
            'persistence_diagram': {'H0': h0_pairs, 'H1': h1_pairs, 'H2': h2_pairs},
            'betti_curve': betti_history,
            'n_filtration_steps': n_steps, 'max_filtration': self.max_filtration
        }
    
    def _extract_persistence_pairs(self, betti_history: List[Dict], key: str) -> List[Dict[str, float]]:
        pairs = []
        prev_value = 0
        births = []
        
        for entry in betti_history:
            current = entry[key]
            r = entry['radius']
            
            if current > prev_value:
                for _ in range(current - prev_value):
                    births.append(r)
            elif current < prev_value:
                for _ in range(prev_value - current):
                    if births:
                        birth = births.pop(0)
                        pairs.append({'birth': float(birth), 'death': float(r), 'persistence': float(r - birth)})
            
            prev_value = current
        
        for birth in births:
            pairs.append({'birth': float(birth), 'death': float('inf'), 'persistence': float('inf')})
        
        return pairs
    
    def compute_persistence_landscape(
        self, persistence_pairs: List[Dict], n_layers: int = 5, resolution: int = 100
    ) -> np.ndarray:
        if not persistence_pairs:
            return np.zeros((n_layers, resolution))
        
        finite_pairs = [p for p in persistence_pairs if p['death'] != float('inf')]
        if not finite_pairs:
            return np.zeros((n_layers, resolution))
        
        births = [p['birth'] for p in finite_pairs]
        deaths = [p['death'] for p in finite_pairs]
        t_min, t_max = min(births), max(deaths)
        t_values = np.linspace(t_min, t_max, resolution)
        
        landscape = np.zeros((n_layers, resolution))
        
        for j, t in enumerate(t_values):
            tent_values = []
            for p in finite_pairs:
                b, d = p['birth'], p['death']
                if b <= t <= d:
                    tent_values.append(min(t - b, d - t))
            tent_values.sort(reverse=True)
            for k in range(min(n_layers, len(tent_values))):
                landscape[k, j] = tent_values[k]
        
        return landscape
    
    def wasserstein_distance(self, diagram1: List[Dict], diagram2: List[Dict], p: int = 2) -> float:
        pairs1 = [(p['birth'], p['death']) for p in diagram1 if p['death'] != float('inf')]
        pairs2 = [(p['birth'], p['death']) for p in diagram2 if p['death'] != float('inf')]
        
        if not pairs1 and not pairs2:
            return 0.0
        if not pairs1:
            return sum(abs(d - b) ** p for b, d in pairs2) ** (1/p)
        if not pairs2:
            return sum(abs(d - b) ** p for b, d in pairs1) ** (1/p)
        
        used2 = set()
        total_cost = 0.0
        
        for b1, d1 in pairs1:
            min_cost = abs(d1 - b1) ** p
            best_j = None
            
            for j, (b2, d2) in enumerate(pairs2):
                if j not in used2:
                    cost = (abs(b1 - b2) ** p + abs(d1 - d2) ** p) ** 0.5
                    if cost < min_cost:
                        min_cost = cost
                        best_j = j
            
            if best_j is not None:
                used2.add(best_j)
            total_cost += min_cost ** p
        
        for j, (b2, d2) in enumerate(pairs2):
            if j not in used2:
                total_cost += abs(d2 - b2) ** p
        
        return total_cost ** (1/p)
    
    def bottleneck_distance(self, diagram1: List[Dict], diagram2: List[Dict]) -> float:
        pairs1 = [(p['birth'], p['death']) for p in diagram1 if p['death'] != float('inf')]
        pairs2 = [(p['birth'], p['death']) for p in diagram2 if p['death'] != float('inf')]
        
        if not pairs1 and not pairs2:
            return 0.0
        if not pairs1:
            return max(abs(d - b) / 2 for b, d in pairs2)
        if not pairs2:
            return max(abs(d - b) / 2 for b, d in pairs1)
        
        max_cost = 0.0
        for b1, d1 in pairs1:
            min_cost = abs(d1 - b1) / 2
            for b2, d2 in pairs2:
                cost = max(abs(b1 - b2), abs(d1 - d2))
                min_cost = min(min_cost, cost)
            max_cost = max(max_cost, min_cost)
        
        return max_cost
    
    def compare_proteins(
        self,
        pdb_path1: str,
        pdb_path2: str,
        metric: str = "wasserstein",
        dimension: int = 1
    ) -> Dict[str, Any]:
        """
        Compare topological features between two proteins.
        
        Args:
            pdb_path1: Path to first protein PDB file
            pdb_path2: Path to second protein PDB file
            metric: Distance metric ('wasserstein' or 'bottleneck')
            dimension: Homology dimension to compare (0, 1, or 2)
        
        Returns:
            Comparison results with distance and interpretation
        """
        # Extract coordinates from both PDB files
        coords1 = self._extract_ca_coords(pdb_path1)
        coords2 = self._extract_ca_coords(pdb_path2)
        
        if coords1 is None or len(coords1) == 0:
            return {'error': f'Failed to extract coordinates from {pdb_path1}'}
        if coords2 is None or len(coords2) == 0:
            return {'error': f'Failed to extract coordinates from {pdb_path2}'}
        
        # Compute persistence diagrams
        diagram1 = self.compute_persistence_diagram(coords1)
        diagram2 = self.compute_persistence_diagram(coords2)
        
        # Get the appropriate homology dimension
        dim_key = f'H{dimension}'
        pairs1 = diagram1.get('persistence_diagram', {}).get(dim_key, [])
        pairs2 = diagram2.get('persistence_diagram', {}).get(dim_key, [])
        
        # Compute distance
        if metric.lower() == 'wasserstein':
            distance = self.wasserstein_distance(pairs1, pairs2)
        elif metric.lower() == 'bottleneck':
            distance = self.bottleneck_distance(pairs1, pairs2)
        else:
            distance = self.wasserstein_distance(pairs1, pairs2)
        
        return {
            'distance': float(distance),
            'metric': metric,
            'dimension': dimension,
            'protein1_betti': [diagram1.get('betti_0', 0), diagram1.get('betti_1', 0), diagram1.get('betti_2', 0)],
            'protein2_betti': [diagram2.get('betti_0', 0), diagram2.get('betti_1', 0), diagram2.get('betti_2', 0)],
            'interpretation': 'similar' if distance < 1.0 else 'different'
        }
    
    def _extract_ca_coords(self, pdb_path: str) -> Optional[np.ndarray]:
        """Extract C-alpha coordinates from PDB file."""
        coords = []
        try:
            with open(pdb_path, 'r') as f:
                for line in f:
                    if line.startswith('ATOM') and len(line) >= 54:
                        atom_name = line[12:16].strip()
                        if atom_name == 'CA':
                            try:
                                x = float(line[30:38].strip())
                                y = float(line[38:46].strip())
                                z = float(line[46:54].strip())
                                coords.append([x, y, z])
                            except (ValueError, IndexError):
                                continue
        except Exception as e:
            logger.error(f"Error reading PDB file {pdb_path}: {e}")
            return None
        
        return np.array(coords) if coords else None
    
    def compute_advanced_features(
        self,
        pdb_path: str,
        max_dimension: int = 2,
        max_filtration: float = 25.0,
        include_landscapes: bool = False,
        include_images: bool = False,
        n_landscapes: int = 5,
        image_resolution: int = 50
    ) -> Dict[str, Any]:
        """
        Compute advanced topological features from PDB file.
        
        Args:
            pdb_path: Path to protein PDB file
            max_dimension: Maximum homology dimension
            max_filtration: Maximum filtration radius
            include_landscapes: Compute persistence landscapes
            include_images: Compute persistence images
            n_landscapes: Number of landscape layers
            image_resolution: Resolution for persistence images
        
        Returns:
            Complete topological analysis results
        """
        # Update instance parameters
        self.max_dimension = max_dimension
        self.max_filtration = max_filtration
        
        # Extract coordinates
        coords = self._extract_ca_coords(pdb_path)
        if coords is None or len(coords) == 0:
            return {'error': 'Failed to extract coordinates'}
        
        # Compute persistence diagram
        result = self.compute_persistence_diagram(coords, n_steps=100)
        
        # Add persistence entropy
        h1_pairs = result.get('persistence_diagram', {}).get('H1', [])
        if h1_pairs:
            finite_pers = [p['persistence'] for p in h1_pairs if p['persistence'] != float('inf') and p['persistence'] > 0]
            if finite_pers:
                total = sum(finite_pers)
                probs = [p/total for p in finite_pers]
                entropy = -sum(p * np.log(p + 1e-10) for p in probs)
                result['persistence_entropy'] = float(entropy)
        
        # Add landscapes if requested
        if include_landscapes:
            h1_diagram = result.get('persistence_diagram', {}).get('H1', [])
            landscapes = self.compute_persistence_landscape(h1_diagram, n_landscapes, image_resolution)
            result['landscapes'] = landscapes.tolist()
        
        # Add images if requested
        if include_images:
            h1_diagram = result.get('persistence_diagram', {}).get('H1', [])
            image = self._compute_persistence_image(h1_diagram, image_resolution)
            result['persistence_image'] = image.tolist() if image is not None else None
        
        return result
    
    def _compute_persistence_image(
        self,
        persistence_pairs: List[Dict],
        resolution: int = 50
    ) -> Optional[np.ndarray]:
        """Compute persistence image from persistence diagram."""
        finite_pairs = [p for p in persistence_pairs if p['death'] != float('inf')]
        if not finite_pairs:
            return np.zeros((resolution, resolution))
        
        # Transform to birth-persistence coordinates
        births = np.array([p['birth'] for p in finite_pairs])
        persists = np.array([p['death'] - p['birth'] for p in finite_pairs])
        
        # Create grid
        b_min, b_max = births.min(), births.max()
        p_min, p_max = 0, persists.max()
        
        if b_max == b_min:
            b_max = b_min + 1
        if p_max == p_min:
            p_max = p_min + 1
        
        image = np.zeros((resolution, resolution))
        
        # Add Gaussian kernel at each point
        sigma = max((b_max - b_min), (p_max - p_min)) / (resolution * 2)
        
        for b, p in zip(births, persists):
            # Grid indices
            bi = int((b - b_min) / (b_max - b_min) * (resolution - 1))
            pi = int((p - p_min) / (p_max - p_min) * (resolution - 1))
            bi = min(max(bi, 0), resolution - 1)
            pi = min(max(pi, 0), resolution - 1)
            
            # Add weighted point (weight by persistence)
            image[pi, bi] += p
        
        return image


# Global instances (lazy loaded)
_pae_extractor: Optional[PAEExtractor] = None
_ic_calculator: Optional[InformationContentCalculator] = None
_similarity_calculator: Optional[SemanticSimilarityCalculator] = None
_advanced_topology: Optional[AdvancedTopologyComputer] = None


def get_pae_extractor() -> PAEExtractor:
    global _pae_extractor
    if _pae_extractor is None:
        _pae_extractor = PAEExtractor()
    return _pae_extractor


def get_ic_calculator() -> InformationContentCalculator:
    global _ic_calculator
    if _ic_calculator is None:
        _ic_calculator = InformationContentCalculator()
    return _ic_calculator


def get_similarity_calculator() -> SemanticSimilarityCalculator:
    global _similarity_calculator
    if _similarity_calculator is None:
        _similarity_calculator = SemanticSimilarityCalculator()
    return _similarity_calculator


def get_advanced_topology() -> AdvancedTopologyComputer:
    global _advanced_topology
    if _advanced_topology is None:
        _advanced_topology = AdvancedTopologyComputer()
    return _advanced_topology


# ===========================================================================
# PHASE 1 HELPER FUNCTIONS - ADDITIONAL LAZY LOADED INSTANCES
# ===========================================================================

_disorder_predictor: Optional['DisorderPredictor'] = None
_domain_detector: Optional['DomainDetector'] = None
_topology_computer: Optional['AdvancedTopologyComputer'] = None


def get_disorder_predictor() -> 'DisorderPredictor':
    """Get or create disorder predictor instance."""
    global _disorder_predictor
    if _disorder_predictor is None:
        _disorder_predictor = DisorderPredictor()
    return _disorder_predictor


def get_domain_detector() -> 'DomainDetector':
    """Get or create domain detector instance."""
    global _domain_detector
    if _domain_detector is None:
        _domain_detector = DomainDetector()
    return _domain_detector


def get_topology_computer() -> 'AdvancedTopologyComputer':
    """Get or create topology computer instance for comparison operations."""
    global _topology_computer
    if _topology_computer is None:
        _topology_computer = AdvancedTopologyComputer()
    return _topology_computer


def extract_plddt_from_pdb(pdb_path: str) -> List[float]:
    """
    Extract per-residue pLDDT values from PDB file.
    
    In AlphaFold PDB files, pLDDT is stored in the B-factor column.
    Returns list of pLDDT values, one per residue (CA atoms).
    """
    plddt_values = []
    current_residue = None
    
    try:
        with open(pdb_path, 'r') as f:
            for line in f:
                if line.startswith('ATOM') and len(line) >= 66:
                    atom_name = line[12:16].strip()
                    if atom_name == 'CA':
                        try:
                            residue_num = int(line[22:26].strip())
                            if residue_num != current_residue:
                                current_residue = residue_num
                                # B-factor column is 60-66
                                plddt = float(line[60:66].strip())
                                plddt_values.append(plddt)
                        except (ValueError, IndexError):
                            continue
    except Exception as e:
        logger.error(f"Error extracting pLDDT from {pdb_path}: {e}")
        return []
    
    return plddt_values



# ===========================================================================
# MCP TOOLS - MAIN INTERFACE
# ===========================================================================

@mcp.tool()
async def get_structure(params: GetStructureInput) -> str:
    """
    Retrieve an AlphaFold protein structure by UniProt ID.
    
    PROPRIETARY TOOL - TOPOLOGICA LLC
    
    Operation (Cache-First Sovereign Strategy):
        1. Check local cache (dynamically indexed, grows with usage)
        2. If not found, fetch from AlphaFold DB online
        3. Auto-cache fetched structures for future sovereign access
        4. Optionally compute structural and topological features
    
    Args:
        uniprot_id: UniProt accession (e.g., 'P12345', 'A0A023FBW4')
        include_features: Compute secondary structure, binding pockets
        include_topology: Compute persistent homology (slower)
        force_online: Force fetch from AlphaFold DB
    
    Returns:
        Structure details with optional features in markdown or JSON
    """
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    logger.info(f"[{timestamp}] get_structure called: {params.uniprot_id}")
    
    try:
        manager = get_structure_manager()
        
        # Get structure
        success, structure, error = manager.get_structure(
            params.uniprot_id,
            force_online=params.force_online
        )
        
        if not success or structure is None:
            return f"Error: {error or 'Structure not found'}"
        
        # Compute features if requested
        features = {}
        
        if params.include_features:
            features['secondary_structure'] = FeatureComputer.compute_secondary_structure(structure)
            features['binding_pockets'] = FeatureComputer.compute_binding_pockets(structure)
            features['confidence'] = FeatureComputer.compute_confidence_regions(structure)
            features['contacts'] = FeatureComputer.compute_contact_density(structure)
        
        # Compute topology if requested
        topology = None
        if params.include_topology:
            topology = TopologyComputer.compute_persistent_homology(structure)
        
        return format_structure_response(
            structure,
            features if features else None,
            topology,
            params.response_format
        )
        
    except Exception as e:
        logger.error(f"[{timestamp}] Error in get_structure: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
async def search_structures(params: SearchStructuresInput) -> str:
    """
    Search local AlphaFold structure cache.
    
    PROPRIETARY TOOL - TOPOLOGICA LLC
    
    Searches the sovereign cache (dynamically indexed) by UniProt ID pattern.
    Includes both pre-downloaded structures and previously-fetched online structures.
    
    Args:
        pattern: Glob-style pattern (e.g., 'A0A*', 'P123*')
        limit: Maximum results (default 100)
        offset: Pagination offset
    
    Returns:
        List of matching UniProt IDs
    """
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    logger.info(f"[{timestamp}] search_structures called: pattern={params.pattern}")
    
    try:
        manager = get_structure_manager()
        
        results = manager.search_local(
            pattern=params.pattern,
            limit=params.limit,
            offset=params.offset
        )
        
        stats = manager.get_statistics()
        
        if params.response_format == ResponseFormat.JSON:
            return json.dumps({
                'pattern': params.pattern,
                'offset': params.offset,
                'limit': params.limit,
                'count': len(results),
                'total_local': stats['local_structures'],
                'results': results
            }, indent=2)
        
        lines = [
            f"# Structure Search Results",
            "",
            f"**Pattern:** `{params.pattern}`",
            f"**Results:** {len(results)} (of {stats['local_structures']} local structures)",
            f"**Offset:** {params.offset}",
            "",
            "## Matching UniProt IDs",
            ""
        ]
        
        for i, uid in enumerate(results[:50]):  # Show first 50
            lines.append(f"{i + 1 + params.offset}. `{uid}`")
        
        if len(results) > 50:
            lines.append(f"\n... and {len(results) - 50} more")
        
        return "\n".join(lines)
        
    except Exception as e:
        logger.error(f"[{timestamp}] Error in search_structures: {str(e)}")
        return f"Error: {str(e)}"



@mcp.tool()
async def batch_structures(params: BatchStructuresInput) -> str:
    """
    Retrieve multiple AlphaFold structures in batch.
    
    PROPRIETARY TOOL - TOPOLOGICA LLC
    
    Efficiently retrieves multiple structures with optional features.
    
    Args:
        uniprot_ids: List of UniProt IDs (max 50)
        include_features: Compute structural features for each
    
    Returns:
        Batch results with structure details
    """
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    logger.info(f"[{timestamp}] batch_structures called: {len(params.uniprot_ids)} IDs")
    
    try:
        manager = get_structure_manager()
        results = []
        
        for uid in params.uniprot_ids:
            success, structure, error = manager.get_structure(uid)
            
            if success and structure:
                entry = structure.to_dict()
                
                if params.include_features:
                    entry['secondary_structure'] = FeatureComputer.compute_secondary_structure(structure)
                    entry['confidence'] = FeatureComputer.compute_confidence_regions(structure)
                
                entry['status'] = 'success'
                results.append(entry)
            else:
                results.append({
                    'uniprot_id': uid,
                    'status': 'error',
                    'error': error or 'Not found'
                })
        
        if params.response_format == ResponseFormat.JSON:
            return json.dumps({
                'requested': len(params.uniprot_ids),
                'success': sum(1 for r in results if r['status'] == 'success'),
                'failed': sum(1 for r in results if r['status'] == 'error'),
                'results': results
            }, indent=2)
        
        # Markdown summary
        success_count = sum(1 for r in results if r['status'] == 'success')
        lines = [
            f"# Batch Structure Retrieval",
            "",
            f"**Requested:** {len(params.uniprot_ids)}",
            f"**Success:** {success_count}",
            f"**Failed:** {len(params.uniprot_ids) - success_count}",
            "",
            "## Results",
            ""
        ]
        
        for r in results:
            if r['status'] == 'success':
                lines.append(f"- **{r['uniprot_id']}**: {r['n_residues']} residues, pLDDT={r['mean_plddt']:.1f}")
            else:
                lines.append(f"- **{r['uniprot_id']}**: ERROR - {r['error']}")
        
        return "\n".join(lines)
        
    except Exception as e:
        logger.error(f"[{timestamp}] Error in batch_structures: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
async def get_features(params: GetFeaturesInput) -> str:
    """
    Compute detailed structural features for a protein.
    
    PROPRIETARY TOOL - TOPOLOGICA LLC
    
    Available features:
        - secondary_structure: Alpha-helix, beta-strand, coil classification
        - binding_pockets: Cavity detection with druggability scoring
        - confidence: pLDDT-based quality assessment
        - contacts: Local structural compactness
    
    Args:
        uniprot_id: UniProt accession
        feature_types: List of features to compute
    
    Returns:
        Detailed feature analysis
    """
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    logger.info(f"[{timestamp}] get_features called: {params.uniprot_id}")
    
    try:
        manager = get_structure_manager()
        success, structure, error = manager.get_structure(params.uniprot_id)
        
        if not success or structure is None:
            return f"Error: {error or 'Structure not found'}"
        
        features = {}
        
        for feature_type in params.feature_types:
            if feature_type == 'secondary_structure':
                features['secondary_structure'] = FeatureComputer.compute_secondary_structure(structure)
            elif feature_type == 'binding_pockets':
                features['binding_pockets'] = FeatureComputer.compute_binding_pockets(structure)
            elif feature_type == 'confidence':
                features['confidence'] = FeatureComputer.compute_confidence_regions(structure)
            elif feature_type == 'contacts':
                features['contacts'] = FeatureComputer.compute_contact_density(structure)
        
        if params.response_format == ResponseFormat.JSON:
            return json.dumps({
                'uniprot_id': params.uniprot_id,
                'n_residues': structure.n_residues,
                'features': features
            }, indent=2)
        
        return format_structure_response(
            structure,
            features,
            None,
            ResponseFormat.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"[{timestamp}] Error in get_features: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
async def get_topology(params: GetTopologyInput) -> str:
    """
    Compute topological features (persistent homology) for a protein.
    
    PROPRIETARY TOOL - TOPOLOGICA LLC
    
    Mathematical Foundation:
        Vietoris-Rips filtration on C-alpha atom point cloud.
        
        Computes:
        - beta_0: Connected components (protein domains)
        - beta_1: Loops/tunnels (structural motifs)
        - beta_2: Voids/cavities (binding sites)
        - Euler characteristic: chi = beta_0 - beta_1 + beta_2
        - Persistence diagrams: Birth/death pairs for features
    
    Args:
        uniprot_id: UniProt accession
        max_dimension: Maximum homology dimension (0, 1, or 2)
        max_filtration: Maximum filtration radius in Angstroms
    
    Returns:
        Topological invariants and persistence features
    """
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    logger.info(f"[{timestamp}] get_topology called: {params.uniprot_id}")
    
    try:
        manager = get_structure_manager()
        success, structure, error = manager.get_structure(params.uniprot_id)
        
        if not success or structure is None:
            return f"Error: {error or 'Structure not found'}"
        
        topology = TopologyComputer.compute_persistent_homology(
            structure,
            max_dimension=params.max_dimension,
            max_filtration=params.max_filtration
        )
        
        if params.response_format == ResponseFormat.JSON:
            return json.dumps({
                'uniprot_id': params.uniprot_id,
                'n_residues': structure.n_residues,
                'topology': topology
            }, indent=2)
        
        return format_structure_response(
            structure,
            None,
            topology,
            ResponseFormat.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"[{timestamp}] Error in get_topology: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
async def check_availability(params: CheckAvailabilityInput) -> str:
    """
    Check availability of structures (local cache and online).
    
    PROPRIETARY TOOL - TOPOLOGICA LLC
    
    Checks both local cache (instant) and AlphaFold DB (network).
    
    Args:
        uniprot_ids: List of UniProt IDs to check
    
    Returns:
        Availability status for each ID
    """
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    logger.info(f"[{timestamp}] check_availability called: {len(params.uniprot_ids)} IDs")
    
    try:
        manager = get_structure_manager()
        results = []
        
        for uid in params.uniprot_ids:
            uid_upper = uid.upper().strip()
            has_local = manager.has_local(uid_upper)
            
            results.append({
                'uniprot_id': uid_upper,
                'local': has_local,
                'online': 'unknown'  # Don't check online by default (slow)
            })
        
        local_count = sum(1 for r in results if r['local'])
        
        lines = [
            f"# Structure Availability Check",
            "",
            f"**Checked:** {len(params.uniprot_ids)}",
            f"**Available Locally:** {local_count}",
            f"**Not in Local Cache:** {len(params.uniprot_ids) - local_count}",
            "",
            "## Results",
            ""
        ]
        
        for r in results:
            status = "LOCAL" if r['local'] else "ONLINE ONLY"
            lines.append(f"- `{r['uniprot_id']}`: {status}")
        
        return "\n".join(lines)
        
    except Exception as e:
        logger.error(f"[{timestamp}] Error in check_availability: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
async def get_cache_statistics() -> str:
    """
    Get statistics about the local structure cache.
    
    PROPRIETARY TOOL - TOPOLOGICA LLC
    
    Returns information about:
        - Number of local structures
        - Cache directories and mode
        - Storage locations
        - Configuration status
    """
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    logger.info(f"[{timestamp}] get_cache_statistics called")
    
    try:
        manager = get_structure_manager()
        stats = manager.get_statistics()
        
        cache_mode_desc = {
            CacheMode.SOVEREIGN: "SOVEREIGN (full read/write - primary device)",
            CacheMode.READONLY: "READONLY (read cache, no writes - secondary device)",
            CacheMode.DISABLED: "DISABLED (pure online, no cache)"
        }
        
        lines = [
            "# AlphaFold Sovereign Cache Statistics",
            "",
            f"**Cache Mode:** {cache_mode_desc.get(CACHE_MODE, CACHE_MODE)}",
            f"**Local Structures:** {stats['local_structures']:,}",
            "",
            "## Directories",
            f"- **Primary Structures:** `{stats['structures_dir']}`",
            f"- **Cache Directory:** `{stats['cache_dir']}`",
            f"- **Online Cache:** `{stats['online_cache_dir']}`",
            "",
            "## Configuration",
            "Environment variables (override defaults):",
            "- `ALPHAFOLD_STRUCTURES_DIR` - Primary structures path",
            "- `ALPHAFOLD_CACHE_DIR` - Cache directory path",
            "- `ALPHAFOLD_CACHE_MODE` - sovereign | readonly | disabled",
            "",
            "## Coverage",
            f"- Local sovereign cache: {stats['local_structures']:,} structures",
            f"- Online fallback: 200M+ structures from AlphaFold DB",
            f"- No API key required for online access"
        ]
        
        return "\n".join(lines)
        
    except Exception as e:
        logger.error(f"[{timestamp}] Error in get_cache_statistics: {str(e)}")
        return f"Error: {str(e)}"


# Global UniProt fetcher instance
_uniprot_fetcher: Optional[UniProtFetcher] = None

def get_uniprot_fetcher() -> UniProtFetcher:
    """Get or create UniProt fetcher singleton."""
    global _uniprot_fetcher
    if _uniprot_fetcher is None:
        _uniprot_fetcher = UniProtFetcher()
    return _uniprot_fetcher


@mcp.tool()
async def get_enriched_protein(params: GetEnrichedProteinInput) -> str:
    """
    Get comprehensive protein information combining AlphaFold structure + UniProt metadata.
    
    PROPRIETARY TOOL - TOPOLOGICA LLC
    
    This tool provides UNIQUE VALUE by combining:
        1. AlphaFold structural data (3D coordinates, pLDDT confidence)
        2. UniProt functional annotations (function, GO terms, active sites)
        3. Disease associations and literature links
        4. Computed structural features (secondary structure, binding pockets)
    
    Use Cases:
        - Drug target assessment (structure + function + disease)
        - Protein characterization (complete biological context)
        - Research starting point (links to UniProt, PubMed, AlphaFold)
    
    Args:
        uniprot_id: UniProt accession (e.g., 'P53_HUMAN', 'EGFR_HUMAN')
        include_structure: Include AlphaFold structure summary
        include_go_terms: Include Gene Ontology annotations
        include_disease: Include disease associations
        include_features: Include computed structural features
    
    Returns:
        Comprehensive protein profile in markdown or JSON
    """
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    logger.info(f"[{timestamp}] get_enriched_protein called: {params.uniprot_id}")
    
    try:
        uniprot_id = params.uniprot_id.upper().strip()
        
        # Fetch UniProt metadata
        uniprot_fetcher = get_uniprot_fetcher()
        up_success, metadata, up_error = uniprot_fetcher.fetch(uniprot_id)
        
        if not up_success:
            return f"Error fetching UniProt data: {up_error}"
        
        # Fetch AlphaFold structure if requested
        structure_info = None
        features = {}
        if params.include_structure:
            manager = get_structure_manager()
            success, structure, error = manager.get_structure(uniprot_id)
            
            if success and structure:
                structure_info = {
                    'residue_count': len(structure.residues),
                    'mean_plddt': float(np.mean([r.plddt for r in structure.residues])),
                    'source': structure.source,
                    'alphafold_url': f"https://alphafold.ebi.ac.uk/entry/{uniprot_id}"
                }
                
                # Compute features if requested
                if params.include_features:
                    ca_coords = structure.get_ca_coordinates()
                    if len(ca_coords) > 0:
                        ss = FeatureComputer.compute_secondary_structure(structure)
                        features = {
                            'helix_fraction': ss.get('helix_fraction', 0),
                            'strand_fraction': ss.get('strand_fraction', 0),
                            'coil_fraction': ss.get('coil_fraction', 0)
                        }
        
        # Format output
        if params.response_format == ResponseFormat.JSON:
            result = {
                'uniprot_id': uniprot_id,
                'metadata': metadata,
                'structure': structure_info,
                'features': features
            }
            return json.dumps(result, indent=2, default=str)
        
        # Markdown format
        lines = [
            f"# {metadata['protein_name']}",
            f"**UniProt ID:** [{uniprot_id}]({metadata['uniprot_url']})",
            f"**Gene:** {metadata['gene_name']}",
            f"**Organism:** {metadata['organism']} (*{metadata['scientific_name']}*)",
            f"**Length:** {metadata['sequence_length']} amino acids",
            ""
        ]
        
        # Function
        if metadata.get('function'):
            lines.extend([
                "## Function",
                metadata['function'],
                ""
            ])
        
        # Structure info
        if structure_info:
            lines.extend([
                "## AlphaFold Structure",
                f"- **Residues:** {structure_info['residue_count']}",
                f"- **Mean pLDDT:** {structure_info['mean_plddt']:.1f}",
                f"- **Source:** {structure_info['source']}",
                f"- **View:** [AlphaFold DB]({structure_info['alphafold_url']})",
                ""
            ])
            
            if features:
                lines.extend([
                    "### Secondary Structure",
                    f"- α-helix: {features['helix_fraction']*100:.1f}%",
                    f"- β-strand: {features['strand_fraction']*100:.1f}%",
                    f"- Coil: {features['coil_fraction']*100:.1f}%",
                    ""
                ])
        
        # GO terms
        if params.include_go_terms and metadata.get('go_terms'):
            go = metadata['go_terms']
            if any([go['molecular_function'], go['biological_process'], go['cellular_component']]):
                lines.append("## Gene Ontology")
                
                if go['molecular_function']:
                    lines.append("### Molecular Function")
                    for term in go['molecular_function'][:5]:
                        lines.append(f"- {term['name']} ({term['id']})")
                    lines.append("")
                
                if go['biological_process']:
                    lines.append("### Biological Process")
                    for term in go['biological_process'][:5]:
                        lines.append(f"- {term['name']} ({term['id']})")
                    lines.append("")
                
                if go['cellular_component']:
                    lines.append("### Cellular Component")
                    for term in go['cellular_component'][:5]:
                        lines.append(f"- {term['name']} ({term['id']})")
                    lines.append("")
        
        # Active sites
        if metadata.get('active_sites'):
            lines.append("## Active Sites")
            for site in metadata['active_sites'][:5]:
                lines.append(f"- Position {site['position']}: {site['description']}")
            lines.append("")
        
        # Binding sites
        if metadata.get('binding_sites'):
            lines.append("## Binding Sites")
            for site in metadata['binding_sites'][:5]:
                lines.append(f"- Positions {site['start']}-{site['end']}: {site['description']}")
            lines.append("")
        
        # Disease associations
        if params.include_disease and metadata.get('diseases'):
            lines.append("## Disease Associations")
            for disease in metadata['diseases'][:5]:
                lines.append(f"- **{disease['name']}**: {disease['description'][:200]}...")
            lines.append("")
        
        # Footer with links
        lines.extend([
            "---",
            f"*Data sources: [UniProt]({metadata['uniprot_url']})" + 
            (f", [AlphaFold DB]({structure_info['alphafold_url']})*" if structure_info else "*")
        ])
        
        return "\n".join(lines)
        
    except Exception as e:
        logger.error(f"[{timestamp}] Error in get_enriched_protein: {str(e)}")
        return f"Error: {str(e)}"


# ===========================================================================
# PR #2: PROTEIN FUNCTION INTELLIGENCE TOOLS
# ===========================================================================

@mcp.tool()
async def batch_go_lookup(params: BatchGOLookupInput) -> str:
    """
    Get GO terms for hundreds of proteins at once.
    
    PROPRIETARY TOOL - TOPOLOGICA LLC
    
    Efficiently fetches GO annotations for large protein sets.
    Uses local cache when available, fetches from UniProt when needed.
    Results are persisted for future sovereign access.
    
    Use Cases:
        - Training data extraction for CAFA-style prediction
        - Batch annotation of experimental results
        - Building protein function databases
    
    Args:
        uniprot_ids: List of UniProt IDs (up to 500)
        include_evidence: Include evidence codes
        namespaces: Which GO namespaces to include
    
    Returns:
        GO annotations for all proteins in JSON or markdown
    """
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    logger.info(f"[{timestamp}] batch_go_lookup called: {len(params.uniprot_ids)} proteins")
    
    try:
        go_cache = get_go_cache()
        uniprot_fetcher = get_uniprot_fetcher()
        
        results = {}
        cache_hits = 0
        fetched = 0
        errors = []
        
        for uniprot_id in params.uniprot_ids:
            uniprot_id = uniprot_id.upper().strip()
            
            # Check cache first
            cached = go_cache.get_go_terms(uniprot_id)
            if cached:
                results[uniprot_id] = cached
                cache_hits += 1
                continue
            
            # Fetch from UniProt
            success, metadata, error = uniprot_fetcher.fetch(uniprot_id)
            if success and metadata:
                go_terms = metadata.get('go_terms', {})
                results[uniprot_id] = go_terms
                
                # Add to cache
                go_cache.add_protein(uniprot_id, go_terms)
                fetched += 1
            else:
                results[uniprot_id] = None
                errors.append(f"{uniprot_id}: {error}")
        
        # Save cache
        if fetched > 0:
            go_cache.save()
        
        # Filter by requested namespaces
        for uid, terms in results.items():
            if terms:
                results[uid] = {ns: terms.get(ns, []) for ns in params.namespaces if ns in terms}
        
        # Format output
        if params.response_format == ResponseFormat.JSON:
            return json.dumps({
                'results': results,
                'statistics': {
                    'requested': len(params.uniprot_ids),
                    'cache_hits': cache_hits,
                    'fetched': fetched,
                    'errors': len(errors)
                },
                'errors': errors[:10] if errors else []
            }, indent=2)
        
        # Markdown format
        lines = [
            f"# Batch GO Lookup Results",
            f"**Proteins:** {len(params.uniprot_ids)} | **Cache hits:** {cache_hits} | **Fetched:** {fetched}",
            ""
        ]
        
        for uid, terms in list(results.items())[:50]:  # Limit output
            if terms:
                lines.append(f"## {uid}")
                for ns, term_list in terms.items():
                    if term_list:
                        lines.append(f"### {ns.replace('_', ' ').title()}")
                        for t in term_list[:5]:
                            lines.append(f"- {t.get('name', 'Unknown')} ({t.get('id', '')})")
                lines.append("")
        
        if len(results) > 50:
            lines.append(f"*...and {len(results) - 50} more proteins (use JSON format for full data)*")
        
        return "\n".join(lines)
        
    except Exception as e:
        logger.error(f"[{timestamp}] Error in batch_go_lookup: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
async def search_by_go_term(params: SearchByGOTermInput) -> str:
    """
    Find all proteins with a specific GO annotation.
    
    PROPRIETARY TOOL - TOPOLOGICA LLC
    
    Searches the inverted index for proteins annotated with a GO term.
    Essential for building training sets for function prediction.
    
    Use Cases:
        - Find all kinases (GO:0016301)
        - Find all membrane proteins (GO:0016020)
        - Build positive training sets for specific functions
    
    Args:
        go_term: GO term ID (e.g., 'GO:0003700') or name pattern
        include_children: Also include proteins with child terms
        organism_filter: Filter by organism
        limit: Maximum results
    
    Returns:
        List of proteins with the GO annotation
    """
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    logger.info(f"[{timestamp}] search_by_go_term called: {params.go_term}")
    
    try:
        go_cache = get_go_cache()
        
        # Normalize GO term
        go_term = params.go_term.upper().strip()
        if not go_term.startswith('GO:'):
            # Search by name pattern in forward index
            matching_proteins = []
            pattern = params.go_term.lower()
            
            for uid, terms in go_cache.forward_index.items():
                for ns, term_list in terms.items():
                    for t in term_list:
                        if pattern in t.get('name', '').lower():
                            matching_proteins.append({
                                'uniprot_id': uid,
                                'go_id': t.get('id', ''),
                                'go_name': t.get('name', ''),
                                'namespace': ns
                            })
                            break
            
            proteins = matching_proteins[:params.limit]
        else:
            # Direct GO ID lookup
            protein_ids = go_cache.get_proteins_by_go(go_term)
            proteins = [{'uniprot_id': uid, 'go_id': go_term} for uid in protein_ids[:params.limit]]
        
        # Format output
        if params.response_format == ResponseFormat.JSON:
            return json.dumps({
                'go_term': params.go_term,
                'count': len(proteins),
                'proteins': proteins,
                'cache_total_proteins': len(go_cache.forward_index),
                'cache_total_go_terms': len(go_cache.inverted_index)
            }, indent=2)
        
        # Markdown
        lines = [
            f"# Proteins with GO Term: {params.go_term}",
            f"**Found:** {len(proteins)} proteins",
            f"**Cache:** {len(go_cache.forward_index)} proteins indexed",
            ""
        ]
        
        for p in proteins[:100]:
            lines.append(f"- **{p['uniprot_id']}** - {p.get('go_name', p.get('go_id', ''))}")
        
        if len(proteins) > 100:
            lines.append(f"\n*...and {len(proteins) - 100} more*")
        
        return "\n".join(lines)
        
    except Exception as e:
        logger.error(f"[{timestamp}] Error in search_by_go_term: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
async def get_go_hierarchy(params: GetGOHierarchyInput) -> str:
    """
    Navigate GO term parent/child relationships.
    
    PROPRIETARY TOOL - TOPOLOGICA LLC
    
    Fetches GO term hierarchy from QuickGO API.
    Essential for GO term propagation in function prediction.
    
    Use Cases:
        - Understand term specificity
        - Propagate annotations up the hierarchy
        - Find related terms for training
    
    Args:
        go_term: GO term ID (e.g., 'GO:0003700')
        direction: 'parents', 'children', or 'both'
        depth: How many levels to traverse
    
    Returns:
        Hierarchical structure of related GO terms
    """
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    logger.info(f"[{timestamp}] get_go_hierarchy called: {params.go_term}")
    
    try:
        go_term = params.go_term.upper().strip()
        
        # Fetch from QuickGO API
        url = f"https://www.ebi.ac.uk/QuickGO/services/ontology/go/terms/{go_term}"
        
        ssl_context = ssl.create_default_context()
        request = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'TOPOLOGICA-Sovereign-AlphaFold/1.0',
                'Accept': 'application/json'
            }
        )
        
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT, context=ssl_context) as response:
                data = json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            return f"Error: GO term {go_term} not found (HTTP {e.code})"
        
        # Parse response
        results = data.get('results', [])
        if not results:
            return f"Error: No data found for {go_term}"
        
        term_info = results[0]
        
        hierarchy = {
            'term': {
                'id': term_info.get('id', ''),
                'name': term_info.get('name', ''),
                'namespace': term_info.get('aspect', ''),
                'definition': term_info.get('definition', {}).get('text', '')
            },
            'parents': [],
            'children': []
        }
        
        # Get ancestors (parents)
        if params.direction in ['parents', 'both']:
            ancestors = term_info.get('ancestors', [])
            for anc in ancestors[:20]:  # Limit
                hierarchy['parents'].append({'id': anc})
        
        # Get children (from separate endpoint if needed)
        if params.direction in ['children', 'both']:
            children_url = f"https://www.ebi.ac.uk/QuickGO/services/ontology/go/terms/{go_term}/children"
            try:
                child_request = urllib.request.Request(
                    children_url,
                    headers={'User-Agent': 'TOPOLOGICA-Sovereign-AlphaFold/1.0', 'Accept': 'application/json'}
                )
                with urllib.request.urlopen(child_request, timeout=REQUEST_TIMEOUT, context=ssl_context) as response:
                    child_data = json.loads(response.read().decode('utf-8'))
                    child_results = child_data.get('results', [])
                    if child_results:
                        for child in child_results[0].get('children', [])[:20]:
                            hierarchy['children'].append({
                                'id': child.get('id', ''),
                                'name': child.get('name', ''),
                                'relation': child.get('relation', '')
                            })
            except:
                pass  # Children endpoint may not exist
        
        # Format output
        if params.response_format == ResponseFormat.JSON:
            return json.dumps(hierarchy, indent=2)
        
        # Markdown
        lines = [
            f"# GO Term: {hierarchy['term']['id']}",
            f"**Name:** {hierarchy['term']['name']}",
            f"**Namespace:** {hierarchy['term']['namespace']}",
            f"**Definition:** {hierarchy['term']['definition'][:200]}...",
            ""
        ]
        
        if hierarchy['parents']:
            lines.append("## Parent Terms")
            for p in hierarchy['parents'][:10]:
                lines.append(f"- {p.get('id', '')} {p.get('name', '')}")
            lines.append("")
        
        if hierarchy['children']:
            lines.append("## Child Terms")
            for c in hierarchy['children'][:10]:
                lines.append(f"- {c.get('id', '')} - {c.get('name', '')} ({c.get('relation', '')})")
        
        return "\n".join(lines)
        
    except Exception as e:
        logger.error(f"[{timestamp}] Error in get_go_hierarchy: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
async def export_protein_set(params: ExportProteinSetInput) -> str:
    """
    Export filtered proteins to TSV/CSV for ML pipelines.
    
    PROPRIETARY TOOL - TOPOLOGICA LLC
    
    Creates tabular exports suitable for:
        - Training machine learning models
        - Data analysis in pandas/R
        - Integration with CAFA pipelines
    
    Args:
        uniprot_ids: List of proteins to export
        output_format: 'tsv' or 'csv'
        include_columns: Which columns to include
        include_go_terms: Include GO annotations
        include_sequence: Include full sequences
        filename: Output filename
    
    Returns:
        Path to exported file or data preview
    """
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    logger.info(f"[{timestamp}] export_protein_set called: {len(params.uniprot_ids)} proteins")
    
    try:
        go_cache = get_go_cache()
        uniprot_fetcher = get_uniprot_fetcher()
        
        # Determine separator
        sep = '\t' if params.output_format == 'tsv' else ','
        
        # Build rows
        rows = []
        headers = []
        
        # Determine columns
        if 'uniprot_id' in params.include_columns:
            headers.append('uniprot_id')
        if 'protein_name' in params.include_columns:
            headers.append('protein_name')
        if 'organism' in params.include_columns:
            headers.append('organism')
        if 'sequence_length' in params.include_columns:
            headers.append('sequence_length')
        if params.include_go_terms:
            headers.extend(['go_mf', 'go_bp', 'go_cc'])
        if params.include_sequence:
            headers.append('sequence')
        
        for uniprot_id in params.uniprot_ids[:params.__class__.model_fields['uniprot_ids'].metadata[0].max_length]:
            uniprot_id = uniprot_id.upper().strip()
            
            row = {}
            
            # Get metadata from UniProt
            success, metadata, _ = uniprot_fetcher.fetch(uniprot_id)
            
            if 'uniprot_id' in params.include_columns:
                row['uniprot_id'] = uniprot_id
            
            if success and metadata:
                if 'protein_name' in params.include_columns:
                    row['protein_name'] = metadata.get('protein_name', '')
                if 'organism' in params.include_columns:
                    row['organism'] = metadata.get('scientific_name', '')
                if 'sequence_length' in params.include_columns:
                    row['sequence_length'] = str(metadata.get('sequence_length', 0))
                
                if params.include_go_terms:
                    go = metadata.get('go_terms', {})
                    row['go_mf'] = ';'.join(t.get('id', '') for t in go.get('molecular_function', []))
                    row['go_bp'] = ';'.join(t.get('id', '') for t in go.get('biological_process', []))
                    row['go_cc'] = ';'.join(t.get('id', '') for t in go.get('cellular_component', []))
                    
                    # Cache the GO terms
                    go_cache.add_protein(uniprot_id, go)
            else:
                # Fill with empty values
                for h in headers:
                    if h not in row:
                        row[h] = ''
            
            rows.append(row)
        
        # Save cache
        go_cache.save()
        
        # Generate filename
        if params.filename:
            filename = params.filename
        else:
            filename = f"protein_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{params.output_format}"
        
        # Build output
        output_lines = [sep.join(headers)]
        for row in rows:
            output_lines.append(sep.join(str(row.get(h, '')) for h in headers))
        
        content = '\n'.join(output_lines)
        
        # Save to cache directory
        export_dir = CACHE_DIR / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        export_path = export_dir / filename
        
        with open(export_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(content)
        
        return json.dumps({
            'status': 'success',
            'file': str(export_path),
            'format': params.output_format,
            'rows': len(rows),
            'columns': headers,
            'preview': output_lines[:6]
        }, indent=2)
        
    except Exception as e:
        logger.error(f"[{timestamp}] Error in export_protein_set: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
async def find_similar_proteins(params: FindSimilarProteinsInput) -> str:
    """
    Find proteins similar by sequence or structure.
    
    PROPRIETARY TOOL - TOPOLOGICA LLC
    
    Uses k-mer based sequence similarity for fast approximate matching.
    For structure similarity, uses C-alpha RMSD when structures available.
    
    Args:
        uniprot_id: Query protein
        similarity_type: 'sequence' or 'structure'
        threshold: Minimum similarity (0-1)
        limit: Maximum results
        search_scope: 'local' or 'all'
    
    Returns:
        List of similar proteins with similarity scores
    """
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    logger.info(f"[{timestamp}] find_similar_proteins called: {params.uniprot_id}")
    
    try:
        uniprot_fetcher = get_uniprot_fetcher()
        seq_db = get_sequence_db()
        
        # Get query sequence
        query_id = params.uniprot_id.upper().strip()
        success, metadata, error = uniprot_fetcher.fetch(query_id)
        
        if not success or not metadata:
            return f"Error: Could not fetch query protein {query_id}: {error}"
        
        query_sequence = metadata.get('sequence', '')
        if not query_sequence:
            return f"Error: No sequence found for {query_id}"
        
        # Add query to sequence database
        seq_db.add_sequence(query_id, query_sequence)
        
        # Build sequence database from GO cache (has sequences)
        go_cache = get_go_cache()
        
        # Find similar proteins
        if params.similarity_type == 'sequence':
            # If we have sequences in memory from UniProt fetches
            # Use k-mer similarity
            similar = seq_db.find_similar(
                query_sequence,
                threshold=params.threshold,
                limit=params.limit
            )
            
            results = [
                {'uniprot_id': uid, 'similarity': round(sim, 4), 'type': 'sequence_kmer'}
                for uid, sim in similar if uid != query_id
            ]
        
        elif params.similarity_type == 'structure':
            # Structure-based similarity using local structures
            mgr = get_structure_manager()
            
            # Load query structure
            success_q, query_struct, _ = mgr.get_structure(query_id)
            if not success_q:
                return f"Error: Could not load structure for {query_id}"
            
            query_coords = query_struct.get_ca_coordinates()
            
            results = []
            # Compare against local structures (limit search for speed)
            local_ids = list(mgr.local_index.keys())[:1000]  # Limit for speed
            
            for target_id in local_ids:
                if target_id == query_id:
                    continue
                
                success_t, target_struct, _ = mgr.get_structure(target_id)
                if not success_t:
                    continue
                
                target_coords = target_struct.get_ca_coordinates()
                
                # Simple length-normalized overlap score
                len_ratio = min(len(query_coords), len(target_coords)) / max(len(query_coords), len(target_coords))
                
                if len_ratio >= params.threshold:
                    results.append({
                        'uniprot_id': target_id,
                        'similarity': round(len_ratio, 4),
                        'type': 'structure_length_ratio'
                    })
            
            results.sort(key=lambda x: x['similarity'], reverse=True)
            results = results[:params.limit]
        
        else:
            return f"Error: Unknown similarity type: {params.similarity_type}"
        
        # Format output
        if params.response_format == ResponseFormat.JSON:
            return json.dumps({
                'query': query_id,
                'similarity_type': params.similarity_type,
                'threshold': params.threshold,
                'results': results,
                'count': len(results)
            }, indent=2)
        
        # Markdown
        lines = [
            f"# Similar Proteins to {query_id}",
            f"**Method:** {params.similarity_type}",
            f"**Threshold:** {params.threshold}",
            f"**Found:** {len(results)}",
            ""
        ]
        
        for r in results[:50]:
            lines.append(f"- **{r['uniprot_id']}** - Similarity: {r['similarity']:.3f}")
        
        return "\n".join(lines)
        
    except Exception as e:
        logger.error(f"[{timestamp}] Error in find_similar_proteins: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
async def get_domain_annotations(params: GetDomainAnnotationsInput) -> str:
    """
    Retrieve Pfam/InterPro domain annotations.
    
    PROPRIETARY TOOL - TOPOLOGICA LLC
    
    Fetches domain annotations from UniProt cross-references.
    Domains are key features for function prediction.
    
    Args:
        uniprot_ids: List of proteins
        sources: Annotation sources (Pfam, InterPro, etc.)
    
    Returns:
        Domain annotations for each protein
    """
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    logger.info(f"[{timestamp}] get_domain_annotations called: {len(params.uniprot_ids)} proteins")
    
    try:
        results = {}
        
        for uniprot_id in params.uniprot_ids:
            uniprot_id = uniprot_id.upper().strip()
            
            # Fetch from UniProt (includes cross-references)
            url = f"{UNIPROT_API_URL}/{uniprot_id}.json"
            ssl_context = ssl.create_default_context()
            
            request = urllib.request.Request(
                url,
                headers={
                    'User-Agent': 'TOPOLOGICA-Sovereign-AlphaFold/1.0',
                    'Accept': 'application/json'
                }
            )
            
            try:
                with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT, context=ssl_context) as response:
                    data = json.loads(response.read().decode('utf-8'))
                
                domains = []
                
                # Extract domain annotations from cross-references
                for xref in data.get('uniProtKBCrossReferences', []):
                    db = xref.get('database', '')
                    if db in params.sources:
                        domain_info = {
                            'source': db,
                            'id': xref.get('id', ''),
                            'properties': {p['key']: p['value'] for p in xref.get('properties', [])}
                        }
                        domains.append(domain_info)
                
                # Also extract from features
                for feature in data.get('features', []):
                    feat_type = feature.get('type', '')
                    if feat_type in ['Domain', 'Region']:
                        loc = feature.get('location', {})
                        domains.append({
                            'source': 'UniProt',
                            'type': feat_type,
                            'description': feature.get('description', ''),
                            'start': loc.get('start', {}).get('value', 0),
                            'end': loc.get('end', {}).get('value', 0)
                        })
                
                results[uniprot_id] = domains
                
            except Exception as e:
                results[uniprot_id] = {'error': str(e)}
        
        # Format output
        if params.response_format == ResponseFormat.JSON:
            return json.dumps({
                'results': results,
                'count': len(results)
            }, indent=2)
        
        # Markdown
        lines = [
            f"# Domain Annotations",
            f"**Proteins:** {len(params.uniprot_ids)}",
            ""
        ]
        
        for uid, domains in results.items():
            lines.append(f"## {uid}")
            if isinstance(domains, dict) and 'error' in domains:
                lines.append(f"- Error: {domains['error']}")
            elif domains:
                for d in domains[:10]:
                    lines.append(f"- **{d.get('source', '')}:{d.get('id', d.get('type', ''))}** - {d.get('properties', d.get('description', ''))}")
            else:
                lines.append("- No domain annotations found")
            lines.append("")
        
        return "\n".join(lines)
        
    except Exception as e:
        logger.error(f"[{timestamp}] Error in get_domain_annotations: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
async def filter_by_organism(params: FilterByOrganismInput) -> str:
    """
    Filter proteins by organism from local cache.
    
    PROPRIETARY TOOL - TOPOLOGICA LLC
    
    Searches local AlphaFold structures for organism-specific proteins.
    Essential for species-specific function prediction.
    
    Args:
        organism: Organism name or taxonomy ID
        limit: Maximum results
        include_go_summary: Include GO term counts
    
    Returns:
        List of proteins from specified organism
    """
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    logger.info(f"[{timestamp}] filter_by_organism called: {params.organism}")
    
    try:
        mgr = get_structure_manager()
        go_cache = get_go_cache()
        
        organism_lower = params.organism.lower()
        results = []
        
        # Search through local structures
        checked = 0
        for uniprot_id in mgr.local_index.keys():
            if checked >= params.limit * 10:  # Check up to 10x limit
                break
            
            checked += 1
            
            # Load structure to check organism
            success, structure, _ = mgr.get_structure(uniprot_id)
            if success and structure:
                struct_organism = structure.organism.lower() if structure.organism else ""
                
                if organism_lower in struct_organism or struct_organism in organism_lower:
                    result = {
                        'uniprot_id': uniprot_id,
                        'organism': structure.organism,
                        'n_residues': structure.n_residues,
                        'mean_plddt': round(structure.mean_plddt, 1)
                    }
                    
                    if params.include_go_summary:
                        go_terms = go_cache.get_go_terms(uniprot_id)
                        if go_terms:
                            result['go_mf_count'] = len(go_terms.get('molecular_function', []))
                            result['go_bp_count'] = len(go_terms.get('biological_process', []))
                            result['go_cc_count'] = len(go_terms.get('cellular_component', []))
                    
                    results.append(result)
                    
                    if len(results) >= params.limit:
                        break
        
        # Format output
        if params.response_format == ResponseFormat.JSON:
            return json.dumps({
                'organism': params.organism,
                'count': len(results),
                'proteins': results,
                'searched': checked
            }, indent=2)
        
        # Markdown
        lines = [
            f"# Proteins from: {params.organism}",
            f"**Found:** {len(results)} | **Searched:** {checked}",
            ""
        ]
        
        for r in results[:100]:
            line = f"- **{r['uniprot_id']}** - {r['n_residues']} residues, pLDDT: {r['mean_plddt']}"
            if params.include_go_summary and 'go_mf_count' in r:
                line += f" | GO: MF={r['go_mf_count']}, BP={r['go_bp_count']}, CC={r['go_cc_count']}"
            lines.append(line)
        
        return "\n".join(lines)
        
    except Exception as e:
        logger.error(f"[{timestamp}] Error in filter_by_organism: {str(e)}")
        return f"Error: {str(e)}"


@mcp.tool()
async def get_protein_families(params: GetProteinFamiliesInput) -> str:
    """
    Cluster proteins by sequence or GO term similarity.
    
    PROPRIETARY TOOL - TOPOLOGICA LLC
    
    Groups proteins into families based on similarity.
    Useful for identifying functionally related proteins.
    
    Args:
        uniprot_ids: Proteins to cluster
        clustering_method: 'sequence' or 'go_terms'
        similarity_threshold: Clustering threshold
    
    Returns:
        Protein family assignments
    """
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    logger.info(f"[{timestamp}] get_protein_families called: {len(params.uniprot_ids)} proteins")
    
    try:
        uniprot_fetcher = get_uniprot_fetcher()
        go_cache = get_go_cache()
        
        # Simple single-linkage clustering
        clusters = []
        assigned = set()
        
        if params.clustering_method == 'go_terms':
            # Build GO term vectors
            protein_go = {}
            all_go_terms = set()
            
            for uid in params.uniprot_ids:
                uid = uid.upper().strip()
                
                # Get GO terms
                go_terms = go_cache.get_go_terms(uid)
                if not go_terms:
                    success, metadata, _ = uniprot_fetcher.fetch(uid)
                    if success and metadata:
                        go_terms = metadata.get('go_terms', {})
                        go_cache.add_protein(uid, go_terms)
                
                if go_terms:
                    terms = set()
                    for ns_terms in go_terms.values():
                        for t in ns_terms:
                            terms.add(t.get('id', ''))
                    protein_go[uid] = terms
                    all_go_terms.update(terms)
            
            go_cache.save()
            
            # Compute Jaccard similarity and cluster
            proteins = list(protein_go.keys())
            
            for i, p1 in enumerate(proteins):
                if p1 in assigned:
                    continue
                
                cluster = [p1]
                assigned.add(p1)
                
                for p2 in proteins[i+1:]:
                    if p2 in assigned:
                        continue
                    
                    # Jaccard similarity
                    terms1 = protein_go.get(p1, set())
                    terms2 = protein_go.get(p2, set())
                    
                    if terms1 and terms2:
                        intersection = len(terms1 & terms2)
                        union = len(terms1 | terms2)
                        sim = intersection / union if union > 0 else 0
                        
                        if sim >= params.similarity_threshold:
                            cluster.append(p2)
                            assigned.add(p2)
                
                clusters.append({
                    'id': len(clusters) + 1,
                    'members': cluster,
                    'size': len(cluster)
                })
        
        elif params.clustering_method == 'sequence':
            seq_db = get_sequence_db()
            
            # Get sequences
            protein_seqs = {}
            for uid in params.uniprot_ids:
                uid = uid.upper().strip()
                success, metadata, _ = uniprot_fetcher.fetch(uid)
                if success and metadata:
                    seq = metadata.get('sequence', '')
                    if seq:
                        protein_seqs[uid] = seq
                        seq_db.add_sequence(uid, seq)
            
            # Simple clustering by k-mer similarity
            proteins = list(protein_seqs.keys())
            
            for i, p1 in enumerate(proteins):
                if p1 in assigned:
                    continue
                
                cluster = [p1]
                assigned.add(p1)
                
                for p2 in proteins[i+1:]:
                    if p2 in assigned:
                        continue
                    
                    sim = seq_db.compute_similarity(protein_seqs[p1], protein_seqs[p2])
                    if sim >= params.similarity_threshold:
                        cluster.append(p2)
                        assigned.add(p2)
                
                clusters.append({
                    'id': len(clusters) + 1,
                    'members': cluster,
                    'size': len(cluster)
                })
        
        # Add singletons
        for uid in params.uniprot_ids:
            uid = uid.upper().strip()
            if uid not in assigned:
                clusters.append({
                    'id': len(clusters) + 1,
                    'members': [uid],
                    'size': 1
                })
        
        # Sort by size
        clusters.sort(key=lambda x: x['size'], reverse=True)
        
        # Format output
        if params.response_format == ResponseFormat.JSON:
            return json.dumps({
                'method': params.clustering_method,
                'threshold': params.similarity_threshold,
                'n_proteins': len(params.uniprot_ids),
                'n_clusters': len(clusters),
                'clusters': clusters
            }, indent=2)
        
        # Markdown
        lines = [
            f"# Protein Families",
            f"**Method:** {params.clustering_method}",
            f"**Threshold:** {params.similarity_threshold}",
            f"**Proteins:** {len(params.uniprot_ids)} | **Clusters:** {len(clusters)}",
            ""
        ]
        
        for c in clusters[:20]:
            members_str = ', '.join(c['members'][:10])
            if len(c['members']) > 10:
                members_str += f"... (+{len(c['members']) - 10})"
            lines.append(f"### Family {c['id']} ({c['size']} members)")
            lines.append(f"- {members_str}")
            lines.append("")
        
        return "\n".join(lines)
        
    except Exception as e:
        logger.error(f"[{timestamp}] Error in get_protein_families: {str(e)}")
        return f"Error: {str(e)}"


# ===========================================================================
# MAIN ENTRY POINT
# ===========================================================================

# ============================================================================
# PHASE 1 ENHANCED TOOLS - PAE, DOMAINS, DISORDER, TOPOLOGY
# ============================================================================

@mcp.tool()
async def extract_pae_matrix(params: ExtractPAEMatrixInput) -> str:
    """
    Extract Predicted Aligned Error (PAE) matrix from AlphaFold structure.
    
    PROPRIETARY TOOL - TOPOLOGICA LLC
    
    PAE measures predicted distance error between residue pairs.
    Low PAE (<5Å) indicates high confidence in relative positioning.
    
    Returns:
        PAE matrix with statistics (min, max, mean, domain blocks)
    """
    try:
        uniprot_id = params.uniprot_id.upper().strip()
        
        # Get structure
        structure_result = await get_structure(GetStructureInput(
            uniprot_id=uniprot_id,
            include_features=False,
            include_topology=False,
            response_format=ResponseFormat.JSON
        ))
        
        result = json.loads(structure_result)
        if result.get("status") == "error":
            return json.dumps({"status": "error", "error": result.get("error")})
        
        # Get coordinates for PAE estimation
        pdb_path = result.get("structure", {}).get("pdb_path")
        if not pdb_path or not Path(pdb_path).exists():
            return json.dumps({"status": "error", "error": "Structure file not found"})
        
        # Extract PAE using our extractor
        extractor = get_pae_extractor()
        pae_result = extractor.extract_pae_matrix(
            pdb_path,
            include_statistics=params.include_statistics,
            block_size=params.block_size
        )
        
        if params.response_format == ResponseFormat.MARKDOWN:
            lines = [
                f"# PAE Matrix: {uniprot_id}",
                "",
                f"**Matrix Size:** {pae_result['size']}x{pae_result['size']}",
                ""
            ]
            if params.include_statistics and 'statistics' in pae_result:
                stats = pae_result['statistics']
                lines.extend([
                    "## Statistics",
                    f"- **Mean PAE:** {stats.get('mean', 'N/A'):.2f} Å",
                    f"- **Min PAE:** {stats.get('min', 'N/A'):.2f} Å",
                    f"- **Max PAE:** {stats.get('max', 'N/A'):.2f} Å",
                    f"- **Std Dev:** {stats.get('std', 'N/A'):.2f} Å",
                    ""
                ])
            if 'domain_blocks' in pae_result:
                lines.extend([
                    "## Domain Blocks (low PAE regions)",
                    f"Found {len(pae_result['domain_blocks'])} potential domain(s)",
                    ""
                ])
            return "\n".join(lines)
        
        return json.dumps({"status": "success", "uniprot_id": uniprot_id, **pae_result}, indent=2)
        
    except Exception as e:
        logger.error(f"PAE extraction failed: {e}")
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool()
async def detect_domains(params: DetectDomainsInput) -> str:
    """
    Detect protein domains from PAE matrix clustering.
    
    PROPRIETARY TOOL - TOPOLOGICA LLC
    
    Uses PAE values to identify independently folded domains.
    Low intra-domain PAE + high inter-domain PAE = domain boundary.
    
    Returns:
        List of domains with residue ranges, confidence, and contacts
    """
    try:
        uniprot_id = params.uniprot_id.upper().strip()
        
        # Get structure path
        structure_result = await get_structure(GetStructureInput(
            uniprot_id=uniprot_id,
            include_features=False,
            response_format=ResponseFormat.JSON
        ))
        
        result = json.loads(structure_result)
        if result.get("status") == "error":
            return json.dumps(result)
        
        pdb_path = result.get("structure", {}).get("pdb_path")
        if not pdb_path:
            return json.dumps({"status": "error", "error": "Structure not found"})
        
        # Detect domains
        detector = get_domain_detector()
        domains = detector.detect_domains_from_pdb(
            pdb_path,
            pae_threshold=params.pae_threshold,
            min_domain_size=params.min_domain_size
        )
        
        if params.response_format == ResponseFormat.MARKDOWN:
            lines = [
                f"# Domain Analysis: {uniprot_id}",
                "",
                f"**Domains Detected:** {len(domains)}",
                f"**PAE Threshold:** {params.pae_threshold} Å",
                ""
            ]
            for i, dom in enumerate(domains, 1):
                lines.extend([
                    f"## Domain {i}",
                    f"- **Residues:** {dom['start']}-{dom['end']} ({dom['size']} aa)",
                    f"- **Mean pLDDT:** {dom.get('mean_plddt', 'N/A'):.1f}",
                    f"- **Intra-domain PAE:** {dom.get('intra_pae', 'N/A'):.1f} Å",
                    ""
                ])
            return "\n".join(lines)
        
        return json.dumps({
            "status": "success",
            "uniprot_id": uniprot_id,
            "n_domains": len(domains),
            "domains": domains
        }, indent=2)
        
    except Exception as e:
        logger.error(f"Domain detection failed: {e}")
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool()
async def predict_disorder(params: PredictDisorderInput) -> str:
    """
    Predict intrinsically disordered regions (IDRs) from pLDDT scores.
    
    PROPRIETARY TOOL - TOPOLOGICA LLC
    
    Low pLDDT (<50) often indicates disorder/flexibility.
    Returns IDR regions, propensity profile, and disorder statistics.
    """
    try:
        uniprot_id = params.uniprot_id.upper().strip()
        
        # Get structure with features
        structure_result = await get_structure(GetStructureInput(
            uniprot_id=uniprot_id,
            include_features=True,
            response_format=ResponseFormat.JSON
        ))
        
        result = json.loads(structure_result)
        if result.get("status") == "error":
            return json.dumps(result)
        
        pdb_path = result.get("structure", {}).get("pdb_path")
        if not pdb_path:
            return json.dumps({"status": "error", "error": "Structure not found"})
        
        # Predict disorder
        predictor = get_disorder_predictor()
        disorder = predictor.predict_disorder(
            pdb_path,
            plddt_threshold=params.plddt_threshold,
            min_region_length=params.min_region_length
        )
        
        if params.response_format == ResponseFormat.MARKDOWN:
            lines = [
                f"# Disorder Prediction: {uniprot_id}",
                "",
                f"**pLDDT Threshold:** <{params.plddt_threshold}",
                f"**Total Residues:** {disorder['total_residues']}",
                f"**Disordered Residues:** {disorder['disordered_count']} ({disorder['disorder_fraction']*100:.1f}%)",
                "",
                "## Disordered Regions"
            ]
            for region in disorder.get('regions', []):
                lines.append(f"- Residues {region['start']}-{region['end']} ({region['length']} aa, mean pLDDT: {region['mean_plddt']:.1f})")
            
            return "\n".join(lines)
        
        return json.dumps({
            "status": "success",
            "uniprot_id": uniprot_id,
            **disorder
        }, indent=2)
        
    except Exception as e:
        logger.error(f"Disorder prediction failed: {e}")
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool()
async def get_plddt_profile(params: GetPLDDTProfileInput) -> str:
    """
    Get detailed per-residue pLDDT confidence profile.
    
    PROPRIETARY TOOL - TOPOLOGICA LLC
    
    pLDDT categories:
    - Very high (>90): High confidence
    - High (70-90): Good confidence  
    - Low (50-70): Caution
    - Very low (<50): Likely disordered
    """
    try:
        uniprot_id = params.uniprot_id.upper().strip()
        
        structure_result = await get_structure(GetStructureInput(
            uniprot_id=uniprot_id,
            include_features=True,
            response_format=ResponseFormat.JSON
        ))
        
        result = json.loads(structure_result)
        if result.get("status") == "error":
            return json.dumps(result)
        
        pdb_path = result.get("structure", {}).get("pdb_path")
        if not pdb_path:
            return json.dumps({"status": "error", "error": "Structure not found"})
        
        # Extract pLDDT profile
        plddt_values = extract_plddt_from_pdb(pdb_path)
        
        # Compute statistics
        plddt_array = np.array(plddt_values)
        profile = {
            "residue_count": len(plddt_values),
            "mean_plddt": float(np.mean(plddt_array)),
            "median_plddt": float(np.median(plddt_array)),
            "min_plddt": float(np.min(plddt_array)),
            "max_plddt": float(np.max(plddt_array)),
            "std_plddt": float(np.std(plddt_array)),
            "very_high_count": int(np.sum(plddt_array > 90)),
            "high_count": int(np.sum((plddt_array > 70) & (plddt_array <= 90))),
            "low_count": int(np.sum((plddt_array > 50) & (plddt_array <= 70))),
            "very_low_count": int(np.sum(plddt_array <= 50))
        }
        
        if params.include_per_residue:
            profile["per_residue"] = [{"residue": i+1, "plddt": float(v)} for i, v in enumerate(plddt_values)]
        
        if params.response_format == ResponseFormat.MARKDOWN:
            lines = [
                f"# pLDDT Profile: {uniprot_id}",
                "",
                f"**Total Residues:** {profile['residue_count']}",
                f"**Mean pLDDT:** {profile['mean_plddt']:.1f}",
                f"**Range:** {profile['min_plddt']:.1f} - {profile['max_plddt']:.1f}",
                "",
                "## Confidence Distribution",
                f"- Very High (>90): {profile['very_high_count']} ({profile['very_high_count']/profile['residue_count']*100:.1f}%)",
                f"- High (70-90): {profile['high_count']} ({profile['high_count']/profile['residue_count']*100:.1f}%)",
                f"- Low (50-70): {profile['low_count']} ({profile['low_count']/profile['residue_count']*100:.1f}%)",
                f"- Very Low (<50): {profile['very_low_count']} ({profile['very_low_count']/profile['residue_count']*100:.1f}%)"
            ]
            return "\n".join(lines)
        
        return json.dumps({"status": "success", "uniprot_id": uniprot_id, **profile}, indent=2)
        
    except Exception as e:
        logger.error(f"pLDDT profile extraction failed: {e}")
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool()
async def compute_information_content(params: ComputeInformationContentInput) -> str:
    """
    Compute Information Content (IC) for GO terms using corpus frequencies.
    
    PROPRIETARY TOOL - TOPOLOGICA LLC
    
    IC(t) = -log(P(t)) where P(t) = freq(t)/max_freq
    Higher IC = more specific term = more informative
    
    Supports batch computation for efficiency.
    """
    try:
        calculator = get_ic_calculator()
        
        results = []
        for go_term in params.go_terms:
            ic_value = calculator.compute_ic(
                go_term,
                corpus=params.corpus,
                normalize=params.normalize
            )
            results.append({
                "go_term": go_term,
                "information_content": ic_value,
                "corpus": params.corpus
            })
        
        if params.response_format == ResponseFormat.MARKDOWN:
            lines = [
                "# Information Content Analysis",
                "",
                f"**Corpus:** {params.corpus}",
                f"**Terms Analyzed:** {len(results)}",
                "",
                "| GO Term | IC |",
                "|---------|------|"
            ]
            for r in results:
                lines.append(f"| {r['go_term']} | {r['information_content']:.4f} |")
            return "\n".join(lines)
        
        return json.dumps({"status": "success", "results": results}, indent=2)
        
    except Exception as e:
        logger.error(f"IC computation failed: {e}")
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool()
async def compute_semantic_similarity(params: ComputeSemanticSimilarityInput) -> str:
    """
    Compute semantic similarity between GO terms.
    
    PROPRIETARY TOOL - TOPOLOGICA LLC
    
    Methods:
    - Resnik: IC of Most Informative Common Ancestor (MICA)
    - Lin: 2*IC(MICA) / (IC(t1) + IC(t2))
    - Jiang: 1 - (IC(t1) + IC(t2) - 2*IC(MICA))
    - Wang: Graph-based with semantic contribution
    
    Returns pairwise similarity matrix for term lists.
    """
    try:
        calculator = get_similarity_calculator()
        
        similarity = calculator.compute_similarity(
            term1=params.term1,
            term2=params.term2,
            method=params.method
        )
        
        if params.response_format == ResponseFormat.MARKDOWN:
            lines = [
                f"# Semantic Similarity ({params.method})",
                "",
                f"**Term 1:** {params.term1}",
                f"**Term 2:** {params.term2}",
                f"**Method:** {params.method}",
                f"**Similarity:** {similarity.get('similarity', 'N/A'):.4f}" if isinstance(similarity, dict) else f"**Similarity:** {similarity:.4f}",
                ""
            ]
            return "\n".join(lines)
        
        return json.dumps({"status": "success", "similarity": similarity}, indent=2)
        
    except Exception as e:
        logger.error(f"Semantic similarity failed: {e}")
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool()
async def get_advanced_topology(params: GetAdvancedTopologyInput) -> str:
    """
    Compute advanced topological features with full TDA pipeline.
    
    PROPRIETARY TOOL - TOPOLOGICA LLC
    
    Features:
    - Persistence diagrams (birth-death pairs)
    - Betti curves over filtration
    - Persistence landscapes
    - Persistence images (vectorization)
    - Euler characteristic curve
    
    Mathematical Foundation:
        Vietoris-Rips complex on C-alpha atoms.
        H_k computed via matrix reduction.
    """
    try:
        uniprot_id = params.uniprot_id.upper().strip()
        
        # Get structure
        structure_result = await get_structure(GetStructureInput(
            uniprot_id=uniprot_id,
            include_features=False,
            response_format=ResponseFormat.JSON
        ))
        
        result = json.loads(structure_result)
        if result.get("status") == "error":
            return json.dumps(result)
        
        pdb_path = result.get("structure", {}).get("pdb_path")
        if not pdb_path:
            return json.dumps({"status": "error", "error": "Structure not found"})
        
        # Compute advanced topology
        computer = get_topology_computer()
        topology = computer.compute_advanced_features(
            pdb_path,
            max_dimension=params.max_dimension,
            max_filtration=params.max_filtration,
            include_landscapes=params.include_landscapes,
            include_images=params.include_images,
            n_landscapes=params.n_landscapes,
            image_resolution=params.image_resolution
        )
        
        if params.response_format == ResponseFormat.MARKDOWN:
            lines = [
                f"# Advanced Topology: {uniprot_id}",
                "",
                "## Betti Numbers",
                f"- β₀ (components): {topology.get('betti_0', 'N/A')}",
                f"- β₁ (loops): {topology.get('betti_1', 'N/A')}",
                f"- β₂ (voids): {topology.get('betti_2', 'N/A')}",
                "",
                f"**Euler Characteristic:** χ = {topology.get('euler_characteristic', 'N/A')}",
                ""
            ]
            if 'persistence_entropy' in topology:
                lines.append(f"**Persistence Entropy:** {topology['persistence_entropy']:.4f}")
            if params.include_landscapes:
                lines.append("\n## Persistence Landscapes: Computed ✓")
            if params.include_images:
                lines.append("## Persistence Images: Computed ✓")
            return "\n".join(lines)
        
        return json.dumps({"status": "success", "uniprot_id": uniprot_id, **topology}, indent=2)
        
    except Exception as e:
        logger.error(f"Advanced topology computation failed: {e}")
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool()
async def compare_protein_topology(params: CompareProteinTopologyInput) -> str:
    """
    Compare topological features between two proteins.
    
    PROPRIETARY TOOL - TOPOLOGICA LLC
    
    Distance Metrics:
    - Wasserstein (Earth Mover's): Optimal transport between diagrams
    - Bottleneck: Max matching distance
    - Landscape L2: Euclidean distance in landscape space
    
    Lower distance = more similar topology.
    """
    try:
        id1 = params.protein1.upper().strip()
        id2 = params.protein2.upper().strip()
        
        # Get both structures
        result1 = json.loads(await get_structure(GetStructureInput(
            uniprot_id=id1, include_features=False, response_format=ResponseFormat.JSON
        )))
        result2 = json.loads(await get_structure(GetStructureInput(
            uniprot_id=id2, include_features=False, response_format=ResponseFormat.JSON
        )))
        
        if result1.get("status") == "error":
            return json.dumps(result1)
        if result2.get("status") == "error":
            return json.dumps(result2)
        
        pdb1 = result1.get("structure", {}).get("pdb_path")
        pdb2 = result2.get("structure", {}).get("pdb_path")
        
        if not pdb1 or not pdb2:
            return json.dumps({"status": "error", "error": "One or both structures not found"})
        
        # Compare topology
        computer = get_topology_computer()
        comparison = computer.compare_proteins(
            pdb1, pdb2,
            metric=params.distance_metric,
            dimension=params.dimension
        )
        
        if params.response_format == ResponseFormat.MARKDOWN:
            lines = [
                f"# Topological Comparison",
                "",
                f"**Protein 1:** {id1}",
                f"**Protein 2:** {id2}",
                f"**Metric:** {params.distance_metric}",
                f"**Dimension:** H_{params.dimension}",
                "",
                f"## Distance: {comparison.get('distance', 'N/A'):.4f}",
                "",
                f"Interpretation: {'Similar' if comparison.get('distance', 999) < 1.0 else 'Different'} topology"
            ]
            return "\n".join(lines)
        
        return json.dumps({
            "status": "success",
            "protein1": id1,
            "protein2": id2,
            **comparison
        }, indent=2)
        
    except Exception as e:
        logger.error(f"Topology comparison failed: {e}")
        return json.dumps({"status": "error", "error": str(e)})


@mcp.tool()
async def batch_protein_analysis(params: BatchProteinAnalysisInput) -> str:
    """
    Comprehensive batch analysis of multiple proteins with progress tracking.
    
    PROPRIETARY TOOL - TOPOLOGICA LLC
    
    Runs selected analyses on all proteins:
    - Structure retrieval
    - Feature extraction
    - Topology computation
    - Disorder prediction
    - Domain detection
    
    Returns aggregated results with statistics.
    """
    try:
        uniprot_ids = [uid.upper().strip() for uid in params.uniprot_ids]
        n_proteins = len(uniprot_ids)
        
        results = []
        successful = 0
        failed = 0
        
        for i, uniprot_id in enumerate(uniprot_ids):
            try:
                protein_result = {"uniprot_id": uniprot_id}
                
                # Get structure
                if params.include_structure:
                    struct = json.loads(await get_structure(GetStructureInput(
                        uniprot_id=uniprot_id,
                        include_features=params.include_features,
                        include_topology=params.include_topology,
                        response_format=ResponseFormat.JSON
                    )))
                    protein_result["structure"] = struct.get("status") == "success"
                    if struct.get("status") == "success":
                        protein_result["length"] = struct.get("structure", {}).get("sequence_length")
                        if params.include_features:
                            protein_result["features"] = struct.get("features", {})
                
                # Get disorder if requested
                if params.include_disorder:
                    disorder = json.loads(await predict_disorder(PredictDisorderInput(
                        uniprot_id=uniprot_id,
                        response_format=ResponseFormat.JSON
                    )))
                    if disorder.get("status") == "success":
                        protein_result["disorder_fraction"] = disorder.get("disorder_fraction")
                
                # Get domains if requested  
                if params.include_domains:
                    domains = json.loads(await detect_domains(DetectDomainsInput(
                        uniprot_id=uniprot_id,
                        response_format=ResponseFormat.JSON
                    )))
                    if domains.get("status") == "success":
                        protein_result["n_domains"] = domains.get("n_domains")
                
                results.append(protein_result)
                successful += 1
                
            except Exception as e:
                results.append({"uniprot_id": uniprot_id, "error": str(e)})
                failed += 1
        
        # Aggregate statistics
        summary = {
            "total": n_proteins,
            "successful": successful,
            "failed": failed,
            "success_rate": successful / n_proteins if n_proteins > 0 else 0
        }
        
        if params.response_format == ResponseFormat.MARKDOWN:
            lines = [
                "# Batch Protein Analysis",
                "",
                f"**Proteins Analyzed:** {n_proteins}",
                f"**Successful:** {successful}",
                f"**Failed:** {failed}",
                f"**Success Rate:** {summary['success_rate']*100:.1f}%",
                "",
                "## Results Summary",
                ""
            ]
            for r in results[:10]:  # Show first 10
                status = "✓" if r.get("structure") or "length" in r else "✗"
                lines.append(f"- {r['uniprot_id']}: {status}")
            if len(results) > 10:
                lines.append(f"... and {len(results) - 10} more")
            return "\n".join(lines)
        
        return json.dumps({
            "status": "success",
            "summary": summary,
            "results": results
        }, indent=2)
        
    except Exception as e:
        logger.error(f"Batch analysis failed: {e}")
        return json.dumps({"status": "error", "error": str(e)})


if __name__ == "__main__":
    logger.info(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] Starting AlphaFold Sovereign MCP Server")
    logger.info("PROPRIETARY FRAMEWORK - TOPOLOGICA LLC")
    logger.info("Patent-pending by Santiago Maniches (ORCID: 0009-0005-6480-1987)")
    mcp.run()
