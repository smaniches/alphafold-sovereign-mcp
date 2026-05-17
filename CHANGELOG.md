# Changelog

All notable changes to this project are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/).

---

## [1.1.2] - 2026-05-17

A metadata-coherence patch on top of v1.1.1. The v1.1.1 published
artifacts (PyPI wheel, GitHub Release, Smithery / MCP-registry scrape)
still carried release-candidate-era manifest fields because the audit
landed in PR #17 that merged after the v1.1.1 tag was cut. v1.1.2
rebuilds the wheel and re-publishes so the public-facing metadata
matches the actual stable status. No runtime behaviour changes.

### Changed
- `pyproject.toml` trove classifier raised from
  `Development Status :: 4 - Beta` to
  `Development Status :: 5 - Production/Stable` so the PyPI surface
  matches the `"stable"` maturity declared in `server.json`,
  `.well-known/mcp.json`, and `smithery.yaml`.
- `server.json` `"maturity"` is `"stable"` and the registry install
  command drops the `--pre` flag (the wheel published for v1.1.1 still
  carried `pip install --pre alphafold-sovereign-mcp`).
- `.well-known/mcp.json` `"maturity"` is `"stable"`.
- `smithery.yaml` gains an explicit `maturity: stable` field (the
  registry manifest only carried it implicitly via the description
  before) and the description coverage figures are aligned with the
  rest of the manifests (677 tests, 100% line and branch).
- `docs/installation.md` no longer pitches the project as a release
  candidate, drops the `--pre` / `--prerelease=allow` install
  instructions, simplifies the `uvx` example to
  `uvx alphafold-sovereign-mcp`, and removes the obsolete
  `## Stable-only pip install` section.
- `AUDIT.md` and `INCIDENT_RESPONSE.md` re-anchor the still-true
  "as of <version>" claims (no external audit, no postmortems) to
  v1.1.2.
- Version strings raised to 1.1.2 across `pyproject.toml`,
  `src/alphafold_sovereign/__init__.py`, `server.json`,
  `.well-known/mcp.json`, `smithery.yaml`, `CITATION.cff`,
  `STATUS.md`, `README.md`, `docs/index.md`, `mkdocs.yml`,
  `docs/installation.md`, and `examples/README.md`.

## [1.1.1] - 2026-05-17

A maintenance release that hardens the 1.1.0 surface. It resolves every
outstanding automated code-review comment, verifies the codebase against
the live AlphaFold DB v6 response schema, and makes the structure tools
behave consistently when AlphaFold DB has no model for an accession.

### Fixed
- `EnsemblClient._first_uniprot` returned the string `"None"` for a list
  whose first element was not a string; it now type-checks before
  coercion.
- `AlphaFoldClient.get_pae` could return a non-dict (a JSON `null` body
  or a `null` first element of a single-element array); it now always
  returns a dict.
- `_validate_af_file_url` rejected an uppercase `HTTPS` scheme; the
  scheme comparison is now case-insensitive per RFC 3986.
- `ClinVarClient` exact-match ranking and RefSeq-accession detection
  were case-sensitive; both are now case-insensitive.
- `_fetch_af_plddt` raised `TypeError` when AlphaFold DB returned a
  `null` `uniprotSequence`; the value is now coerced to an empty string.
- Structure-intelligence AlphaFold fetchers are routed through
  `AlphaFoldClient` and adapt to the AlphaFold DB v6 schema: the removed
  `meanPlddt` field is replaced by `globalMetricValue`.
- The AlphaMissense UniProt accession is resolved from the Ensembl VEP
  `swissprot` consequence field, removing a redundant gene lookup.

### Changed
- The structure tools now return one consistent, human-readable
  response when AlphaFold DB has no model for an accession, including a
  `structure_available` flag. A stale coverage claim was removed.
- `score_binding_pocket_geometry` docstring and methodology string now
  describe the additive druggability index and the pLDDT threshold the
  code actually applies.
- Self-description accuracy pass: stale version strings and overstated
  docstrings were corrected across the repository.
- Test surface: 677 tests at 100% line and branch coverage, up from 623
  tests at 99%. The `noxfile.py` coverage gate is raised to 100% to
  match CI.

### Security
- The offline-mode air-gap pre-check resolved its target URL with a
  manual branch that could inspect a different host than the request
  reached for a protocol-relative or uppercase-scheme path. It now uses
  `httpx.URL.join`, the same RFC 3986 resolution httpx applies
  internally, so the pre-check inspects the host the request will
  actually contact.

## [1.1.0-rc1] — 2026-05-11

First release candidate that ships the refactored modular tree alongside
the full audit-readiness kit (`STATUS.md`, `LIMITATIONS.md`, `AUDIT.md`,
threat model, examples, mkdocs site).

### Added — release-ready surface
- `examples/` with three documented end-to-end transcripts:
  variant triage (BRCA1 c.5266dupC), target characterisation (EGFR),
  and drug-discovery (Imatinib → BCR-ABL).
- mkdocs-material documentation site deployed to GitHub Pages at
  `https://smaniches.github.io/alphafold-sovereign-mcp/`.
- `AUDIT.md`, `docs/threat-model.md` (STRIDE × MCP server surface),
  `INCIDENT_RESPONSE.md`.
- `smithery.yaml` and `server.json` so the server is discoverable in
  the Smithery registry and the official MCP server registry.
- `.well-known/security.txt` (RFC 9116) and `.well-known/mcp.json`.
- `noxfile.py` with `lint`, `type`, `test`, `cov`, `mutate`, `docs`,
  `build` sessions.
