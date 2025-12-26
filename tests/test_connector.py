"""
Sovereign AlphaFold Connector - Test Suite
==========================================

Validates all components of the sovereign AlphaFold connector.
Run this to verify installation and functionality.

Santiago Maniches (ORCID: 0009-0005-6480-1987)
TOPOLOGICA LLC
"""

import sys
import os
from pathlib import Path
from datetime import datetime, timezone
import numpy as np

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

def test_pdb_parser():
    """Test PDB file parsing."""
    print("\n" + "="*60)
    print("[TEST] PDB Parser")
    print("="*60)
    
    from alphafold.parsers import PDBParser, AlphaFoldStructure
    
    # Initialize parser
    parser = PDBParser(
        structures_dir=Path(r"C:\TOPOLOGICA_KAGGLE_CAFA6\ALPHAFOLD2_STRUCTURES\pdb_files")
    )
    
    # Parse a single file
    test_file = Path(r"C:\TOPOLOGICA_KAGGLE_CAFA6\ALPHAFOLD2_STRUCTURES\pdb_files\A0A023FBW4.pdb")
    
    structure = parser.parse_file(test_file)
    
    print(f"  [OK] Parsed: {structure.uniprot_id}")
    print(f"  [OK] Residues: {structure.n_residues}")
    print(f"  [OK] Atoms: {len(structure.atoms)}")
    print(f"  [OK] Sequence length: {len(structure.sequence)}")
    print(f"  [OK] Mean pLDDT: {np.mean(structure.plddt_per_residue):.2f}")
    print(f"  [OK] Cα coords shape: {structure.ca_coordinates.shape}")
    print(f"  [OK] Organism: {structure.metadata.organism}")
    
    # Verify Cα coordinates
    assert structure.ca_coordinates.shape[0] == structure.n_residues
    assert structure.ca_coordinates.shape[1] == 3
    
    # Verify distance matrix
    dist_matrix = structure.get_distance_matrix()
    assert dist_matrix.shape == (structure.n_residues, structure.n_residues)
    assert np.allclose(dist_matrix, dist_matrix.T)  # Symmetric
    
    print(f"  [OK] Distance matrix shape: {dist_matrix.shape}")
    
    return structure


def test_core_connector():
    """Test core connector functionality."""
    print("\n" + "="*60)
    print("[TEST] Core Connector")
    print("="*60)
    
    from alphafold.core import SovereignAlphaFoldConnector
    
    # Initialize connector with default paths
    connector = SovereignAlphaFoldConnector(seed=42)
    
    print(f"  [OK] Total structures: {connector.n_structures}")
    
    # Test structure access
    test_id = "A0A023FBW4"
    
    assert connector.has_structure(test_id)
    print(f"  [OK] has_structure({test_id}): True")
    
    structure = connector.get_structure(test_id)
    print(f"  [OK] get_structure: {structure.n_residues} residues")
    
    # Test batch access
    test_ids = list(connector.available_ids)[:5]
    structures = connector.get_structures_batch(test_ids)
    print(f"  [OK] Batch loaded: {len(structures)} structures")
    
    # Test coordinate extraction
    coords = connector.get_ca_coordinates(test_id)
    print(f"  [OK] Cα coordinates: {coords.shape}")
    
    # Test pLDDT
    plddt = connector.get_plddt_scores(test_id)
    print(f"  [OK] pLDDT scores: mean={np.mean(plddt):.2f}")
    
    # Test statistics
    stats = connector.get_statistics()
    print(f"  [OK] Statistics: {stats['total_structures']} structures")
    
    return connector


def test_feature_extractor():
    """Test feature extraction."""
    print("\n" + "="*60)
    print("[TEST] Feature Extractor")
    print("="*60)
    
    from alphafold.core import SovereignAlphaFoldConnector
    from alphafold.features import StructureFeatureExtractor
    
    # Get a structure
    connector = SovereignAlphaFoldConnector(seed=42)
    structure = connector.get_structure("A0A023FBW4")
    
    # Extract features
    extractor = StructureFeatureExtractor(seed=42)
    features = extractor.extract(structure)
    
    print(f"  [OK] UniProt ID: {features.uniprot_id}")
    print(f"  [OK] N residues: {features.n_residues}")
    print(f"  [OK] SS sequence: {features.ss_sequence[:30]}...")
    print(f"  [OK] Helix fraction: {features.ss_summary['helix_fraction']:.3f}")
    print(f"  [OK] Strand fraction: {features.ss_summary['strand_fraction']:.3f}")
    print(f"  [OK] N pockets: {len(features.binding_pockets)}")
    print(f"  [OK] Feature vector shape: {features.feature_vector.shape}")
    
    # Verify feature vector
    assert features.feature_vector.shape == (32,)
    assert np.all(np.isfinite(features.feature_vector))
    
    return features


