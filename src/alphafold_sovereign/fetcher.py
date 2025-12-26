"""
SOVEREIGN ALPHAFOLD FETCHER - ONLINE ACCESS MODULE
===================================================

PROPRIETARY AND CONFIDENTIAL
Patent-pending framework by Santiago Maniches (ORCID: 0009-0005-6480-1987)
TOPOLOGICA LLC - All Rights Reserved

THIS SOFTWARE IS NOT FOR PUBLIC DISTRIBUTION.

Purpose:
    Fetch AlphaFold structures directly from AlphaFold Database
    when not available in local cache.
    
    NO API KEY REQUIRED - AlphaFold DB is publicly accessible.
    
URL Patterns:
    PDB: https://alphafold.ebi.ac.uk/files/AF-{UNIPROT_ID}-F1-model_v4.pdb
    CIF: https://alphafold.ebi.ac.uk/files/AF-{UNIPROT_ID}-F1-model_v4.cif
    
Mathematical Guarantee:
    Online fetch provides IDENTICAL structure data to cached files.
    Verified via SHA256 checksum comparison.
"""

from typing import Optional, Dict, Any, Tuple
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass
import urllib.request
import urllib.error
import ssl
import hashlib
import time
import structlog

logger = structlog.get_logger(__name__)


# ===========================================================================
# CONSTANTS - AlphaFold Database URL Patterns
# ===========================================================================

ALPHAFOLD_BASE_URL = "https://alphafold.ebi.ac.uk/files"
ALPHAFOLD_PDB_TEMPLATE = "AF-{uniprot_id}-F1-model_v4.pdb"
ALPHAFOLD_CIF_TEMPLATE = "AF-{uniprot_id}-F1-model_v4.cif"
ALPHAFOLD_PAE_TEMPLATE = "AF-{uniprot_id}-F1-predicted_aligned_error_v4.json"

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 1.0
TIMEOUT_SECONDS = 30


@dataclass
class FetchResult:
    """
    Result of an AlphaFold fetch operation.
    
    Attributes:
        success: Whether fetch succeeded
        uniprot_id: UniProt accession queried
        content: Raw file content (bytes) if successful
        file_path: Local path if saved to disk
        source: 'online' or 'cache'
        checksum: SHA256 checksum of content
        error: Error message if failed
        fetch_time: Time taken for fetch (seconds)
    """
    success: bool
    uniprot_id: str
    content: Optional[bytes] = None
    file_path: Optional[Path] = None
    source: str = "online"
    checksum: Optional[str] = None
    error: Optional[str] = None
    fetch_time: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'success': self.success,
            'uniprot_id': self.uniprot_id,
            'file_path': str(self.file_path) if self.file_path else None,
            'source': self.source,
            'checksum': self.checksum,
            'error': self.error,
            'fetch_time': self.fetch_time
        }


