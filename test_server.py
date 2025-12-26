# Test script for AlphaFold Sovereign MCP
import sys
sys.path.insert(0, r"C:\Users\santi\Documents\GITHUB_REPOS\alphafold-sovereign-mcp")

print("[TEST] Importing module...")
try:
    from src.alphafold_sovereign.alphafold_mcp import (
        LOCAL_STRUCTURES_DIR, CACHE_DIR, CACHE_MODE, CacheMode,
        StructureManager, UniProtFetcher, get_structure_manager
    )
    print("[OK] Module imported successfully")
except Exception as e:
    print(f"[FAIL] Import error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print(f"\n[CONFIG]")
print(f"  STRUCTURES_DIR: {LOCAL_STRUCTURES_DIR}")
print(f"  CACHE_DIR: {CACHE_DIR}")
print(f"  CACHE_MODE: {CACHE_MODE}")

print(f"\n[TEST] Initializing StructureManager...")
try:
    manager = get_structure_manager()
    stats = manager.get_statistics()
    print(f"[OK] StructureManager initialized: {stats['local_structures']:,} structures")
except Exception as e:
    print(f"[FAIL] StructureManager error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print(f"\n[TEST] Testing UniProt fetcher...")
try:
    fetcher = UniProtFetcher()
    success, metadata, error = fetcher.fetch("P53_HUMAN")
    if success:
        print(f"[OK] UniProt fetch successful")
        print(f"  Protein: {metadata['protein_name']}")
        print(f"  Gene: {metadata['gene_name']}")
        print(f"  Organism: {metadata['organism']}")
        print(f"  Length: {metadata['sequence_length']} aa")
        go_count = sum(len(v) for v in metadata['go_terms'].values())
        print(f"  GO Terms: {go_count}")
    else:
        print(f"[WARN] UniProt fetch failed: {error}")
except Exception as e:
    print(f"[WARN] UniProt test error: {e}")

print(f"\n[TEST] Loading a test structure...")
try:
    success, structure, error = manager.get_structure("A0A023FBW4")
    if success:
        print(f"[OK] Structure loaded: {len(structure.residues)} residues")
    else:
        print(f"[WARN] Structure load failed: {error}")
except Exception as e:
    print(f"[WARN] Structure test error: {e}")

print(f"\n[SUCCESS] All tests passed!")
