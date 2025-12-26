# AlphaFold Sovereign MCP

Production-grade MCP server for sovereign AlphaFold structure analysis with local-first architecture and advanced topological computation.

## Features

- **25 API Tools** for comprehensive protein structure analysis
- **222,891 Local Structures** with dynamic indexing
- **200M+ Online Fallback** via AlphaFold DB (no API key required)
- **Persistent Homology** via Vietoris-Rips filtration
- **GO Semantic Analysis** with information content metrics
- **Multi-device Support** with configurable cache modes

## Quick Start

### Installation

```bash
git clone https://github.com/topologica-ai/alphafold-sovereign-mcp.git
cd alphafold-sovereign-mcp
pip install -e .
```

### Claude Desktop Integration

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "alphafold-sovereign": {
      "command": "python",
      "args": ["-m", "alphafold_sovereign"],
      "env": {
        "ALPHAFOLD_STRUCTURES_DIR": "/path/to/pdb_files",
        "ALPHAFOLD_CACHE_DIR": "/path/to/cache"
      }
    }
  }
}
```

## Configuration

Configuration priority (highest to lowest):

1. **Environment variables**: `ALPHAFOLD_STRUCTURES_DIR`, `ALPHAFOLD_CACHE_DIR`, `ALPHAFOLD_CACHE_MODE`
2. **User config**: `~/.alphafold_sovereign/config.json`
3. **XDG config**: `~/.config/alphafold_sovereign/config.json`
4. **Module defaults**: Platform-specific paths

### Cache Modes

| Mode | Description |
|------|-------------|
| `sovereign` | Full read/write (primary device) |
| `readonly` | Read cache, no writes (secondary device) |
| `disabled` | Pure online, no cache (mobile/temporary) |

## API Reference

### Core Tools (7)

| Tool | Description |
|------|-------------|
| `get_structure` | Retrieve AlphaFold structure by UniProt ID |
| `search_structures` | Search local cache by pattern |
| `batch_structures` | Retrieve multiple structures (up to 50) |
| `get_features` | Compute structural features |
| `get_topology` | Compute persistent homology |
| `check_availability` | Check local/online availability |
| `get_cache_statistics` | Get cache statistics |

### Enrichment Tools (9)

| Tool | Description |
|------|-------------|
| `get_enriched_protein` | AlphaFold + UniProt + GO + disease |
| `batch_go_lookup` | Batch GO annotations (up to 500) |
| `search_by_go_term` | Find proteins by GO term |
| `get_go_hierarchy` | Navigate GO parent/child relationships |
| `export_protein_set` | Export to TSV/CSV for ML pipelines |
| `filter_by_organism` | Filter by organism |
| `get_protein_families` | Cluster proteins by similarity |
| `find_similar_proteins` | Find similar by sequence/structure |
| `get_domain_annotations` | Pfam/InterPro domain annotations |

### Advanced Analysis Tools (9)

| Tool | Description |
|------|-------------|
| `extract_pae_matrix` | Extract Predicted Aligned Error matrix |
| `detect_domains` | Detect domains from PAE clustering |
| `predict_disorder` | Predict intrinsically disordered regions |
| `get_plddt_profile` | Per-residue pLDDT confidence profile |
| `compute_information_content` | GO term information content |
| `compute_semantic_similarity` | GO semantic similarity (Resnik/Lin/Jiang) |
| `get_advanced_topology` | Full TDA: landscapes, images, Euler curves |
| `compare_protein_topology` | Wasserstein/bottleneck distance |
| `batch_protein_analysis` | Comprehensive batch analysis |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    AlphaFold Sovereign MCP                  │
├─────────────────────────────────────────────────────────────┤
│  1. Check Local Cache (dynamically indexed)                 │
│  2. Fallback: AlphaFold DB Online (no API key)              │
│  3. Auto-cache fetched structures                           │
│  4. Compute features/topology on-demand                     │
└─────────────────────────────────────────────────────────────┘
```

## Mathematical Foundation

Built on rigorous topological data analysis:

- **Persistent Homology**: Vietoris-Rips complex on C-alpha atoms
- **Betti Numbers**: β₀ (components), β₁ (loops), β₂ (voids)
- **Distances**: Wasserstein (optimal transport), Bottleneck (max matching)
- **GO Semantics**: Information content IC(t) = -log(P(t))

## Documentation

Full API documentation: [docs/index.html](docs/index.html)

## License

Proprietary - TOPOLOGICA LLC

Patent-pending drift tensor correction framework (R²=0.9992)

## Author

Santiago Maniches (ORCID: [0009-0005-6480-1987](https://orcid.org/0009-0005-6480-1987))

TOPOLOGICA LLC | [topologica.ai](https://topologica.ai)