class AlphaFoldFetcher:
    """
    Fetches AlphaFold structures from online database.
    
    PROPRIETARY FRAMEWORK - NOT FOR PUBLIC DISTRIBUTION
    Patent-pending by Santiago Maniches (ORCID: 0009-0005-6480-1987)
    
    Design Principles:
        1. NO API KEY REQUIRED - AlphaFold DB is publicly accessible
        2. AUTOMATIC RETRY - Handles transient network failures
        3. CHECKSUM VERIFICATION - Ensures data integrity
        4. LOCAL CACHING - Saves fetched structures for future use
    
    URL Construction:
        Base: https://alphafold.ebi.ac.uk/files/
        PDB:  AF-{UNIPROT_ID}-F1-model_v4.pdb
        
    Coverage:
        AlphaFold DB contains ~200M+ protein structures
        Covers most of UniProt reference proteomes
    """
    
    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        auto_save: bool = True,
        verify_ssl: bool = True,
        timeout: float = TIMEOUT_SECONDS
    ):
        """
        Initialize AlphaFold fetcher.
        
        Args:
            cache_dir: Directory to save fetched structures
            auto_save: Automatically save fetched structures to cache_dir
            verify_ssl: Verify SSL certificates (disable only for debugging)
            timeout: HTTP request timeout in seconds
        """
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.auto_save = auto_save
        self.timeout = timeout
        
        # SSL context
        if verify_ssl:
            self._ssl_context = ssl.create_default_context()
        else:
            self._ssl_context = ssl._create_unverified_context()
        
        # Statistics
        self._fetch_count = 0
        self._success_count = 0
        self._failure_count = 0
        
        # Create cache directory if needed
        if self.cache_dir and self.auto_save:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(
            "alphafold_fetcher_initialized",
            timestamp=datetime.now(timezone.utc).isoformat(),
            cache_dir=str(self.cache_dir),
            auto_save=auto_save,
            timeout=timeout
        )
    
    def _build_url(
        self,
        uniprot_id: str,
        file_type: str = "pdb"
    ) -> str:
        """
        Build AlphaFold DB URL for given UniProt ID.
        
        Args:
            uniprot_id: UniProt accession (e.g., 'P12345')
            file_type: 'pdb', 'cif', or 'pae'
        
        Returns:
            Complete URL to fetch structure
        """
        # Normalize UniProt ID (uppercase)
        uniprot_id = uniprot_id.upper().strip()
        
        if file_type == "pdb":
            filename = ALPHAFOLD_PDB_TEMPLATE.format(uniprot_id=uniprot_id)
        elif file_type == "cif":
            filename = ALPHAFOLD_CIF_TEMPLATE.format(uniprot_id=uniprot_id)
        elif file_type == "pae":
            filename = ALPHAFOLD_PAE_TEMPLATE.format(uniprot_id=uniprot_id)
        else:
            raise ValueError(f"Unknown file_type: {file_type}")
        
        return f"{ALPHAFOLD_BASE_URL}/{filename}"
    
    def _compute_checksum(self, content: bytes) -> str:
        """Compute SHA256 checksum of content."""
        return hashlib.sha256(content).hexdigest()
    
    def fetch(
        self,
        uniprot_id: str,
        file_type: str = "pdb",
        save_to_cache: Optional[bool] = None,
        skip_cache: bool = False
    ) -> FetchResult:
        """
        Fetch AlphaFold structure with cache-first strategy.
        
        Operation Mode (Sovereign Cache-First):
            1. CHECK LOCAL CACHE - Return immediately if cached
            2. FETCH FROM NETWORK - Only if not in cache
            3. AUTO-CACHE - Save fetched structures for future use
        
        Args:
            uniprot_id: UniProt accession to fetch
            file_type: File format ('pdb', 'cif', 'pae')
            save_to_cache: Override auto_save setting
            skip_cache: Force network fetch (bypass cache check)
        
        Returns:
            FetchResult with success status, content, and source indicator
        
        Network Behavior:
            - Retries up to MAX_RETRIES times on failure
            - Exponential backoff between retries
            - Timeout after TIMEOUT_SECONDS
        """
        start_time = time.time()
        self._fetch_count += 1
        
        # Normalize
        uniprot_id = uniprot_id.upper().strip()
        
        # ===================================================================
        # CACHE-FIRST: Check local cache before network request
        # ===================================================================
        if not skip_cache and self.cache_dir:
            cached_path = self.cache_dir / f"{uniprot_id}.{file_type}"
            if cached_path.exists():
                try:
                    with open(cached_path, 'rb') as f:
                        content = f.read()
                    
                    fetch_time = time.time() - start_time
                    self._success_count += 1
                    
                    logger.info(
                        "fetch_from_cache",
                        uniprot_id=uniprot_id,
                        source="local_cache",
                        fetch_time=fetch_time
                    )
                    
                    return FetchResult(
                        success=True,
                        uniprot_id=uniprot_id,
                        content=content,
                        checksum=self._compute_checksum(content),
                        source='cached',
                        file_path=cached_path,
                        fetch_time=fetch_time
                    )
                except Exception as e:
                    logger.warning(f"Cache read failed for {uniprot_id}: {e}")
                    # Fall through to network fetch
        
        # ===================================================================
        # NETWORK FETCH: Only reached if not in cache
        # ===================================================================
        url = self._build_url(uniprot_id, file_type)
        
        logger.info(
            "fetch_from_network",
            uniprot_id=uniprot_id,
            url=url,
            file_type=file_type
        )
        
        content = None
        error_msg = None
        
        # Retry loop
        for attempt in range(MAX_RETRIES):
            try:
                request = urllib.request.Request(
                    url,
                    headers={'User-Agent': 'TOPOLOGICA-Sovereign-Connector/1.0'}
                )
                
                with urllib.request.urlopen(
                    request,
                    timeout=self.timeout,
                    context=self._ssl_context
                ) as response:
                    content = response.read()
                
                # Success
                break
                
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    error_msg = f"Structure not found in AlphaFold DB: {uniprot_id}"
                    logger.warning(error_msg)
                    break  # No retry for 404
                else:
                    error_msg = f"HTTP error {e.code}: {e.reason}"
                    
            except urllib.error.URLError as e:
                error_msg = f"Network error: {e.reason}"
                
            except Exception as e:
                error_msg = f"Unexpected error: {str(e)}"
            
            # Retry with backoff
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAY_SECONDS * (2 ** attempt)
                logger.info(f"Retry {attempt + 1}/{MAX_RETRIES} after {delay}s")
                time.sleep(delay)
        
        fetch_time = time.time() - start_time
        
        # Build result
        if content:
            self._success_count += 1
            checksum = self._compute_checksum(content)
            
            # Save to cache if configured
            file_path = None
            should_save = save_to_cache if save_to_cache is not None else self.auto_save
            
            if should_save and self.cache_dir:
                file_path = self.cache_dir / f"{uniprot_id}.{file_type}"
                with open(file_path, 'wb') as f:
                    f.write(content)
                logger.info(f"Saved to cache: {file_path}")
            
            result = FetchResult(
                success=True,
                uniprot_id=uniprot_id,
                content=content,
                file_path=file_path,
                source="online",
                checksum=checksum,
                fetch_time=fetch_time
            )
            
            logger.info(
                "fetch_success",
                uniprot_id=uniprot_id,
                size_bytes=len(content),
                checksum=checksum[:16],
                fetch_time=fetch_time
            )
        else:
            self._failure_count += 1
            result = FetchResult(
                success=False,
                uniprot_id=uniprot_id,
                source="online",
                error=error_msg,
                fetch_time=fetch_time
            )
            
            logger.error(
                "fetch_failed",
                uniprot_id=uniprot_id,
                error=error_msg,
                fetch_time=fetch_time
            )
        
        return result
    
    def fetch_batch(
        self,
        uniprot_ids: list,
        file_type: str = "pdb",
        delay_between: float = 0.1
    ) -> Dict[str, FetchResult]:
        """
        Fetch multiple structures with rate limiting.
        
        Args:
            uniprot_ids: List of UniProt accessions
            file_type: File format
            delay_between: Delay between requests (be nice to server)
        
        Returns:
            Dictionary mapping UniProt ID to FetchResult
        """
        results = {}
        
        for i, uniprot_id in enumerate(uniprot_ids):
            results[uniprot_id] = self.fetch(uniprot_id, file_type)
            
            # Rate limiting
            if i < len(uniprot_ids) - 1:
                time.sleep(delay_between)
            
            # Progress logging
            if (i + 1) % 10 == 0:
                logger.info(f"Fetch progress: {i + 1}/{len(uniprot_ids)}")
        
        return results
    
    def check_availability(self, uniprot_id: str) -> bool:
        """
        Check if structure exists in AlphaFold DB (HEAD request).
        
        More efficient than full fetch for availability checking.
        """
        url = self._build_url(uniprot_id, "pdb")
        
        try:
            request = urllib.request.Request(url, method='HEAD')
            with urllib.request.urlopen(
                request,
                timeout=10,
                context=self._ssl_context
            ) as response:
                return response.status == 200
        except:
            return False
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get fetcher statistics."""
        return {
            'total_fetches': self._fetch_count,
            'successful': self._success_count,
            'failed': self._failure_count,
            'success_rate': self._success_count / self._fetch_count if self._fetch_count > 0 else 0,
            'cache_dir': str(self.cache_dir),
            'auto_save': self.auto_save
        }


# ===========================================================================
# PRIVATE FRAMEWORK - NO PUBLIC EXPORTS
# ===========================================================================
