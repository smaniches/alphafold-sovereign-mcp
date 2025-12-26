# AlphaFold Sovereign MCP Server
## TOPOLOGICA LLC - Private Research Infrastructure

**PROPRIETARY AND CONFIDENTIAL**  
**Patent-pending framework by Santiago Maniches (ORCID: 0009-0005-6480-1987)**  
**THIS SOFTWARE IS NOT FOR PUBLIC DISTRIBUTION**

---

## UNIQUE VALUE PROPOSITION

This MCP server goes **beyond AlphaFold** by integrating:

| Data Source | Information Provided |
|-------------|---------------------|
| **AlphaFold DB** | 3D structure, pLDDT confidence, coordinate data |
| **UniProt** | Protein function, GO annotations, active sites, disease links |
| **Computed Features** | Secondary structure analysis, binding pocket detection |
| **Topological Analysis** | Persistent homology (Betti numbers, Euler characteristic) |

**Result**: Complete protein characterization in a single query.

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
│  3. AUTO-CACHE FOR FUTURE ACCESS (if cache_mode=sovereign)      │
│     - Saved to: CACHE/online_structures/{ID}.pdb                │
│     - Added to local index (no restart needed)                  │
│     → Cache grows dynamically over time                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## TOOLS AVAILABLE (8 Total)

| Tool Name | Function |
|-----------|----------|
| `get_structure` | Retrieve AlphaFold structure (cache-first + online fallback) |
| `get_enriched_protein` | **NEW** Complete protein profile (AlphaFold + UniProt + features) |
| `search_structures` | Search local cache by glob pattern |
| `batch_structures` | Retrieve multiple structures efficiently |
| `get_features` | Compute secondary structure, binding pockets, confidence |
| `get_topology` | Compute persistent homology (Betti numbers, Euler characteristic) |
| `check_availability` | Check if structures exist locally/online |
| `get_cache_statistics` | Get current cache size, mode, and configuration |

---

## CONFIGURATION

### Method 1: Environment Variables (Highest Priority)

```bash
# Windows (PowerShell)
$env:ALPHAFOLD_STRUCTURES_DIR = "D:\my_structures\pdb_files"
$env:ALPHAFOLD_CACHE_DIR = "D:\my_cache"
$env:ALPHAFOLD_CACHE_MODE = "sovereign"

# Linux/Mac
export ALPHAFOLD_STRUCTURES_DIR="/data/alphafold/pdb_files"
export ALPHAFOLD_CACHE_DIR="/data/alphafold/cache"
export ALPHAFOLD_CACHE_MODE="sovereign"
```

### Method 2: Config File

Create `~/.alphafold_sovereign/config.json`:

```json
{
    "structures_dir": "/path/to/structures/pdb_files",
    "cache_dir": "/path/to/cache",
    "cache_mode": "sovereign"
}
```

### Cache Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| `sovereign` | Full read/write | Primary device with local storage |
| `readonly` | Read cache, no writes | Secondary device sharing NAS/cloud cache |
| `disabled` | Pure online, no cache | Mobile, temporary, or testing |

---

## MULTI-DEVICE SETUP

### Primary Device (Desktop with Storage)
```json
{
    "cache_mode": "sovereign",
    "structures_dir": "C:\\AlphaFold\\structures",
    "cache_dir": "C:\\AlphaFold\\cache"
}
```

### Secondary Device (Laptop)
```json
{
    "cache_mode": "readonly",
    "structures_dir": "\\\\NAS\\alphafold\\structures",
    "cache_dir": "\\\\NAS\\alphafold\\cache"
}
```

### Mobile/Temporary
```bash
export ALPHAFOLD_CACHE_MODE="disabled"
# All requests go to AlphaFold DB online
```

---

## USAGE EXAMPLES

### Get Enriched Protein Profile (Recommended)
```
Get enriched protein info for P53_HUMAN including GO terms and disease associations
```

Returns: Protein name, function, structure summary, GO annotations, active sites, disease links.

### Get Structure Only
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
Show me the AlphaFold cache statistics and configuration
```

---

## MATHEMATICAL FOUNDATION

### Structural Features
- **Secondary Structure**: Ramachandran angle-based (φ/ψ) with distance refinement
- **Binding Pockets**: Local curvature analysis (negative = concave = pocket)
- **Confidence Regions**: pLDDT-based quality classification

### Topological Features (Patent-Pending)
- **Vietoris-Rips Filtration**: VR(X, ε) for ε ∈ [0, ε_max]
- **Betti Numbers**: β₀ (components), β₁ (loops), β₂ (voids)
- **Euler Characteristic**: χ = β₀ - β₁ + β₂
- **Persistence Diagrams**: Birth/death pairs for topological features

---

## DIRECTORY STRUCTURE

```
C:\TOPOLOGICA_KAGGLE_CAFA6\                    # Default on Windows
├── ALPHAFOLD2_STRUCTURES\
│   └── pdb_files\           # Primary sovereign cache (bulk pre-downloaded)
└── CACHE\
    └── online_structures\   # Dynamic cache (auto-populated on fetch)

~/.alphafold_sovereign/                         # Linux/Mac config location
└── config.json              # User configuration
```

---

## CLAUDE DESKTOP CONFIG

Location: `C:\Users\<user>\AppData\Roaming\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "alphafold_sovereign": {
      "command": "C:\\Python\\python.exe",
      "args": ["path/to/alphafold_mcp.py"],
      "env": {
        "ALPHAFOLD_CACHE_MODE": "sovereign"
      }
    }
  }
}
```

---

## LOGS

MCP server logs appear in:
- Windows: `C:\Users\<user>\AppData\Roaming\Claude\logs\mcp-server-alphafold_sovereign.log`
- Linux/Mac: `~/.config/Claude/logs/mcp-server-alphafold_sovereign.log`

---

## API DEPENDENCIES (NO KEYS REQUIRED)

| API | Purpose | Auth |
|-----|---------|------|
| AlphaFold DB | 3D protein structures | Public |
| UniProt REST | Protein metadata | Public |

---

## INTELLECTUAL PROPERTY

This software implements patent-pending innovations:
- Drift tensor correction framework (R² = 0.9992)
- Topological data analysis for protein structures
- Sovereign computational infrastructure

All rights reserved. Unauthorized distribution prohibited.

---

© 2025 TOPOLOGICA LLC - Santiago Maniches (ORCID: 0009-0005-6480-1987)
