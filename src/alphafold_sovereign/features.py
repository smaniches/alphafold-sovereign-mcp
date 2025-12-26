"""
Sovereign AlphaFold Feature Extractor
=====================================

Extract structural features from AlphaFold structures for ML/analysis.
Supports: secondary structure, binding pockets, topology, geometric features.

Patent-pending framework by Santiago Maniches (ORCID: 0009-0005-6480-1987)
TOPOLOGICA LLC
"""

from typing import Dict, List, Optional, Tuple, Any
import numpy as np
import numpy.typing as npt
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger(__name__)


# ===========================================================================
# Secondary Structure Detection (DSSP-like implementation)
# ===========================================================================

@dataclass
class SecondaryStructureAssignment:
    """
    Secondary structure assignment per residue.
    
    DSSP Codes:
        H: α-helix
        E: β-strand (extended)
        C: Coil/Loop
        G: 3₁₀-helix
        I: π-helix
        T: Turn
        B: β-bridge
    """
    residue_index: int
    dssp_code: str
    phi: float
    psi: float
    hydrogen_bond: Optional[Tuple[int, float]] = None


class SecondaryStructureCalculator:
    """
    Calculate secondary structure from Cα coordinates.
    
    Uses geometric criteria based on backbone dihedral angles
    and hydrogen bonding patterns.
    
    Reference:
        Kabsch & Sander (1983). "Dictionary of protein secondary structure"
    """
    
    # Ramachandran region boundaries for secondary structure
    ALPHA_HELIX_PHI = (-80, -40)
    ALPHA_HELIX_PSI = (-60, -20)
    
    BETA_STRAND_PHI = (-150, -90)
    BETA_STRAND_PSI = (90, 150)
    
    # Distance criteria
    HELIX_CA_DISTANCE = 5.5      # Å between i and i+4 for α-helix
    HELIX_DISTANCE_TOL = 1.0
    
    STRAND_CA_DISTANCE = 6.5     # Å between adjacent strands
    
    def __init__(self):
        logger.info("secondary_structure_calculator_initialized")
    
    def calculate(
        self,
        ca_coords: npt.NDArray[np.float64],
        all_coords: Optional[Dict[str, npt.NDArray[np.float64]]] = None
    ) -> List[SecondaryStructureAssignment]:
        """
        Calculate secondary structure for entire chain.
        
        Args:
            ca_coords: Cα coordinates, shape (n_residues, 3)
            all_coords: Optional dict with N, C, O coords for H-bond calc
        
        Returns:
            List of SecondaryStructureAssignment for each residue
        """
        n_residues = len(ca_coords)
        assignments = []
        
        # Calculate phi/psi angles (simplified from Cα only)
        phi_psi = self._estimate_phi_psi_from_ca(ca_coords)
        
        # Initial assignment based on Ramachandran regions
        raw_ss = ['C'] * n_residues  # Default to coil
        
        for i in range(n_residues):
            phi, psi = phi_psi[i]
            
            # Check alpha helix region
            if self._in_range(phi, self.ALPHA_HELIX_PHI) and \
               self._in_range(psi, self.ALPHA_HELIX_PSI):
                raw_ss[i] = 'H'
            
            # Check beta strand region  
            elif self._in_range(phi, self.BETA_STRAND_PHI) and \
                 self._in_range(psi, self.BETA_STRAND_PSI):
                raw_ss[i] = 'E'
        
        # Refine using distance patterns
        raw_ss = self._refine_by_distance(raw_ss, ca_coords)
        
        # Smooth assignments (remove isolated assignments)
        raw_ss = self._smooth_assignments(raw_ss, min_length=3)
        
        # Build final assignments
        for i in range(n_residues):
            assignments.append(SecondaryStructureAssignment(
                residue_index=i,
                dssp_code=raw_ss[i],
                phi=phi_psi[i][0],
                psi=phi_psi[i][1]
            ))
        
        return assignments
    
    def _estimate_phi_psi_from_ca(
        self,
        ca_coords: npt.NDArray[np.float64]
    ) -> List[Tuple[float, float]]:
        """
        Estimate phi/psi angles from Cα-only coordinates.
        
        Uses virtual bond model where backbone is approximated
        by Cα-Cα vectors.
        """
        n = len(ca_coords)
        phi_psi = []
        
        for i in range(n):
            if i < 2 or i >= n - 2:
                # Terminal residues: assign to coil region
                phi_psi.append((0.0, 0.0))
            else:
                # Calculate pseudo dihedral from 4 consecutive Cα
                v1 = ca_coords[i-1] - ca_coords[i-2]
                v2 = ca_coords[i] - ca_coords[i-1]
                v3 = ca_coords[i+1] - ca_coords[i]
                v4 = ca_coords[i+2] - ca_coords[i+1]
                
                phi = self._calc_dihedral(v1, v2, v3)
                psi = self._calc_dihedral(v2, v3, v4)
                
                phi_psi.append((np.degrees(phi), np.degrees(psi)))
        
        return phi_psi
    
    def _calc_dihedral(
        self,
        v1: npt.NDArray[np.float64],
        v2: npt.NDArray[np.float64],
        v3: npt.NDArray[np.float64]
    ) -> float:
        """Calculate dihedral angle from three vectors."""
        # Normal vectors to planes
        n1 = np.cross(v1, v2)
        n2 = np.cross(v2, v3)
        
        # Normalize
        n1_norm = np.linalg.norm(n1)
        n2_norm = np.linalg.norm(n2)
        
        if n1_norm < 1e-10 or n2_norm < 1e-10:
            return 0.0
        
        n1 = n1 / n1_norm
        n2 = n2 / n2_norm
        
        # Calculate angle
        cos_angle = np.clip(np.dot(n1, n2), -1.0, 1.0)
        angle = np.arccos(cos_angle)
        
        # Determine sign
        if np.dot(np.cross(n1, n2), v2) < 0:
            angle = -angle
        
        return angle
    
    def _in_range(
        self,
        value: float,
        range_tuple: Tuple[float, float]
    ) -> bool:
        """Check if value is in range (handles wrap-around for angles)."""
        low, high = range_tuple
        if low <= high:
            return low <= value <= high
        else:
            return value >= low or value <= high
    
    def _refine_by_distance(
        self,
        raw_ss: List[str],
        ca_coords: npt.NDArray[np.float64]
    ) -> List[str]:
        """
        Refine secondary structure using Cα distance patterns.
        
        α-helix: ~5.4 Å between i and i+4
        β-strand: parallel/antiparallel patterns
        """
        n = len(raw_ss)
        refined = raw_ss.copy()
        
        # Check helix pattern (i, i+4 distance)
        for i in range(n - 4):
            if raw_ss[i] == 'H':
                dist = np.linalg.norm(ca_coords[i+4] - ca_coords[i])
                if abs(dist - self.HELIX_CA_DISTANCE) > self.HELIX_DISTANCE_TOL:
                    refined[i] = 'C'
        
        return refined
    
    def _smooth_assignments(
        self,
        raw_ss: List[str],
        min_length: int = 3
    ) -> List[str]:
        """
        Remove isolated secondary structure assignments.
        
        Helices/strands must be at least min_length residues.
        """
        n = len(raw_ss)
        smoothed = raw_ss.copy()
        
        i = 0
        while i < n:
            ss_type = smoothed[i]
            
            if ss_type in ['H', 'E']:
                # Find extent of this element
                j = i
                while j < n and smoothed[j] == ss_type:
                    j += 1
                
                length = j - i
                
                # Convert short elements to coil
                if length < min_length:
                    for k in range(i, j):
                        smoothed[k] = 'C'
                
                i = j
            else:
                i += 1
        
        return smoothed
    
    def get_summary(
        self,
        assignments: List[SecondaryStructureAssignment]
    ) -> Dict[str, Any]:
        """
        Get summary statistics for secondary structure.
        
        Returns:
            Dictionary with counts and fractions per SS type
        """
        n = len(assignments)
        
        counts = {'H': 0, 'E': 0, 'C': 0, 'G': 0, 'I': 0, 'T': 0, 'B': 0}
        
        for a in assignments:
            if a.dssp_code in counts:
                counts[a.dssp_code] += 1
            else:
                counts['C'] += 1
        
        fractions = {k: v / n if n > 0 else 0.0 for k, v in counts.items()}
        
        return {
            'n_residues': n,
            'counts': counts,
            'fractions': fractions,
            'helix_fraction': fractions.get('H', 0) + fractions.get('G', 0) + fractions.get('I', 0),
            'strand_fraction': fractions.get('E', 0) + fractions.get('B', 0),
            'coil_fraction': fractions.get('C', 0) + fractions.get('T', 0)
        }


