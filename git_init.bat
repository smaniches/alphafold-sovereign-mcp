@echo off
cd /d "C:\Users\santi\Documents\GITHUB_REPOS\alphafold-sovereign-mcp"
"C:\Program Files\Git\cmd\git.exe" init
"C:\Program Files\Git\cmd\git.exe" add .
"C:\Program Files\Git\cmd\git.exe" commit -m "feat: Initial release - AlphaFold Sovereign MCP Server

- Hybrid local/online AlphaFold structure access (81,559+ cached)
- 7 MCP tools: get_structure, search, batch, features, topology, availability, stats
- Modular architecture: core, cache, features, fetcher, parsers, topology
- Secondary structure, binding pockets, confidence analysis
- Persistent homology: Betti numbers, Euler characteristic
- Proprietary topological analysis framework

Author: Santiago Maniches (ORCID: 0009-0005-6480-1987)
TOPOLOGICA LLC - Patent-pending innovations"

"C:\Program Files\Git\cmd\git.exe" branch -M main
"C:\Program Files\Git\cmd\git.exe" remote add origin https://github.com/smaniches/alphafold-sovereign-mcp.git
"C:\Program Files\Git\cmd\git.exe" push -u origin main
