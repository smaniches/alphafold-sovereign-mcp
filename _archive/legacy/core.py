# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""
Sovereign AlphaFold Connector - Core Module
============================================

Main interface for sovereign AlphaFold structure access.
Filesystem-first, no API dependencies.

Patent-pending framework by Santiago Maniches (ORCID: 0009-0005-6480-1987)
TOPOLOGICA LLC
"""

from typing import Dict, List, Optional, Set, Tuple, Any, Iterator
import numpy as np
import numpy.typing as npt
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog
import pickle
import json

from .parsers import PDBParser, AlphaFoldStructure, AlphaFoldMetadata

logger = structlog.get_logger(__name__)


@dataclass
class SovereignAlphaFoldConfig:
    """
    Configuration for sovereign AlphaFold connector.
    
    All paths are filesystem-based - no API endpoints.
    """
    structures_dir: Path
    cache_dir: Path
    index_file: Optional[Path] = None
    
    # Performance settings
    lazy_loading: bool = True
    precompute_features: bool = False
    batch_size: int = 1000
    
    # Validation settings
    verify_integrity: bool = True
    min_plddt_threshold: float = 0.0
    
    def __post_init__(self):
        self.structures_dir = Path(self.structures_dir)
        self.cache_dir = Path(self.cache_dir)
        if self.index_file:
            self.index_file = Path(self.index_file)


@dataclass
class StructureIndex:
    """
    Index of available AlphaFold structures.
    
    Enables O(1) lookup without loading all structures.
    """
    uniprot_ids: Set[str]
    file_paths: Dict[str, Path]
    metadata_cache: Dict[str, Dict[str, Any]]
    statistics: Dict[str, Any]
    created_at: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'uniprot_ids': list(self.uniprot_ids),
            'file_paths': {k: str(v) for k, v in self.file_paths.items()},
            'metadata_cache': self.metadata_cache,
            'statistics': self.statistics,
            'created_at': self.created_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StructureIndex':
        return cls(
            uniprot_ids=set(data['uniprot_ids']),
            file_paths={k: Path(v) for k, v in data['file_paths'].items()},
            metadata_cache=data['metadata_cache'],
            statistics=data['statistics'],
            created_at=data['created_at']
        )


class SovereignAlphaFoldConnector:
    """
    Sovereign connector for AlphaFold structure data.
    
    Design Principles:
        1. FILESYSTEM-FIRST: All data from local files, no API
        2. LAZY LOADING: Load structures on demand
        3. INDEXED ACCESS: O(1) structure lookup
        4. CACHED FEATURES: Precomputed features for performance
        5. DETERMINISTIC: Same input → same output
    
    Mathematical Foundation:
        Protein structure P exists in configuration space M
        P: sequence → (R³)^N where N = number of atoms
        Topological features: H_k(P) persistent homology
    
    Patent Notice:
        Sovereign AlphaFold connector framework is patent-pending
        intellectual property of Santiago Maniches
        (ORCID: 0009-0005-6480-1987)
    """
    
    def __init__(
        self,
        config: Optional[SovereignAlphaFoldConfig] = None,
        structures_dir: Optional[Path] = None,
        cache_dir: Optional[Path] = None,
        seed: int = 42
    ):
        """
        Initialize sovereign AlphaFold connector.
        
        Args:
            config: Full configuration object
            structures_dir: Path to PDB files (alternative to config)
            cache_dir: Path to cache directory (alternative to config)
            seed: Random seed for deterministic behavior
        """
        self.seed = seed
        np.random.seed(seed)
        
        # Initialize configuration
        if config:
            self.config = config
        elif structures_dir and cache_dir:
            self.config = SovereignAlphaFoldConfig(
                structures_dir=structures_dir,
                cache_dir=cache_dir
            )
        else:
            # Default to CAFA-6 paths
            self.config = SovereignAlphaFoldConfig(
                structures_dir=Path(r"C:\TOPOLOGICA_KAGGLE_CAFA6\ALPHAFOLD2_STRUCTURES\pdb_files"),
                cache_dir=Path(r"C:\TOPOLOGICA_KAGGLE_CAFA6\CACHE")
            )
        
        # Initialize parser
        self.parser = PDBParser(
            structures_dir=self.config.structures_dir,
            seed=seed
        )
        
        # Index and cache
        self._index: Optional[StructureIndex] = None
        self._structure_cache: Dict[str, AlphaFoldStructure] = {}
        
        # Initialize
        self._initialize()
    
    def _initialize(self) -> None:
        """Initialize connector - build or load index."""
        start_time = datetime.now(timezone.utc)
        
        logger.info(
            "connector_initializing",
            timestamp=start_time.isoformat(),
            structures_dir=str(self.config.structures_dir),
            cache_dir=str(self.config.cache_dir)
        )
        
        # Validate directories
        if not self.config.structures_dir.exists():
            raise FileNotFoundError(
                f"Structures directory not found: {self.config.structures_dir}"
            )
        
        self.config.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Load or build index
        index_path = self.config.cache_dir / "alphafold_sovereign_index.pkl"
        
        if index_path.exists():
            self._load_index(index_path)
        else:
            self._build_index()
            self._save_index(index_path)
        
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        
        logger.info(
            "connector_initialized",
            n_structures=len(self._index.uniprot_ids),
            duration_seconds=duration,
            index_path=str(index_path)
        )
    
    def _build_index(self) -> None:
        """Build index of all available structures."""
        start_time = datetime.now(timezone.utc)
        
        logger.info("building_structure_index")
        
        pdb_files = list(self.config.structures_dir.glob("*.pdb"))
        
        uniprot_ids: Set[str] = set()
        file_paths: Dict[str, Path] = {}
        
        for pdb_file in pdb_files:
            uniprot_id = pdb_file.stem
            uniprot_ids.add(uniprot_id)
            file_paths[uniprot_id] = pdb_file
        
        statistics = {
            'total_structures': len(uniprot_ids),
            'structures_dir': str(self.config.structures_dir),
            'build_timestamp': start_time.isoformat()
        }
        
        self._index = StructureIndex(
            uniprot_ids=uniprot_ids,
            file_paths=file_paths,
            metadata_cache={},
            statistics=statistics,
            created_at=start_time.isoformat()
        )
        
        logger.info(
            "index_built",
            n_structures=len(uniprot_ids)
        )
    
    def _load_index(self, path: Path) -> None:
        """Load index from cache."""
        with open(path, 'rb') as f:
            data = pickle.load(f)
        self._index = StructureIndex.from_dict(data)
        logger.info("index_loaded", n_structures=len(self._index.uniprot_ids))
    
    def _save_index(self, path: Path) -> None:
        """Save index to cache."""
        with open(path, 'wb') as f:
            pickle.dump(self._index.to_dict(), f)
        logger.info("index_saved", path=str(path))
    
    # =====================================================================
    # PUBLIC API - Structure Access
    # =====================================================================
    
    @property
    def available_ids(self) -> Set[str]:
        """Get set of all available UniProt IDs."""
        return self._index.uniprot_ids
    
    @property
    def n_structures(self) -> int:
        """Total number of available structures."""
        return len(self._index.uniprot_ids)
    
    def has_structure(self, uniprot_id: str) -> bool:
        """
        Check if structure exists for UniProt ID.
        
        Time Complexity: O(1) via hash set lookup
        """
        return uniprot_id in self._index.uniprot_ids
    
    def get_structure(
        self,
        uniprot_id: str,
        use_cache: bool = True
    ) -> AlphaFoldStructure:
        """
        Get AlphaFold structure by UniProt ID.
        
        Args:
            uniprot_id: UniProt accession (e.g., 'P12345')
            use_cache: Use in-memory cache if available
        
        Returns:
            Complete AlphaFoldStructure with atoms, residues, metadata
        
        Raises:
            KeyError: If structure not found
        
        Time Complexity:
            Cache hit: O(1)
            Cache miss: O(n) where n = number of atoms
        """
        if uniprot_id not in self._index.uniprot_ids:
            raise KeyError(f"Structure not found for: {uniprot_id}")
        
        # Check cache
        if use_cache and uniprot_id in self._structure_cache:
            return self._structure_cache[uniprot_id]
        
        # Load from filesystem
        file_path = self._index.file_paths[uniprot_id]
        structure = self.parser.parse_file(file_path)
        
        # Cache if enabled
        if use_cache and self.config.lazy_loading:
            self._structure_cache[uniprot_id] = structure
        
        return structure
    
    def get_structures_batch(
        self,
        uniprot_ids: List[str],
        skip_missing: bool = True
    ) -> Dict[str, AlphaFoldStructure]:
        """
        Get multiple structures in batch.
        
        Args:
            uniprot_ids: List of UniProt accessions
            skip_missing: Skip missing structures instead of raising
        
        Returns:
            Dictionary mapping UniProt ID to structure
        """
        structures = {}
        
        for uniprot_id in uniprot_ids:
            try:
                structures[uniprot_id] = self.get_structure(uniprot_id)
            except KeyError:
                if not skip_missing:
                    raise
                logger.warning(f"Structure not found: {uniprot_id}")
        
        return structures
    
    def iterate_structures(
        self,
        limit: Optional[int] = None,
        filter_func: Optional[callable] = None
    ) -> Iterator[AlphaFoldStructure]:
        """
        Iterate over all structures (lazy loading).
        
        Args:
            limit: Maximum number of structures to yield
            filter_func: Optional filter function(structure) -> bool
        
        Yields:
            AlphaFoldStructure objects one at a time
        
        Memory Efficiency:
            Only loads one structure at a time
            Does not cache during iteration
        """
        count = 0
        
        for uniprot_id in sorted(self._index.uniprot_ids):
            if limit and count >= limit:
                break
            
            try:
                structure = self.get_structure(uniprot_id, use_cache=False)
                
                if filter_func is None or filter_func(structure):
                    yield structure
                    count += 1
                    
            except Exception as e:
                logger.warning(f"Failed to load {uniprot_id}: {e}")
    
    # =====================================================================
    # PUBLIC API - Feature Extraction
    # =====================================================================
    
    def get_ca_coordinates(
        self,
        uniprot_id: str
    ) -> npt.NDArray[np.float64]:
        """
        Get Cα backbone coordinates.
        
        Args:
            uniprot_id: UniProt accession
        
        Returns:
            Array of shape (n_residues, 3)
        """
        structure = self.get_structure(uniprot_id)
        return structure.ca_coordinates
    
    def get_plddt_scores(
        self,
        uniprot_id: str
    ) -> npt.NDArray[np.float64]:
        """
        Get per-residue pLDDT confidence scores.
        
        AlphaFold Confidence Scale:
            90-100: Very high confidence
            70-90:  High confidence
            50-70:  Low confidence
            <50:    Very low confidence
        
        Returns:
            Array of shape (n_residues,)
        """
        structure = self.get_structure(uniprot_id)
        return structure.plddt_per_residue
    
    def get_distance_matrix(
        self,
        uniprot_id: str
    ) -> npt.NDArray[np.float64]:
        """
        Get Cα-Cα distance matrix.
        
        Returns:
            Symmetric matrix of shape (n_residues, n_residues)
        """
        structure = self.get_structure(uniprot_id)
        return structure.get_distance_matrix()
    
    def get_contact_map(
        self,
        uniprot_id: str,
        threshold: float = 8.0
    ) -> npt.NDArray[np.bool_]:
        """
        Get contact map (boolean adjacency).
        
        Args:
            uniprot_id: UniProt accession
            threshold: Distance cutoff in Angstroms
        
        Returns:
            Boolean matrix of shape (n_residues, n_residues)
        """
        structure = self.get_structure(uniprot_id)
        return structure.get_contact_map(threshold)
    
    def get_sequence(self, uniprot_id: str) -> str:
        """Get amino acid sequence from structure."""
        structure = self.get_structure(uniprot_id)
        return structure.sequence
    
    def get_metadata(self, uniprot_id: str) -> AlphaFoldMetadata:
        """Get structure metadata."""
        structure = self.get_structure(uniprot_id)
        return structure.metadata
    
    # =====================================================================
    # PUBLIC API - Batch Feature Extraction
    # =====================================================================
    
    def extract_all_ca_coordinates(
        self,
        uniprot_ids: Optional[List[str]] = None,
        max_length: Optional[int] = None
    ) -> Dict[str, npt.NDArray[np.float64]]:
        """
        Extract Cα coordinates for multiple proteins.
        
        Args:
            uniprot_ids: List of IDs (None for all)
            max_length: Skip proteins longer than this
        
        Returns:
            Dictionary mapping UniProt ID to coordinate array
        """
        if uniprot_ids is None:
            uniprot_ids = list(self._index.uniprot_ids)
        
        coords = {}
        
        for uniprot_id in uniprot_ids:
            try:
                structure = self.get_structure(uniprot_id)
                
                if max_length and structure.n_residues > max_length:
                    continue
                
                coords[uniprot_id] = structure.ca_coordinates
                
            except Exception as e:
                logger.warning(f"Failed to extract coords for {uniprot_id}: {e}")
        
        return coords
    
    def extract_all_plddt_scores(
        self,
        uniprot_ids: Optional[List[str]] = None
    ) -> Dict[str, npt.NDArray[np.float64]]:
        """
        Extract pLDDT scores for multiple proteins.
        
        Returns:
            Dictionary mapping UniProt ID to pLDDT array
        """
        if uniprot_ids is None:
            uniprot_ids = list(self._index.uniprot_ids)
        
        scores = {}
        
        for uniprot_id in uniprot_ids:
            try:
                scores[uniprot_id] = self.get_plddt_scores(uniprot_id)
            except Exception as e:
                logger.warning(f"Failed to extract pLDDT for {uniprot_id}: {e}")
        
        return scores
    
    # =====================================================================
    # PUBLIC API - Statistics and Info
    # =====================================================================
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get connector statistics.
        
        Returns:
            Dictionary with structure counts, cache stats, etc.
        """
        return {
            'total_structures': self.n_structures,
            'cached_structures': len(self._structure_cache),
            'structures_dir': str(self.config.structures_dir),
            'cache_dir': str(self.config.cache_dir),
            'index_created': self._index.created_at,
            'config': {
                'lazy_loading': self.config.lazy_loading,
                'batch_size': self.config.batch_size
            }
        }
    
    def clear_cache(self) -> None:
        """Clear in-memory structure cache."""
        n_cleared = len(self._structure_cache)
        self._structure_cache.clear()
        logger.info(f"Cache cleared: {n_cleared} structures")
    
    def rebuild_index(self) -> None:
        """Force rebuild of structure index."""
        self._build_index()
        index_path = self.config.cache_dir / "alphafold_sovereign_index.pkl"
        self._save_index(index_path)
        logger.info("Index rebuilt and saved")


# Export for public API
__all__ = [
    'SovereignAlphaFoldConnector',
    'SovereignAlphaFoldConfig',
    'StructureIndex',
]