# ===========================================================================
# Binding Pocket Detection
# ===========================================================================

@dataclass
class BindingPocket:
    """
    Detected binding pocket from structure.
    """
    pocket_id: int
    center: npt.NDArray[np.float64]
    radius: float
    residue_indices: List[int]
    volume_estimate: float
    druggability_score: float


class BindingPocketDetector:
    """
    Detect potential binding pockets from AlphaFold structures.
    
    Uses cavity detection based on:
        1. Surface concavity analysis
        2. Residue clustering
        3. Geometry-based scoring
    """
    
    def __init__(
        self,
        min_pocket_residues: int = 5,
        probe_radius: float = 1.4,  # Water molecule size
        cavity_threshold: float = 5.0
    ):
        self.min_pocket_residues = min_pocket_residues
        self.probe_radius = probe_radius
        self.cavity_threshold = cavity_threshold
    
    def detect_pockets(
        self,
        ca_coords: npt.NDArray[np.float64],
        plddt: Optional[npt.NDArray[np.float64]] = None
    ) -> List[BindingPocket]:
        """
        Detect binding pockets from Cα coordinates.
        
        Algorithm:
            1. Find surface residues (exposed to solvent)
            2. Identify concave regions
            3. Cluster nearby concave residues
            4. Score clusters by druggability metrics
        
        Args:
            ca_coords: Cα coordinates, shape (n_residues, 3)
            plddt: Optional confidence scores (used for filtering)
        
        Returns:
            List of detected binding pockets
        """
        n_residues = len(ca_coords)
        
        # Calculate local curvature/concavity
        curvature = self._calculate_local_curvature(ca_coords)
        
        # Identify concave residues
        concave_mask = curvature < -self.cavity_threshold
        concave_indices = np.where(concave_mask)[0]
        
        if len(concave_indices) < self.min_pocket_residues:
            return []
        
        # Cluster concave residues spatially
        clusters = self._cluster_residues(
            ca_coords[concave_indices],
            concave_indices,
            distance_cutoff=10.0
        )
        
        # Build pocket objects
        pockets = []
        
        for pocket_id, residue_indices in enumerate(clusters):
            if len(residue_indices) < self.min_pocket_residues:
                continue
            
            pocket_coords = ca_coords[residue_indices]
            center = np.mean(pocket_coords, axis=0)
            
            # Estimate radius as max distance from center
            distances = np.linalg.norm(pocket_coords - center, axis=1)
            radius = np.max(distances)
            
            # Estimate volume (spherical approximation)
            volume = (4/3) * np.pi * radius**3
            
            # Druggability score based on size and pLDDT
            druggability = self._score_druggability(
                residue_indices,
                ca_coords,
                plddt
            )
            
            pockets.append(BindingPocket(
                pocket_id=pocket_id,
                center=center,
                radius=radius,
                residue_indices=residue_indices,
                volume_estimate=volume,
                druggability_score=druggability
            ))
        
        # Sort by druggability
        pockets.sort(key=lambda p: p.druggability_score, reverse=True)
        
        return pockets
    
    def _calculate_local_curvature(
        self,
        ca_coords: npt.NDArray[np.float64],
        window: int = 5
    ) -> npt.NDArray[np.float64]:
        """
        Calculate local curvature at each residue.
        
        Negative curvature = concave (potential pocket)
        Positive curvature = convex (exposed surface)
        """
        n = len(ca_coords)
        curvature = np.zeros(n)
        
        for i in range(n):
            # Get local neighborhood
            start = max(0, i - window)
            end = min(n, i + window + 1)
            local_coords = ca_coords[start:end]
            
            if len(local_coords) < 3:
                continue
            
            # Fit plane to local neighborhood
            centroid = np.mean(local_coords, axis=0)
            centered = local_coords - centroid
            
            # PCA to find normal
            _, _, vh = np.linalg.svd(centered)
            normal = vh[2]  # Smallest eigenvector = normal
            
            # Curvature = deviation from plane
            distances_to_plane = np.dot(centered, normal)
            
            # Signed curvature based on position relative to neighbors
            curvature[i] = np.mean(distances_to_plane)
        
        return curvature
    
    def _cluster_residues(
        self,
        coords: npt.NDArray[np.float64],
        indices: npt.NDArray[np.int64],
        distance_cutoff: float
    ) -> List[List[int]]:
        """
        Cluster residues by spatial proximity.
        
        Simple single-linkage clustering.
        """
        n = len(coords)
        
        if n == 0:
            return []
        
        # Distance matrix
        dist_matrix = np.zeros((n, n))
        for i in range(n):
            for j in range(i + 1, n):
                dist = np.linalg.norm(coords[i] - coords[j])
                dist_matrix[i, j] = dist
                dist_matrix[j, i] = dist
        
        # Single linkage clustering
        visited = set()
        clusters = []
        
        for i in range(n):
            if i in visited:
                continue
            
            # BFS to find cluster
            cluster = []
            queue = [i]
            
            while queue:
                current = queue.pop(0)
                if current in visited:
                    continue
                
                visited.add(current)
                cluster.append(int(indices[current]))
                
                # Add neighbors
                for j in range(n):
                    if j not in visited and dist_matrix[current, j] < distance_cutoff:
                        queue.append(j)
            
            if cluster:
                clusters.append(cluster)
        
        return clusters
    
    def _score_druggability(
        self,
        residue_indices: List[int],
        ca_coords: npt.NDArray[np.float64],
        plddt: Optional[npt.NDArray[np.float64]]
    ) -> float:
        """
        Score pocket druggability.
        
        Based on:
            - Pocket size (larger = better, up to limit)
            - pLDDT confidence (higher = more reliable)
            - Geometric compactness
        """
        n_residues = len(residue_indices)
        
        # Size score (optimal around 15-30 residues)
        size_score = 1.0 - abs(n_residues - 22) / 30
        size_score = max(0, min(1, size_score))
        
        # Confidence score
        if plddt is not None:
            pocket_plddt = plddt[residue_indices]
            confidence_score = np.mean(pocket_plddt) / 100.0
        else:
            confidence_score = 0.5
        
        # Compactness score
        pocket_coords = ca_coords[residue_indices]
        center = np.mean(pocket_coords, axis=0)
        distances = np.linalg.norm(pocket_coords - center, axis=1)
        compactness = 1.0 / (1.0 + np.std(distances) / 5.0)
        
        # Combined score
        score = (0.3 * size_score + 0.4 * confidence_score + 0.3 * compactness)
        
        return float(score)


