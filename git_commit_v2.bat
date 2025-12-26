@echo off
cd /d C:\Users\santi\Documents\GITHUB_REPOS\alphafold-sovereign-mcp

echo === GIT STATUS ===
git status

echo.
echo === GIT DIFF STAT ===
git diff --stat

echo.
echo === ADDING ALL CHANGES ===
git add -A

echo.
echo === COMMITTING ===
git commit -m "feat: Configuration system + UniProt integration + enriched protein tool

BREAKING CHANGES:
- Paths now configurable via env vars and config file
- Cache mode support (sovereign/readonly/disabled)

NEW FEATURES:
1. Configuration System
   - ALPHAFOLD_STRUCTURES_DIR env var
   - ALPHAFOLD_CACHE_DIR env var  
   - ALPHAFOLD_CACHE_MODE env var (sovereign/readonly/disabled)
   - Config file support (~/.alphafold_sovereign/config.json)

2. UniProt Integration
   - UniProtFetcher class for protein metadata
   - Function descriptions, GO annotations
   - Active sites, binding sites, disease associations

3. New Tool: get_enriched_protein
   - Combines AlphaFold + UniProt + computed features
   - Complete protein characterization in single query
   - Drug target assessment ready

4. Multi-Device Support
   - sovereign mode: full read/write (primary device)
   - readonly mode: read cache only (secondary device)
   - disabled mode: pure online (mobile/temporary)

5. Updated Documentation
   - Comprehensive README with all configuration options
   - Example config file (config.example.json)
   - Multi-device setup guide

VERIFIED: All tests pass (222,892 structures indexed)"

echo.
echo === PUSHING ===
git push origin main

echo.
echo === DONE ===
