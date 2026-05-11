# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""
Sovereign AlphaFold PDB Parser
==============================

High-performance parser for AlphaFold PDB files with full metadata extraction.
No API dependencies - direct filesystem access.

Mathematical Foundation:
    Protein structure P = (V, E, F) where:
    - V: Vertex set (atoms with coordinates x ∈ ℝ³)
    - E: Edge set (covalent bonds)
    - F: Feature set (pLDDT, secondary structure, sequence)

Patent-pending framework by Santiago Maniches (ORCID: 0009-0005-6480-1987)
"""

from typing import Dict, List, Optional, Tuple, Any
import numpy as np
import numpy.typing as npt
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timezone
import structlog
import re

logger = structlog.get_logger(__name__)


@dataclass
class Atom:
    """
    Single atom representation from PDB file.
    
    Coordinates:
        x ∈ ℝ³: Position in Angstroms
        b_factor: pLDDT confidence (0-100 for AlphaFold)
    """
    serial: int
    name: str              # Atom name (CA, N, C, O, CB, etc.)
    residue_name: str      # 3-letter amino acid code
    chain_id: str
    residue_seq: int
    x: float
    y: float
    z: float
    occupancy: float
    b_factor: float        # pLDDT for AlphaFold structures
    element: str
    
    @property
    def position(self) -> npt.NDArray[np.float64]:
        """Return atom position as numpy array."""
        return np.array([self.x, self.y, self.z], dtype=np.float64)
    
    @property
    def plddt(self) -> float:
        """pLDDT confidence score (AlphaFold B-factor encoding)."""
        return self.b_factor


@dataclass
class Residue:
    """
    Single residue representation.
    
    Contains all atoms for one amino acid with derived properties.
    """
    name: str              # 3-letter code
    sequence_number: int
    chain_id: str
    atoms: Dict[str, Atom] = field(default_factory=dict)
    
    @property
    def ca_position(self) -> Optional[npt.NDArray[np.float64]]:
        """Cα carbon position for backbone analysis."""
        if 'CA' in self.atoms:
            return self.atoms['CA'].position
        return None
    
    @property
    def plddt(self) -> float:
        """Mean pLDDT for all atoms in residue."""
        if not self.atoms:
            return 0.0
        return np.mean([a.b_factor for a in self.atoms.values()])
    
    @property
    def one_letter_code(self) -> str:
        """Convert 3-letter to 1-letter amino acid code."""
        AA_MAP = {
            'ALA': 'A', 'CYS': 'C', 'ASP': 'D', 'GLU': 'E', 'PHE': 'F',
            'GLY': 'G', 'HIS': 'H', 'ILE': 'I', 'LYS': 'K', 'LEU': 'L',
            'MET': 'M', 'ASN': 'N', 'PRO': 'P', 'GLN': 'Q', 'ARG': 'R',
            'SER': 'S', 'THR': 'T', 'VAL': 'V', 'TRP': 'W', 'TYR': 'Y',
            'UNK': 'X', 'SEC': 'U', 'PYL': 'O'
        }
        return AA_MAP.get(self.name, 'X')


@dataclass
class AlphaFoldMetadata:
    """
    Complete AlphaFold structure metadata.
    
    Extracted from PDB header and computed from structure.
    """
    uniprot_id: str
    protein_name: str
    organism: str
    organism_taxid: Optional[int]
    chain_id: str
    sequence_length: int
    sequence: str
    alphafold_version: str
    prediction_date: Optional[str]
    mean_plddt: float
    confidence_regions: Dict[str, int]  # Very High/High/Low/Very Low counts
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for caching."""
        return {
            'uniprot_id': self.uniprot_id,
            'protein_name': self.protein_name,
            'organism': self.organism,
            'organism_taxid': self.organism_taxid,
            'chain_id': self.chain_id,
            'sequence_length': self.sequence_length,
            'sequence': self.sequence,
            'alphafold_version': self.alphafold_version,
            'prediction_date': self.prediction_date,
            'mean_plddt': self.mean_plddt,
            'confidence_regions': self.confidence_regions
        }


