# `_archive/legacy/`

This directory contains the pre-decomposition monolith from the v0.x line of
AlphaFold Sovereign MCP.

## What's here

| File | Role (legacy) | Status |
|------|---------------|--------|
| `alphafold_mcp.py` (5,840 LOC) | Monolithic FastMCP server with 25 tools wired against AlphaFold DB + UniProt + GO + persistent-homology | superseded by `src/alphafold_sovereign/server/`, `tools/`, `clients/`, `domain/`, `storage/`, `compute/` (Wave 1) |
| `parsers.py` | PDB / mmCIF parsing → `AlphaFoldStructure`, `AlphaFoldMetadata`, `Atom`, `Residue` | will move to `src/alphafold_sovereign/domain/structure.py` (Wave 1 cont.) |
| `core.py` | `SovereignAlphaFoldConfig`, `SovereignAlphaFoldConnector`, `StructureIndex` | being decomposed into `clients/alphafold.py` + `storage/index.py` |
| `features.py` | `StructureFeatureExtractor`, `StructureFeatures` | moves to `compute/features.py` |
| `topology.py` | `VietorisRipsComplex`, `StructureTopologyAnalyzer`, `TopologicalFeatures` | moves to `compute/topology.py` (will swap homegrown filtration for `ripser.py`) |
| `fetcher.py` | `AlphaFoldFetcher` (urllib-based) | superseded by `clients/alphafold.py` (httpx-based) |
| `cache.py` | `SovereignStructureCache` | moves to `storage/cache.py` (gains Redis backend) |

## Why "_archive/"?

These files are **not part of the public API surface of v1.x**. They are kept
in-tree (rather than deleted outright) so that:

1. Bytes-identical reference outputs remain reproducible for regression
   testing during the decomposition.
2. Maintainers can compare the new module-tree implementations against the
   monolith for parity.
3. The patent-pending mathematics (drift tensor, topological fingerprinting,
   R² = 0.9992) remain on-record in the repo history at the original
   line-numbered locations cited in the patent filings.

## How they are kept out of the v1.x distribution

- `pyproject.toml` `[tool.hatch.build.targets.wheel]` only includes
  `src/alphafold_sovereign/`. Files under `_archive/` are **not packaged**.
- `[tool.coverage.run]` excludes `_archive/` from coverage measurement.
- `[tool.mypy]` and `[tool.ruff]` ignore `_archive/`.
- `[tool.bandit]` skips `_archive/`.

## Deprecation timeline

- **v1.1** (current): files archived, lazy re-exports from
  `alphafold_sovereign.__init__` keep `from alphafold_sovereign import PDBParser`
  working for one release.
- **v1.2**: re-exports removed; legacy imports raise `ImportError`.
- **v2.0**: directory deleted from the repo.

## Licensing

Files in this directory are released under the same Apache-2.0 terms as the
rest of the project. See `LICENSE` and `NOTICE` at the repo root.

— TOPOLOGICA LLC, 2026