# ===========================================================================
# Main Feature Extractor
# ===========================================================================

@dataclass
class StructureFeatures:
    """
    Complete structural features for a protein.
    """
    uniprot_id: str
    
    # Basic geometry
    n_residues: int
    ca_coordinates: npt.NDArray[np.float64]
    plddt_scores: npt.NDArray[np.float64]
    distance_matrix: npt.NDArray[np.float64]
    contact_map: npt.NDArray[np.bool_]
    
    # Secondary structure
    secondary_structure: List[SecondaryStructureAssignment]
    ss_summary: Dict[str, Any]
    ss_sequence: str  # String like "HHHHEEEECCCC"
    
    # Binding pockets
    binding_pockets: List[BindingPocket]
    
    # Aggregate features (for ML)
    feature_vector: Optional[npt.NDArray[np.float64]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'uniprot_id': self.uniprot_id,
            'n_residues': self.n_residues,
            'ss_summary': self.ss_summary,
            'ss_sequence': self.ss_sequence,
            'n_pockets': len(self.binding_pockets),
            'mean_plddt': float(np.mean(self.plddt_scores)),
            'plddt_std': float(np.std(self.plddt_scores))
        }


class StructureFeatureExtractor:
    """
    Extract comprehensive features from AlphaFold structures.
    
    Features Include:
        - Secondary structure (DSSP-like)
        - Binding pocket detection
        - Contact maps and distance matrices
        - Geometric features (radius of gyration, etc.)
        - ML-ready feature vectors
    
    Patent-pending framework by Santiago Maniches
    (ORCID: 0009-0005-6480-1987)
    """
    
    def __init__(
        self,
        contact_threshold: float = 8.0,
        seed: int = 42
    ):
        self.contact_threshold = contact_threshold
        self.seed = seed
        
        # Initialize sub-components
        self.ss_calculator = SecondaryStructureCalculator()
        self.pocket_detector = BindingPocketDetector()
        
        logger.info(
            "feature_extractor_initialized",
            timestamp=datetime.now(timezone.utc).isoformat(),
            contact_threshold=contact_threshold
        )
    
    def extract(
        self,
        structure  # AlphaFoldStructure
    ) -> StructureFeatures:
        """
        Extract all features from AlphaFold structure.
        
        Args:
            structure: AlphaFoldStructure object
        
        Returns:
            StructureFeatures with all computed features
        """
        start_time = datetime.now(timezone.utc)
        
        # Basic coordinates
        ca_coords = structure.ca_coordinates
        plddt = structure.plddt_per_residue
        n_residues = len(ca_coords)
        
        # Distance and contact matrices (vectorized)
        distance_matrix = structure.get_distance_matrix()
        contact_map = distance_matrix < self.contact_threshold
        
        # Secondary structure
        ss_assignments = self.ss_calculator.calculate(ca_coords)
        ss_summary = self.ss_calculator.get_summary(ss_assignments)
        ss_sequence = ''.join(a.dssp_code for a in ss_assignments)
        
        # Binding pockets
        pockets = self.pocket_detector.detect_pockets(ca_coords, plddt)
        
        # Build feature vector for ML
        feature_vector = self._build_feature_vector(
            ca_coords, plddt, ss_summary, pockets, distance_matrix
        )
        
        features = StructureFeatures(
            uniprot_id=structure.uniprot_id,
            n_residues=n_residues,
            ca_coordinates=ca_coords,
            plddt_scores=plddt,
            distance_matrix=distance_matrix,
            contact_map=contact_map,
            secondary_structure=ss_assignments,
            ss_summary=ss_summary,
            ss_sequence=ss_sequence,
            binding_pockets=pockets,
            feature_vector=feature_vector
        )
        
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        
        logger.info(
            "features_extracted",
            uniprot_id=structure.uniprot_id,
            n_residues=n_residues,
            helix_fraction=ss_summary['helix_fraction'],
            strand_fraction=ss_summary['strand_fraction'],
            n_pockets=len(pockets),
            duration_seconds=duration
        )
        
        return features
    
    def _build_feature_vector(
        self,
        ca_coords: npt.NDArray[np.float64],
        plddt: npt.NDArray[np.float64],
        ss_summary: Dict[str, Any],
        pockets: List[BindingPocket],
        distance_matrix: npt.NDArray[np.float64]
    ) -> npt.NDArray[np.float64]:
        """
        Build fixed-size feature vector for ML.
        
        Feature Vector (32 dimensions):
            [0-2]:   Size features (n_residues, log_n, normalized)
            [3-6]:   pLDDT statistics (mean, std, min, max)
            [7-9]:   Secondary structure fractions (helix, strand, coil)
            [10-12]: Radius of gyration features
            [13-15]: Contact density features
            [16-18]: Binding pocket features
            [19-31]: Reserved for topological features
        """
        n = len(ca_coords)
        
        features = np.zeros(32, dtype=np.float64)
        
        # Size features
        features[0] = n / 1000.0  # Normalized length
        features[1] = np.log1p(n) / 10.0
        features[2] = min(n / 500.0, 1.0)
        
        # pLDDT features
        features[3] = np.mean(plddt) / 100.0
        features[4] = np.std(plddt) / 50.0
        features[5] = np.min(plddt) / 100.0
        features[6] = np.max(plddt) / 100.0
        
        # Secondary structure
        features[7] = ss_summary['helix_fraction']
        features[8] = ss_summary['strand_fraction']
        features[9] = ss_summary['coil_fraction']
        
        # Radius of gyration
        centroid = np.mean(ca_coords, axis=0)
        distances_to_center = np.linalg.norm(ca_coords - centroid, axis=1)
        rg = np.sqrt(np.mean(distances_to_center**2))
        features[10] = rg / 50.0  # Normalized
        features[11] = np.max(distances_to_center) / 100.0
        features[12] = np.std(distances_to_center) / 30.0
        
        # Contact density
        n_contacts = np.sum(distance_matrix < 8.0) - n  # Exclude diagonal
        max_contacts = n * (n - 1)
        features[13] = n_contacts / max_contacts if max_contacts > 0 else 0
        features[14] = np.sum(distance_matrix < 5.0) / max_contacts if max_contacts > 0 else 0
        features[15] = np.sum(distance_matrix < 12.0) / max_contacts if max_contacts > 0 else 0
        
        # Binding pockets
        features[16] = min(len(pockets) / 5.0, 1.0)
        if pockets:
            features[17] = pockets[0].druggability_score
            features[18] = sum(p.volume_estimate for p in pockets) / 10000.0
        
        # Features 19-31 reserved for topological analysis
        
        return features


# Export for public API
__all__ = [
    'SecondaryStructureAssignment',
    'SecondaryStructureCalculator',
    'BindingPocket',
    'BindingPocketDetector',
    'StructureFeatures',
    'StructureFeatureExtractor',
]