@dataclass
class AlphaFoldStructure:
    """
    Complete AlphaFold structure representation.
    
    Contains atoms, residues, metadata, and derived features.
    """
    uniprot_id: str
    file_path: Path
    metadata: AlphaFoldMetadata
    atoms: List[Atom]
    residues: Dict[int, Residue]
    
    # Derived features (computed lazily)
    _ca_coords: Optional[npt.NDArray[np.float64]] = field(default=None, repr=False)
    _plddt_scores: Optional[npt.NDArray[np.float64]] = field(default=None, repr=False)
    
    @property
    def ca_coordinates(self) -> npt.NDArray[np.float64]:
        """
        Extract Cα backbone coordinates.
        
        Returns:
            Array of shape (n_residues, 3) with Cα positions
        """
        if self._ca_coords is None:
            coords = []
            for seq_num in sorted(self.residues.keys()):
                ca_pos = self.residues[seq_num].ca_position
                if ca_pos is not None:
                    coords.append(ca_pos)
            self._ca_coords = np.array(coords, dtype=np.float64)
        return self._ca_coords
    
    @property
    def plddt_per_residue(self) -> npt.NDArray[np.float64]:
        """pLDDT confidence score per residue."""
        if self._plddt_scores is None:
            scores = []
            for seq_num in sorted(self.residues.keys()):
                scores.append(self.residues[seq_num].plddt)
            self._plddt_scores = np.array(scores, dtype=np.float64)
        return self._plddt_scores
    
    @property
    def sequence(self) -> str:
        """Amino acid sequence from structure."""
        return ''.join(
            self.residues[seq_num].one_letter_code 
            for seq_num in sorted(self.residues.keys())
        )
    
    @property
    def n_residues(self) -> int:
        """Number of residues in structure."""
        return len(self.residues)
    
    def get_distance_matrix(self) -> npt.NDArray[np.float64]:
        """
        Compute Cα-Cα distance matrix.
        
        Mathematical Definition:
            D[i,j] = ||r_i - r_j||₂ where r_i is Cα position of residue i
        
        Returns:
            Symmetric distance matrix of shape (n_residues, n_residues)
        
        Complexity:
            Time: O(n²) via vectorized pdist
            Space: O(n²)
        """
        coords = self.ca_coordinates
        # Vectorized distance computation
        diff = coords[:, np.newaxis, :] - coords[np.newaxis, :, :]
        distances = np.linalg.norm(diff, axis=2)
        return distances
    
    def get_contact_map(
        self,
        threshold: float = 8.0
    ) -> npt.NDArray[np.bool_]:
        """
        Compute contact map from distance matrix.
        
        Args:
            threshold: Distance cutoff in Angstroms (default: 8.0)
        
        Returns:
            Boolean contact matrix of shape (n_residues, n_residues)
        """
        return self.get_distance_matrix() < threshold


