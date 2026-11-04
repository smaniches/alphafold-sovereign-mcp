# `_archive/legacy/`

This directory preserves the pre-decomposition code from the v0.x line of
AlphaFold Sovereign MCP. It is a historical reference, not the current
implementation or a shipped package component. The table below reflects
migration notes written during decomposition, not current release status.

## What's here

| File | Role (legacy) | Historical migration note |
|------|---------------|--------|
| `alphafold_mcp.py` (5,840 LOC) | Monolithic FastMCP server with 25 tools wired against AlphaFold DB + UniProt + GO + persistent-homology | superseded by `src/alphafold_sovereign/server/`, `tools/`, `clients/`, `domain/`, `storage/`, `compute/` (Wave 1) |
| `parsers.py` | PDB / mmCIF parsing → `AlphaFoldStructure`, `AlphaFoldMetadata`, `Atom`, `Residue` | will move to `src/alphafold_sovereign/domain/structure.py` (Wave 1 cont.) |
| `core.py` | `SovereignAlphaFoldConfig`, `SovereignAlphaFoldConnector`, `StructureIndex` | being decomposed into `clients/alphafold.py` + `storage/index.py` |
| `features.py` | `StructureFeatureExtractor`, `StructureFeatures` | moves to `compute/features.py` |
| `topology.py` | `VietorisRipsComplex`, `StructureTopologyAnalyzer`, `TopologicalFeatures` | moves to `compute/topology.py` (will swap homegrown filtration for `ripser.py`) |
| `fetcher.py` | `AlphaFoldFetcher` (urllib-based) | superseded by `clients/alphafold.py` (httpx-based) |
| `cache.py` | `SovereignStructureCache` | moves to `storage/cache.py` (gains Redis backend) |

## Why keep the archive?

The old implementation is retained for historical comparison and targeted
regression investigations. The archive alone does not establish equivalence
with the current implementation; that requires separate tests.

Archived source code and comments do not substantiate current mathematical
functionality, numerical performance, or patent application status. The
changelog records the withdrawal of an unsupported performance claim.
Historical metadata does not impose licensing restrictions beyond those
in the applicable license; see `LICENSE` and `PATENTS.md` in the repo root.

## Package and analysis exclusions

- `pyproject.toml` packages only `src/alphafold_sovereign/` in wheels,
  and its source-distribution manifest does not include `_archive/`.
- `[tool.coverage.run]` excludes `_archive/` from coverage measurement.
- `[tool.mypy]` and `[tool.ruff]` ignore `_archive/`.
- `[tool.bandit]` skips `_archive/`.

## Version context

The archive dates from the v1.x decomposition period. Earlier references to
v1.1 as the "current" release and to future v1.2/v2.0 removals were period
notes, not current release information or continuing commitments. Consult
the root README, release metadata, and CHANGELOG for the supported version.

## Licensing

Files in this directory are released under the same Apache-2.0 terms as the
rest of the project. See `LICENSE` and `NOTICE` at the repo root.

— TOPOLOGICA LLC, 2026
