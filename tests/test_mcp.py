"""Test script for AlphaFold MCP server."""
import sys
sys.path.insert(0, r'C:\TOPOLOGICA_FRAMEWORK\SOVEREIGN_CONNECTORS\alphafold')

print("[TEST] Testing imports...")

try:
    from mcp.server.fastmcp import FastMCP
    print("[OK] MCP import successful")
except ImportError as e:
    print(f"[ERROR] MCP import failed: {e}")
    sys.exit(1)

try:
    from pydantic import BaseModel
    print("[OK] Pydantic import successful")
except ImportError as e:
    print(f"[ERROR] Pydantic import failed: {e}")
    sys.exit(1)

try:
    import numpy as np
    print("[OK] NumPy import successful")
except ImportError as e:
    print(f"[ERROR] NumPy import failed: {e}")
    sys.exit(1)

print("\n[TEST] Testing AlphaFold MCP module...")

try:
    # Import the main components
    exec(open(r'C:\TOPOLOGICA_FRAMEWORK\SOVEREIGN_CONNECTORS\alphafold\alphafold_mcp.py').read().split('if __name__')[0])
    print("[OK] AlphaFold MCP module loaded successfully")
    
    # Test structure manager
    manager = get_structure_manager()
    stats = manager.get_statistics()
    print(f"[OK] StructureManager initialized: {stats['local_structures']} local structures")
    
    # Test a local structure if available
    local_ids = manager.search_local(limit=1)
    if local_ids:
        test_id = local_ids[0]
        success, structure, error = manager.get_structure(test_id)
        if success:
            print(f"[OK] Test structure loaded: {test_id} ({structure.n_residues} residues, pLDDT={structure.mean_plddt:.1f})")
        else:
            print(f"[WARN] Could not load test structure: {error}")
    else:
        print("[WARN] No local structures found")
    
    print("\n[SUCCESS] All tests passed!")
    
except Exception as e:
    print(f"[ERROR] AlphaFold MCP module failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