class PDBParser:
    """
    High-performance PDB parser for AlphaFold structures.
    
    Provides:
        - Full atom/residue parsing
        - AlphaFold metadata extraction
        - Vectorized coordinate handling
        - pLDDT confidence analysis
    
    Design Principles:
        - Filesystem-first: No API dependencies
        - Deterministic: Same file → same output
        - Complete: All PDB fields preserved
    """
    
    def __init__(
        self,
        structures_dir: Optional[Path] = None,
        seed: int = 42
    ):
        """
        Initialize parser.
        
        Args:
            structures_dir: Base directory for PDB files
            seed: Random seed for deterministic behavior
        """
        self.structures_dir = Path(structures_dir) if structures_dir else None
        self.seed = seed
        
        # Precompile regex patterns for performance
        self._atom_pattern = re.compile(
            r'^ATOM\s+(\d+)\s+(\S+)\s+(\w+)\s+(\w)\s*(\d+)\s+'
            r'(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+'
            r'(\d+\.\d+)\s+(\d+\.\d+)\s*(\w*)'
        )
        
        logger.info(
            "pdb_parser_initialized",
            timestamp=datetime.now(timezone.utc).isoformat(),
            structures_dir=str(self.structures_dir),
            seed=seed
        )
    
    def parse_file(
        self,
        file_path: Path
    ) -> AlphaFoldStructure:
        """
        Parse single PDB file into AlphaFoldStructure.
        
        Args:
            file_path: Path to PDB file
        
        Returns:
            Complete structure with atoms, residues, metadata
        
        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file format invalid
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"PDB file not found: {file_path}")
        
        start_time = datetime.now(timezone.utc)
        
        # Extract UniProt ID from filename
        uniprot_id = file_path.stem
        
        # Parse file
        atoms: List[Atom] = []
        residues: Dict[int, Residue] = {}
        header_info: Dict[str, Any] = {}
        
        with open(file_path, 'r') as f:
            for line in f:
                record_type = line[:6].strip()
                
                if record_type == 'HEADER':
                    header_info['date'] = line[50:59].strip()
                
                elif record_type == 'TITLE':
                    title = line[10:].strip()
                    header_info.setdefault('title', '')
                    header_info['title'] += ' ' + title
                
                elif record_type == 'SOURCE':
                    if 'ORGANISM_SCIENTIFIC' in line:
                        match = re.search(r'ORGANISM_SCIENTIFIC:\s*(.+?);', line)
                        if match:
                            header_info['organism'] = match.group(1).strip()
                    elif 'ORGANISM_TAXID' in line:
                        match = re.search(r'ORGANISM_TAXID:\s*(\d+)', line)
                        if match:
                            header_info['taxid'] = int(match.group(1))
                
                elif record_type == 'ATOM':
                    atom = self._parse_atom_line(line)
                    if atom:
                        atoms.append(atom)
                        
                        # Add to residue
                        if atom.residue_seq not in residues:
                            residues[atom.residue_seq] = Residue(
                                name=atom.residue_name,
                                sequence_number=atom.residue_seq,
                                chain_id=atom.chain_id
                            )
                        residues[atom.residue_seq].atoms[atom.name] = atom
        
        # Compute metadata
        sequence = ''.join(
            residues[seq_num].one_letter_code 
            for seq_num in sorted(residues.keys())
        )
        
        plddt_scores = np.array([
            residues[seq_num].plddt 
            for seq_num in sorted(residues.keys())
        ])
        mean_plddt = float(np.mean(plddt_scores)) if len(plddt_scores) > 0 else 0.0
        
        # Classify confidence regions
        confidence_regions = self._classify_plddt_regions(plddt_scores)
        
        # Extract protein name from title
        title = header_info.get('title', '').strip()
        protein_name = self._extract_protein_name(title, uniprot_id)
        
        metadata = AlphaFoldMetadata(
            uniprot_id=uniprot_id,
            protein_name=protein_name,
            organism=header_info.get('organism', 'Unknown'),
            organism_taxid=header_info.get('taxid'),
            chain_id='A',  # AlphaFold uses chain A
            sequence_length=len(sequence),
            sequence=sequence,
            alphafold_version='v2.0',  # From title pattern
            prediction_date=header_info.get('date'),
            mean_plddt=mean_plddt,
            confidence_regions=confidence_regions
        )
        
        structure = AlphaFoldStructure(
            uniprot_id=uniprot_id,
            file_path=file_path,
            metadata=metadata,
            atoms=atoms,
            residues=residues
        )
        
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        
        logger.info(
            "pdb_parsed",
            uniprot_id=uniprot_id,
            n_atoms=len(atoms),
            n_residues=len(residues),
            mean_plddt=mean_plddt,
            duration_seconds=duration
        )
        
        return structure
    
    def _parse_atom_line(self, line: str) -> Optional[Atom]:
        """
        Parse single ATOM line from PDB file.
        
        PDB ATOM format (columns 1-indexed):
            1-6:   Record type (ATOM)
            7-11:  Serial number
            13-16: Atom name
            17:    Alternate location indicator
            18-20: Residue name
            22:    Chain identifier
            23-26: Residue sequence number
            31-38: X coordinate
            39-46: Y coordinate
            47-54: Z coordinate
            55-60: Occupancy
            61-66: Temperature factor (pLDDT for AlphaFold)
            77-78: Element symbol
        """
        try:
            serial = int(line[6:11].strip())
            name = line[12:16].strip()
            residue_name = line[17:20].strip()
            chain_id = line[21].strip() or 'A'
            residue_seq = int(line[22:26].strip())
            x = float(line[30:38].strip())
            y = float(line[38:46].strip())
            z = float(line[46:54].strip())
            occupancy = float(line[54:60].strip()) if line[54:60].strip() else 1.0
            b_factor = float(line[60:66].strip()) if line[60:66].strip() else 0.0
            element = line[76:78].strip() if len(line) > 76 else name[0]
            
            return Atom(
                serial=serial,
                name=name,
                residue_name=residue_name,
                chain_id=chain_id,
                residue_seq=residue_seq,
                x=x,
                y=y,
                z=z,
                occupancy=occupancy,
                b_factor=b_factor,
                element=element
            )
        except (ValueError, IndexError) as e:
            logger.warning(f"Failed to parse ATOM line: {line[:70]}... Error: {e}")
            return None
    
    def _classify_plddt_regions(
        self,
        plddt_scores: npt.NDArray[np.float64]
    ) -> Dict[str, int]:
        """
        Classify pLDDT scores into AlphaFold confidence regions.
        
        AlphaFold Confidence Scale:
            - Very High (90-100): High accuracy, confident backbone and sidechains
            - High (70-90): Good backbone prediction, less certain sidechains
            - Low (50-70): Caution advised, possibly disordered
            - Very Low (<50): Should not be interpreted
        
        Returns:
            Count of residues in each confidence category
        """
        return {
            'very_high': int(np.sum(plddt_scores >= 90)),
            'high': int(np.sum((plddt_scores >= 70) & (plddt_scores < 90))),
            'low': int(np.sum((plddt_scores >= 50) & (plddt_scores < 70))),
            'very_low': int(np.sum(plddt_scores < 50))
        }
    
    def _extract_protein_name(
        self,
        title: str,
        uniprot_id: str
    ) -> str:
        """Extract protein name from PDB title."""
        # AlphaFold title format: "ALPHAFOLD MONOMER V2.0 PREDICTION FOR <NAME> (<UNIPROT_ID>)"
        match = re.search(
            r'PREDICTION FOR\s+(.+?)\s*\(' + re.escape(uniprot_id) + r'\)',
            title,
            re.IGNORECASE
        )
        if match:
            return match.group(1).strip()
        return f"Protein {uniprot_id}"
    
    def parse_directory(
        self,
        directory: Optional[Path] = None,
        limit: Optional[int] = None,
        pattern: str = "*.pdb"
    ) -> Dict[str, AlphaFoldStructure]:
        """
        Parse all PDB files in directory.
        
        Args:
            directory: Directory to parse (uses self.structures_dir if None)
            limit: Maximum number of files to parse (None for all)
            pattern: Glob pattern for PDB files
        
        Returns:
            Dictionary mapping UniProt ID to structure
        """
        directory = Path(directory) if directory else self.structures_dir
        
        if not directory or not directory.exists():
            raise ValueError(f"Directory not found: {directory}")
        
        start_time = datetime.now(timezone.utc)
        
        pdb_files = list(directory.glob(pattern))
        
        if limit:
            pdb_files = pdb_files[:limit]
        
        logger.info(
            "parsing_directory",
            directory=str(directory),
            n_files=len(pdb_files),
            limit=limit
        )
        
        structures = {}
        for i, pdb_file in enumerate(pdb_files):
            try:
                structure = self.parse_file(pdb_file)
                structures[structure.uniprot_id] = structure
                
                if (i + 1) % 1000 == 0:
                    logger.info(
                        "parse_progress",
                        completed=i + 1,
                        total=len(pdb_files),
                        percent=100 * (i + 1) / len(pdb_files)
                    )
            except Exception as e:
                logger.warning(f"Failed to parse {pdb_file}: {e}")
        
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        
        logger.info(
            "directory_parsed",
            n_structures=len(structures),
            n_failed=len(pdb_files) - len(structures),
            duration_seconds=duration
        )
        
        return structures


# Export for public API
__all__ = [
    'Atom',
    'Residue',
    'AlphaFoldMetadata',
    'AlphaFoldStructure',
    'PDBParser',
]
