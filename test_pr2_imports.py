import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r'C:\Users\santi\Documents\GITHUB_REPOS\alphafold-sovereign-mcp\src')

print("Testing imports...")

try:
    from alphafold_sovereign.alphafold_mcp import (
        # Original tools
        get_structure, search_structures, batch_structures,
        get_features, get_topology, check_availability,
        get_cache_statistics, get_enriched_protein,
        # NEW PR #2 tools
        batch_go_lookup, search_by_go_term, get_go_hierarchy,
        export_protein_set, find_similar_proteins,
        get_domain_annotations, filter_by_organism, get_protein_families,
        # Input models
        BatchGOLookupInput, SearchByGOTermInput, GetGOHierarchyInput,
        ExportProteinSetInput, FindSimilarProteinsInput,
        GetDomainAnnotationsInput, FilterByOrganismInput, GetProteinFamiliesInput,
        # Cache classes
        GOAnnotationCache, SequenceDatabase
    )
    print("SUCCESS: All imports work!")
    print()
    print("TOOLS AVAILABLE:")
    print("  Original (8):")
    print("    - get_structure")
    print("    - search_structures")
    print("    - batch_structures")
    print("    - get_features")
    print("    - get_topology")
    print("    - check_availability")
    print("    - get_cache_statistics")
    print("    - get_enriched_protein")
    print()
    print("  NEW PR #2 (8):")
    print("    - batch_go_lookup")
    print("    - search_by_go_term")
    print("    - get_go_hierarchy")
    print("    - export_protein_set")
    print("    - find_similar_proteins")
    print("    - get_domain_annotations")
    print("    - filter_by_organism")
    print("    - get_protein_families")
    print()
    print("  TOTAL: 16 tools")
    
except Exception as e:
    print(f"IMPORT ERROR: {e}")
    import traceback
    traceback.print_exc()
