# AlphaFold Sovereign MCP Server
## TOPOLOGICA LLC - Private Research Infrastructure

**PROPRIETARY AND CONFIDENTIAL**  
**Patent-pending framework by Santiago Maniches (ORCID: 0009-0005-6480-1987)**  
**THIS SOFTWARE IS NOT FOR PUBLIC DISTRIBUTION**

---

## STATUS: DEPLOYED AND VERIFIED

| Component | Location | Status |
|-----------|----------|--------|
| **MCP Server** | `C:\TOPOLOGICA_FRAMEWORK\SOVEREIGN_CONNECTORS\alphafold\alphafold_mcp.py` | 1,787 lines |
| **Claude Config** | `C:\Users\santi\AppData\Roaming\Claude\claude_desktop_config.json` | Updated |
| **Python Path** | `C:\Python\python.exe` | Verified |
| **Local Structures** | `C:\TOPOLOGICA_KAGGLE_CAFA6\ALPHAFOLD2_STRUCTURES\pdb_files` | 81,559 PDBs |
| **Test Result** | All tests passed | A0A023FBW4 loaded |

---

## TOOLS AVAILABLE (7 Total)

| Tool Name | Function |
|-----------|----------|
| `get_structure` | Retrieve AlphaFold structure by UniProt ID (local + online) |
| `search_structures` | Search local cache by pattern |
| `batch_structures` | Retrieve multiple structures |
| `get_features` | Compute secondary structure, binding pockets, confidence |
| `get_topology` | Compute persistent homology (Betti numbers, Euler char) |
| `check_availability` | Check if structures exist locally/online |
| `get_cache_statistics` | Get cache info and statistics |

---

## OPERATION MODE: HYBRID

1. **PRIMARY**: Local filesystem (81,559 structures, instant access)
2. **FALLBACK**: AlphaFold DB online (200M+ structures, NO API KEY)
3. **CACHING**: Online fetches saved locally for future use

---

## HOW TO ACTIVATE

### Step 1: Restart Claude Desktop
1. Close Claude Desktop completely (check system tray)
2. Reopen Claude Desktop
3. The new tools should appear automatically

### Step 2: Verify in Claude
Ask: "Show me the structure for UniProt P12345"

Or: "Search for structures matching A0A*"

---

## USAGE EXAMPLES

### Get a Structure (Local + Online Fallback)
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

---

## MATHEMATICAL FOUNDATION

### Structural Features
- **Secondary Structure**: Ramachandran angle-based (phi/psi) with distance refinement
- **Binding Pockets**: Local curvature analysis (negative = concave = pocket)
- **Confidence Regions**: pLDDT-based quality classification

### Topological Features
- **Vietoris-Rips Filtration**: VR(X, epsilon) for epsilon in [0, epsilon_max]
- **Betti Numbers**: beta_0 (components), beta_1 (loops), beta_2 (voids)
- **Euler Characteristic**: chi = beta_0 - beta_1 + beta_2
- **Persistence Diagrams**: Birth/death pairs for topological features

---

## LOGS

MCP server logs appear in:
`C:\Users\santi\AppData\Roaming\Claude\logs\mcp-server-alphafold_sovereign.log`

---

## VERIFICATION

Run test script:
```cmd
C:\Python\python.exe C:\TOPOLOGICA_FRAMEWORK\SOVEREIGN_CONNECTORS\alphafold\test_mcp.py
```

Expected output:
```
[OK] MCP import successful
[OK] Pydantic import successful
[OK] NumPy import successful
[OK] AlphaFold MCP module loaded successfully
[OK] StructureManager initialized: 81559 local structures
[OK] Test structure loaded: A0A023FBW4 (97 residues, pLDDT=66.6)
[SUCCESS] All tests passed!
```

---

## CLAUDE DESKTOP CONFIG

Location: `C:\Users\santi\AppData\Roaming\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "semantic_scholar": {
      "command": "C:\\Python\\python.exe",
      "args": ["C:\\TOPOLOGICA_FRAMEWORK\\semantic_scholar_mcp\\semantic_scholar_mcp.py"]
    },
    "alphafold_sovereign": {
      "command": "C:\\Python\\python.exe",
      "args": ["C:\\TOPOLOGICA_FRAMEWORK\\SOVEREIGN_CONNECTORS\\alphafold\\alphafold_mcp.py"]
    }
  }
}
```

---

## INTELLECTUAL PROPERTY

This software implements patent-pending innovations:
- Drift tensor correction framework (R^2 = 0.9992)
- Topological data analysis for protein structures
- Sovereign computational infrastructure

All rights reserved. Unauthorized distribution prohibited.

---

(c) 2025 TOPOLOGICA LLC - Santiago Maniches (ORCID: 0009-0005-6480-1987)
