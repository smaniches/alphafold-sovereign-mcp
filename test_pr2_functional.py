import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r'C:\Users\santi\Documents\GITHUB_REPOS\alphafold-sovereign-mcp\src')

import asyncio
from alphafold_sovereign.alphafold_mcp import (
    batch_go_lookup, BatchGOLookupInput, ResponseFormat,
    get_go_hierarchy, GetGOHierarchyInput,
    GOAnnotationCache
)

async def test_batch_go():
    print("=" * 60)
    print("TEST 1: batch_go_lookup (3 proteins)")
    print("=" * 60)
    
    params = BatchGOLookupInput(
        uniprot_ids=["P04637", "P00533", "P38398"],  # p53, EGFR, BRCA1
        namespaces=["molecular_function", "biological_process"],
        response_format=ResponseFormat.MARKDOWN
    )
    result = await batch_go_lookup(params)
    # Truncate for display
    print(result[:1500])
    print("\n... [truncated]")

async def test_go_hierarchy():
    print()
    print("=" * 60)
    print("TEST 2: get_go_hierarchy (kinase activity)")
    print("=" * 60)
    
    params = GetGOHierarchyInput(
        go_term="GO:0016301",  # kinase activity
        direction="both",
        depth=2,
        response_format=ResponseFormat.MARKDOWN
    )
    result = await get_go_hierarchy(params)
    print(result[:1000])

async def test_cache():
    print()
    print("=" * 60)
    print("TEST 3: GO Cache Statistics")
    print("=" * 60)
    
    cache = GOAnnotationCache()
    stats = cache.get_statistics()
    print(f"Proteins indexed: {stats['proteins_indexed']}")
    print(f"GO terms indexed: {stats['go_terms_indexed']}")
    print(f"Cache dir: {stats['cache_dir']}")

async def main():
    await test_batch_go()
    await test_go_hierarchy()
    await test_cache()
    print()
    print("=" * 60)
    print("ALL TESTS PASSED!")
    print("=" * 60)

asyncio.run(main())
