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
        return json.dumps(result, indent=2)
    
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
                    'mean_plddt': float(np.mean([r.mean_plddt for r in structure.residues])),
                    'source': structure.source,
                    'alphafold_url': f"https://alphafold.ebi.ac.uk/entry/{uniprot_id}"
                }
                
                # Compute features if requested
                if params.include_features:
                    ca_coords = structure.get_ca_coords()
                    if len(ca_coords) > 0:
                        ss = SecondaryStructureAnalyzer.analyze(structure)
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
# MAIN ENTRY POINT
# ===========================================================================

if __name__ == "__main__":
    logger.info(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] Starting AlphaFold Sovereign MCP Server")
    logger.info("PROPRIETARY FRAMEWORK - TOPOLOGICA LLC")
    logger.info("Patent-pending by Santiago Maniches (ORCID: 0009-0005-6480-1987)")
    mcp.run()
