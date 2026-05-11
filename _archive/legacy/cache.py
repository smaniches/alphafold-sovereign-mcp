# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""
Sovereign Structure Cache
=========================

High-performance caching for AlphaFold structure data and features.
Enables instant retrieval of pre-computed features.

Patent-pending framework by Santiago Maniches (ORCID: 0009-0005-6480-1987)
TOPOLOGICA LLC
"""

from typing import Dict, List, Optional, Any, Set
import numpy as np
import numpy.typing as npt
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timezone
import structlog
import pickle
import json
import hashlib

logger = structlog.get_logger(__name__)


@dataclass
class CacheMetadata:
    """Metadata for a cached item."""
    key: str
    created_at: str
    size_bytes: int
    data_type: str
    version: str
    checksum: str


class SovereignStructureCache:
    """
    Sovereign cache for AlphaFold structure data and features.
    
    Design Principles:
        1. FILESYSTEM-BASED: All data on local disk
        2. VERSIONED: Track cache versions for invalidation
        3. CHECKSUMMED: Verify data integrity
        4. FAST LOOKUP: O(1) via hash-based indexing
    
    Cache Organization:
        cache_dir/
        ├── metadata.json           # Cache index
        ├── structures/             # Serialized structures
        ├── features/               # Computed features
        ├── topology/               # Topological features
        └── embeddings/             # Coordinate embeddings
    
    Patent-pending framework by Santiago Maniches
    (ORCID: 0009-0005-6480-1987)
    """
    
    VERSION = "1.0.0"
    
    def __init__(
        self,
        cache_dir: Path,
        auto_create: bool = True,
        verify_integrity: bool = True
    ):
        """
        Initialize cache.
        
        Args:
            cache_dir: Directory for cache storage
            auto_create: Create directories if missing
            verify_integrity: Verify checksums on load
        """
        self.cache_dir = Path(cache_dir)
        self.verify_integrity = verify_integrity
        
        # Subdirectories
        self.structures_dir = self.cache_dir / "structures"
        self.features_dir = self.cache_dir / "features"
        self.topology_dir = self.cache_dir / "topology"
        self.embeddings_dir = self.cache_dir / "embeddings"
        
        # Create directories
        if auto_create:
            for d in [self.structures_dir, self.features_dir, 
                      self.topology_dir, self.embeddings_dir]:
                d.mkdir(parents=True, exist_ok=True)
        
        # Load or initialize metadata
        self.metadata_file = self.cache_dir / "cache_metadata.json"
        self._metadata: Dict[str, CacheMetadata] = {}
        self._load_metadata()
        
        logger.info(
            "cache_initialized",
            timestamp=datetime.now(timezone.utc).isoformat(),
            cache_dir=str(self.cache_dir),
            n_entries=len(self._metadata),
            version=self.VERSION
        )
    
    def _load_metadata(self) -> None:
        """Load cache metadata from disk."""
        if self.metadata_file.exists():
            with open(self.metadata_file, 'r') as f:
                data = json.load(f)
            
            self._metadata = {
                k: CacheMetadata(**v) for k, v in data.items()
            }
    
    def _save_metadata(self) -> None:
        """Save cache metadata to disk."""
        data = {
            k: {
                'key': v.key,
                'created_at': v.created_at,
                'size_bytes': v.size_bytes,
                'data_type': v.data_type,
                'version': v.version,
                'checksum': v.checksum
            }
            for k, v in self._metadata.items()
        }
        
        with open(self.metadata_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def _compute_checksum(self, data: bytes) -> str:
        """Compute SHA256 checksum of data."""
        return hashlib.sha256(data).hexdigest()[:16]
    
    def _get_cache_path(
        self,
        key: str,
        data_type: str
    ) -> Path:
        """Get path for cache entry."""
        if data_type == 'structure':
            return self.structures_dir / f"{key}.pkl"
        elif data_type == 'features':
            return self.features_dir / f"{key}.pkl"
        elif data_type == 'topology':
            return self.topology_dir / f"{key}.pkl"
        elif data_type == 'embedding':
            return self.embeddings_dir / f"{key}.npy"
        else:
            return self.cache_dir / f"{key}.pkl"
    
    # =====================================================================
    # Public API - Cache Operations
    # =====================================================================
    
    def has(self, key: str, data_type: str = 'features') -> bool:
        """Check if key exists in cache."""
        cache_key = f"{data_type}:{key}"
        return cache_key in self._metadata
    
    def get(
        self,
        key: str,
        data_type: str = 'features'
    ) -> Optional[Any]:
        """
        Retrieve item from cache.
        
        Args:
            key: Cache key (typically UniProt ID)
            data_type: Type of cached data
        
        Returns:
            Cached data or None if not found
        """
        cache_key = f"{data_type}:{key}"
        
        if cache_key not in self._metadata:
            return None
        
        path = self._get_cache_path(key, data_type)
        
        if not path.exists():
            logger.warning(f"Cache file missing: {path}")
            del self._metadata[cache_key]
            self._save_metadata()
            return None
        
        # Load data
        if path.suffix == '.npy':
            data = np.load(path)
        else:
            with open(path, 'rb') as f:
                data_bytes = f.read()
                
            # Verify checksum if enabled
            if self.verify_integrity:
                checksum = self._compute_checksum(data_bytes)
                expected = self._metadata[cache_key].checksum
                if checksum != expected:
                    logger.error(
                        f"Checksum mismatch for {cache_key}: "
                        f"expected {expected}, got {checksum}"
                    )
                    return None
            
            data = pickle.loads(data_bytes)
        
        return data
    
    def put(
        self,
        key: str,
        data: Any,
        data_type: str = 'features'
    ) -> None:
        """
        Store item in cache.
        
        Args:
            key: Cache key (typically UniProt ID)
            data: Data to cache
            data_type: Type of data being cached
        """
        cache_key = f"{data_type}:{key}"
        path = self._get_cache_path(key, data_type)
        
        # Serialize data
        if isinstance(data, np.ndarray):
            np.save(path, data)
            size = path.stat().st_size
            checksum = self._compute_checksum(data.tobytes())
        else:
            data_bytes = pickle.dumps(data)
            with open(path, 'wb') as f:
                f.write(data_bytes)
            size = len(data_bytes)
            checksum = self._compute_checksum(data_bytes)
        
        # Update metadata
        self._metadata[cache_key] = CacheMetadata(
            key=key,
            created_at=datetime.now(timezone.utc).isoformat(),
            size_bytes=size,
            data_type=data_type,
            version=self.VERSION,
            checksum=checksum
        )
        
        self._save_metadata()
        
        logger.debug(f"Cached {cache_key}: {size} bytes")
    
    def delete(self, key: str, data_type: str = 'features') -> bool:
        """
        Delete item from cache.
        
        Returns:
            True if deleted, False if not found
        """
        cache_key = f"{data_type}:{key}"
        
        if cache_key not in self._metadata:
            return False
        
        path = self._get_cache_path(key, data_type)
        
        if path.exists():
            path.unlink()
        
        del self._metadata[cache_key]
        self._save_metadata()
        
        return True
    
    def keys(self, data_type: Optional[str] = None) -> Set[str]:
        """
        Get all cached keys.
        
        Args:
            data_type: Filter by data type (None for all)
        
        Returns:
            Set of cache keys
        """
        if data_type:
            prefix = f"{data_type}:"
            return {
                k.split(':')[1] for k in self._metadata.keys()
                if k.startswith(prefix)
            }
        else:
            return {k.split(':')[1] for k in self._metadata.keys()}
    
    # =====================================================================
    # Public API - Batch Operations
    # =====================================================================
    
    def get_batch(
        self,
        keys: List[str],
        data_type: str = 'features'
    ) -> Dict[str, Any]:
        """
        Retrieve multiple items from cache.
        
        Returns:
            Dictionary mapping key to cached data (missing keys omitted)
        """
        result = {}
        
        for key in keys:
            data = self.get(key, data_type)
            if data is not None:
                result[key] = data
        
        return result
    
    def put_batch(
        self,
        data_dict: Dict[str, Any],
        data_type: str = 'features'
    ) -> int:
        """
        Store multiple items in cache.
        
        Returns:
            Number of items cached
        """
        count = 0
        
        for key, data in data_dict.items():
            self.put(key, data, data_type)
            count += 1
        
        return count
    
    # =====================================================================
    # Public API - Cache Management
    # =====================================================================
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get cache statistics."""
        by_type: Dict[str, int] = {}
        total_size = 0
        
        for cache_key, meta in self._metadata.items():
            data_type = meta.data_type
            by_type[data_type] = by_type.get(data_type, 0) + 1
            total_size += meta.size_bytes
        
        return {
            'total_entries': len(self._metadata),
            'entries_by_type': by_type,
            'total_size_bytes': total_size,
            'total_size_mb': total_size / (1024 * 1024),
            'cache_dir': str(self.cache_dir),
            'version': self.VERSION
        }
    
    def clear(self, data_type: Optional[str] = None) -> int:
        """
        Clear cache entries.
        
        Args:
            data_type: Type to clear (None for all)
        
        Returns:
            Number of entries cleared
        """
        if data_type:
            keys_to_delete = [
                k for k in self._metadata.keys()
                if self._metadata[k].data_type == data_type
            ]
        else:
            keys_to_delete = list(self._metadata.keys())
        
        count = 0
        for cache_key in keys_to_delete:
            key = cache_key.split(':')[1]
            dt = self._metadata[cache_key].data_type
            self.delete(key, dt)
            count += 1
        
        return count
    
    def verify_all(self) -> Dict[str, bool]:
        """
        Verify integrity of all cached items.
        
        Returns:
            Dictionary mapping cache key to verification result
        """
        results = {}
        
        for cache_key, meta in self._metadata.items():
            key = cache_key.split(':')[1]
            data_type = meta.data_type
            
            path = self._get_cache_path(key, data_type)
            
            if not path.exists():
                results[cache_key] = False
                continue
            
            if path.suffix == '.npy':
                data = np.load(path)
                checksum = self._compute_checksum(data.tobytes())
            else:
                with open(path, 'rb') as f:
                    data_bytes = f.read()
                checksum = self._compute_checksum(data_bytes)
            
            results[cache_key] = (checksum == meta.checksum)
        
        n_valid = sum(results.values())
        n_total = len(results)
        
        logger.info(f"Cache verification: {n_valid}/{n_total} valid")
        
        return results


# Export for public API
__all__ = [
    'CacheMetadata',
    'SovereignStructureCache',
]
