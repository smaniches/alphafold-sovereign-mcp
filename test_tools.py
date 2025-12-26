import sys
sys.path.insert(0, r'C:\Users\santi\Documents\GITHUB_REPOS\alphafold-sovereign-mcp\src')

try:
    from alphafold_sovereign.alphafold_mcp import mcp
    tools = [t.name for t in mcp._tool_manager._tools.values()]
    print(f"SUCCESS: Found {len(tools)} tools")
    for t in tools:
        print(f"  - {t}")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
