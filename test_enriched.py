import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r'C:\Users\santi\Documents\GITHUB_REPOS\alphafold-sovereign-mcp\src')

import asyncio
from alphafold_sovereign.alphafold_mcp import get_enriched_protein, GetEnrichedProteinInput, ResponseFormat

async def test():
    params = GetEnrichedProteinInput(
        uniprot_id="A0A023FBW4",
        include_structure=True,
        include_go_terms=True,
        include_disease=True,
        include_features=True,
        response_format=ResponseFormat.MARKDOWN
    )
    result = await get_enriched_protein(params)
    print("SUCCESS!")
    print("=" * 60)
    # Replace Greek letters for Windows console
    safe_result = result.replace('\u03b1', 'alpha').replace('\u03b2', 'beta')
    print(safe_result[:2500])
    print("\n... [truncated]")

asyncio.run(test())