def test_topology_analyzer():
    """Test topological analysis."""
    print("\n" + "="*60)
    print("[TEST] Topology Analyzer")
    print("="*60)
    
    from alphafold.core import SovereignAlphaFoldConnector
    from alphafold.topology import StructureTopologyAnalyzer
    
    # Get a structure
    connector = SovereignAlphaFoldConnector(seed=42)
    structure = connector.get_structure("A0A023FBW4")
    
    # Analyze topology
    analyzer = StructureTopologyAnalyzer(
        max_dimension=2,
        max_filtration=30.0,
        seed=42
    )
    
    topo_features = analyzer.analyze(structure, subsample=50)
    
    print(f"  [OK] Betti 0: {topo_features.invariants.betti_0}")
    print(f"  [OK] Betti 1: {topo_features.invariants.betti_1}")
    print(f"  [OK] Betti 2: {topo_features.invariants.betti_2}")
    print(f"  [OK] Euler char: {topo_features.invariants.euler_characteristic}")
    print(f"  [OK] H1 features: {len(topo_features.persistence_h1)}")
    print(f"  [OK] Max H1 persistence: {topo_features.invariants.max_persistence_h1:.2f}")
    print(f"  [OK] Feature vector shape: {topo_features.feature_vector.shape}")
    print(f"  [OK] Computation time: {topo_features.computation_time:.3f}s")
    
    return topo_features


def test_cache():
    """Test cache functionality."""
    print("\n" + "="*60)
    print("[TEST] Cache System")
    print("="*60)
    
    from alphafold.cache import SovereignStructureCache
    
    # Initialize cache in temp directory
    cache_dir = Path(r"C:\TOPOLOGICA_KAGGLE_CAFA6\CACHE\test_cache")
    cache = SovereignStructureCache(cache_dir, auto_create=True)
    
    # Test put/get
    test_data = {"test": "data", "array": [1, 2, 3]}
    cache.put("test_key", test_data, "features")
    
    retrieved = cache.get("test_key", "features")
    assert retrieved == test_data
    print("  [OK] put/get: data matches")
    
    # Test numpy array
    test_array = np.random.randn(100, 3)
    cache.put("test_coords", test_array, "embedding")
    
    retrieved_array = cache.get("test_coords", "embedding")
    assert np.allclose(test_array, retrieved_array)
    print("  [OK] numpy array: data matches")
    
    # Test has
    assert cache.has("test_key", "features")
    assert not cache.has("nonexistent", "features")
    print("  [OK] has: works correctly")
    
    # Test statistics
    stats = cache.get_statistics()
    print(f"  [OK] Statistics: {stats['total_entries']} entries")
    
    # Test verification
    results = cache.verify_all()
    assert all(results.values())
    print("  [OK] Verification: all checksums valid")
    
    # Cleanup
    cache.clear()
    print("  [OK] Cache cleared")
    
    return cache


def run_all_tests():
    """Run complete test suite."""
    print("\n" + "#"*60)
    print("# SOVEREIGN ALPHAFOLD CONNECTOR - TEST SUITE")
    print("# Santiago Maniches (ORCID: 0009-0005-6480-1987)")
    print("# TOPOLOGICA LLC")
    print(f"# Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print("#"*60)
    
    results = {}
    
    try:
        test_pdb_parser()
        results['pdb_parser'] = 'PASS'
    except Exception as e:
        results['pdb_parser'] = f'FAIL: {e}'
        print(f"  [FAIL] {e}")
    
    try:
        test_core_connector()
        results['core_connector'] = 'PASS'
    except Exception as e:
        results['core_connector'] = f'FAIL: {e}'
        print(f"  [FAIL] {e}")
    
    try:
        test_feature_extractor()
        results['feature_extractor'] = 'PASS'
    except Exception as e:
        results['feature_extractor'] = f'FAIL: {e}'
        print(f"  [FAIL] {e}")
    
    try:
        test_topology_analyzer()
        results['topology_analyzer'] = 'PASS'
    except Exception as e:
        results['topology_analyzer'] = f'FAIL: {e}'
        print(f"  [FAIL] {e}")
    
    try:
        test_cache()
        results['cache'] = 'PASS'
    except Exception as e:
        results['cache'] = f'FAIL: {e}'
        print(f"  [FAIL] {e}")
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    n_pass = sum(1 for v in results.values() if v == 'PASS')
    n_total = len(results)
    
    for test_name, result in results.items():
        status = "✓" if result == 'PASS' else "✗"
        print(f"  {status} {test_name}: {result}")
    
    print(f"\nTotal: {n_pass}/{n_total} passed")
    
    if n_pass == n_total:
        print("\n✓ ALL TESTS PASSED - Sovereign AlphaFold Connector Ready!")
    else:
        print("\n✗ SOME TESTS FAILED - Review errors above")
    
    return results


if __name__ == "__main__":
    run_all_tests()