- `--self-test` and `--version` CLI flags. `alphafold-sovereign
  --self-test` boots the server in offline mode and verifies the
  deterministic logic of `generate_variant_clinical_report` on a known
  variant.
- Pre-registered 10-prompt benchmark under `benchmarks/` with
  SHA-256-committed prompt manifest and a deterministic re-run verifier.
- Mutation testing via `mutmut`; per-module mutation scores published
  to `docs/quality/mutation-scores.md`.
- Release workflow with SLSA L3 provenance attestations and
  `cosign`-signed artefacts.
- OpenSSF Scorecard workflow; badge in README.
- Zenodo DOI integration via GitHub releases; DOI added to
  `CITATION.cff`.

### Changed — language scrub for open release
- Removed marketing and overclaim language from the README, docstrings,
  and module headers. Specifically:
  - Dropped claims of "drift tensor R²=0.9992" — there is no benchmark
    in the repository that substantiates this number.
  - Dropped "patent-pending TOPOLOGICA methodology" framing from the
    structure-intelligence module. The patent status is described
    soberly in [`PATENTS.md`](PATENTS.md).
  - Dropped "Defense-grade sovereignty stack (FedRAMP-aligned, FIPS,
    SBOM, SLSA L3)" comparison line. None of those certifications has
    been audited; only an SBOM is actually emitted today.
  - Renamed `_wasserstein_distance` → `_fingerprint_distance` because
    the function computes L2 distance between length-normalised
    fingerprint vectors, not a Wasserstein distance on persistence
    diagrams. Updated callers, tests, and the tool's annotation title
    accordingly.
  - The ACMG/AMP output of the variant tools is now consistently
    described as a "draft surface of the upstream evidence", not a
    clinical interpretation.
  - The druggability tier is consistently described as a "heuristic".
- Removed the `LICENSE-COMMERCIAL.md` file and the "Enterprise
  Edition" wording everywhere. The project is licensed under
  Apache 2.0, full stop.
- Dropped enterprise / commercial contact email addresses from the
  docs. Contact channels are: GitHub Discussions for questions,
  GitHub Issues for bugs, GitHub Security Advisories for
  vulnerabilities.

### Changed — test surface
- 623 unit tests, hermetic (respx-mocked upstreams), runs in under 15
  seconds on a laptop.
- Coverage on the shipped surface: **99% line + branch** (99.52%
  measured), with 19 of 20 modules at 100%. The remaining gap is 1
  statement and 2 partial branches in
  `tools/knowledge_graph_tools.py` in a defensive sync-fallback path.
- CI matrix: Python 3.10, 3.11, 3.12, 3.13 × Ubuntu, macOS.
- CodeQL `security-extended` runs on every push to a public repo
  (free tier of GitHub-hosted runners).

### Fixed
- SQL injection (CWE-89) in `storage/knowledge_graph.py`: parameterised
  `LIMIT` clauses and added the `_ALLOWED_TABLES` allow-list guarding
  `export_to_dict(tables=...)`.
- `__init__.py` no longer eagerly imports legacy `parsers`/`core`/
  `features`/`topology` modules. `import alphafold_sovereign` now
  succeeds without `numpy`, so the `--no-deps` wheel-import check in
  CI passes.
- 24 mypy strict errors across the client modules (proper return-type
  casts for `Any`-typed upstream responses; removal of stale `#
  type: ignore` comments).
- 5 bandit / CodeQL `B608` hardcoded-SQL flags eliminated.
- `_traverse_network` in `tools/knowledge_graph_tools.py` was awaiting
  a sync method (`kg._fetchall`); calling it synchronously now.

### Removed
- `_archive/legacy/` — the original monolithic `alphafold_mcp.py`
  (5,840 LOC) and its supporting modules moved here. Not packaged in
  the wheel; excluded from lint, type, coverage, and security tooling.
  Tracked for deletion in v2.0.
- `tests/verify_config.py` — a one-off helper with a hardcoded Windows
  path; not a test.

### Known limitations (see `LIMITATIONS.md`)
- ACMG criterion mapping has not been reviewed by an independent
  clinical geneticist (L1).
- Druggability tier thresholds are unvalidated heuristics (L2).
- Upstream API schemas are not pinned (L3).
- No production deployment experience yet (L4).
- macOS Python 3.11 test flake (L5).
- Single-maintainer bus factor (L6).
- No real-world correctness telemetry (L7).

---

## [Unreleased]

---

## [1.0.0] — 2026-03-01 (Phase 1 baseline)

### Added
- 25 MCP tools across structure, enrichment, and analysis modules.
- FastMCP server over stdio transport.
- Local-first AlphaFold structure cache with AlphaFold DB fallback.
- Persistent homology via Vietoris-Rips (Betti numbers β₀, β₁, β₂).
- PAE matrix extraction and domain detection.
- Intrinsic-disorder prediction.
- GO semantic similarity (Resnik, Lin, Jiang).
- UniProt metadata enrichment.
- Multi-mode local cache (`sovereign` / `readonly` / `disabled`).
- HTML5 API documentation.

[Unreleased]: https://github.com/smaniches/alphafold-sovereign-mcp/compare/v1.1.2...HEAD
[1.1.2]: https://github.com/smaniches/alphafold-sovereign-mcp/compare/v1.1.1...v1.1.2
[1.1.1]: https://github.com/smaniches/alphafold-sovereign-mcp/compare/v1.1.0-rc1...v1.1.1
[1.1.0-rc1]: https://github.com/smaniches/alphafold-sovereign-mcp/releases/tag/v1.1.0-rc1
[1.0.0]: https://github.com/smaniches/alphafold-sovereign-mcp/releases/tag/v1.0.0
