# AlphaFold Sovereign MCP Server
## TOPOLOGICA LLC - Private Research Infrastructure

**PROPRIETARY AND CONFIDENTIAL**  
**Patent-pending framework by Santiago Maniches (ORCID: 0009-0005-6480-1987)**  
**THIS SOFTWARE IS NOT FOR PUBLIC DISTRIBUTION**

---

## ARCHITECTURE: SOVEREIGN CACHE-FIRST

```
┌─────────────────────────────────────────────────────────────────┐
│                    QUERY: get_structure(P12345)                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  1. CHECK LOCAL INDEX (O(1) hash lookup)                        │
│     - Primary: ALPHAFOLD2_STRUCTURES/pdb_files/                 │
│     - Secondary: CACHE/online_structures/                       │
│     → FOUND? Return immediately (sovereign, no network)         │
└─────────────────────────────────────────────────────────────────┘
                              │ NOT FOUND
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. FETCH FROM ALPHAFOLD DB (network)                           │
│     - URL: https://alphafold.ebi.ac.uk/files/AF-{ID}-F1-*.pdb   │
│     - NO API KEY REQUIRED                                       │
│     - Auto-retry with exponential backoff                       │
└─────────────────────────────────────────────────────────────────┘
                              │ SUCCESS
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. AUTO-CACHE FOR FUTURE ACCESS                                │
│     - Saved to: CACHE/online_structures/{ID}.pdb                │
│     - Added to local index (no restart needed)                  │
│     → Cache grows dynamically over time                         │
└─────────────────────────────────────────────────────────────────┘
```

**Key Property**: The local cache grows dynamically. Every structure fetched online is automatically cached for sovereign future access. The index is rebuilt on startup to include all cached structures.

---

## TOOLS AVAILABLE (7 Total)

| Tool Name | Function |
|-----------|----------|
| `get_structure` | Retrieve AlphaFold structure by UniProt ID (cache-first + online fallback) |
| `search_structures` | Search local cache by glob pattern |
| `batch_structures` | Retrieve multiple structures efficiently |
| `get_features` | Compute secondary structure, binding pockets, confidence |
| `get_topology` | Compute persistent homology (Betti numbers, Euler characteristic) |
| `check_availability` | Check if structures exist locally/online |
| `get_cache_statistics` | Get current cache size and statistics |

---

## OPERATION MODE: HYBRID SOVEREIGN

| Priority | Source | Latency | Coverage |
|----------|--------|---------|----------|
| 1st | Local sovereign cache | O(1) instant | Grows dynamically |
| 2nd | AlphaFold DB online | ~1-3 sec | 200M+ structures |
| 3rd | Auto-cache on fetch | — | Prevents re-fetch |

**Sovereign Principle**: Once a structure is fetched, it never needs to be fetched again. The cache is perpetual and grows with usage.

---

## USAGE EXAMPLES

### Get a Structure (Cache-First + Online Fallback)
```
Get the AlphaFold structure for P12345 with features
```

### Search Local Cache
```
Search for all structures matching pattern Q9* in local cache
```

### Compute Topology
```
Compute persistent homology for structure A0A023FBW4
```

### Batch Retrieval
```
Get structures for: P53_HUMAN, EGFR_HUMAN, BRCA1_HUMAN
```

### Check Cache Statistics
```
Show me the AlphaFold cache statistics
```

---

## MATHEMATICAL FOUNDATION

### Structural Features
- **Secondary Structure**: Ramachandran angle-based (φ/ψ) with distance refinement
- **Binding Pockets**: Local curvature analysis (negative = concave = pocket)
- **Confidence Regions**: pLDDT-based quality classification

### Topological Features
- **Vietoris-Rips Filtration**: VR(X, ε) for ε ∈ [0, ε_max]
- **Betti Numbers**: β₀ (components), β₁ (loops), β₂ (voids)
- **Euler Characteristic**: χ = β₀ - β₁ + β₂
- **Persistence Diagrams**: Birth/death pairs for topological features

---

## CONFIGURATION

### Directory Structure
```
C:\TOPOLOGICA_KAGGLE_CAFA6\
├── ALPHAFOLD2_STRUCTURES\
│   └── pdb_files\           # Primary sovereign cache (bulk pre-downloaded)
└── CACHE\
    └── online_structures\   # Dynamic cache (auto-populated on fetch)
```

### Claude Desktop Config
Location: `C:\Users\santi\AppData\Roaming\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "alphafold_sovereign": {
      "command": "C:\\Python\\python.exe",
      "args": ["path/to/alphafold_mcp.py"]
    }
  }
}
```

---

## LOGS

MCP server logs appear in:
`C:\Users\santi\AppData\Roaming\Claude\logs\mcp-server-alphafold_sovereign.log`

---

## INTELLECTUAL PROPERTY

This software implements patent-pending innovations:
- Drift tensor correction framework (R² = 0.9992)
- Topological data analysis for protein structures
- Sovereign computational infrastructure

All rights reserved. Unauthorized distribution prohibited.

---

© 2025 TOPOLOGICA LLC - Santiago Maniches (ORCID: 0009-0005-6480-1987)
