# Changelog

All notable changes to this project are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/).

---

## [1.1.5] - 2026-05-17

A dependency-hygiene patch. Closes nine of the ten Dependabot PRs
that landed within hours of `.github/dependabot.yml` going live in
v1.1.3, by consolidating their lockfile / workflow updates into a
single coordinated release. No code, runtime-behaviour, or scientific
output changes — same `src/` tree as v1.1.4, 677/677 tests still pass.

### Changed (Python lockfile bumps — within existing `>=` constraints)

`uv lock --upgrade` ran cleanly and produced the following moves, all
verified by the full test suite passing:

- `black` 26.3.1 → 26.5.0 (dev formatter; Dependabot PR #29)
- `fastmcp` 3.2.4 → 3.3.1 (**runtime**; Dependabot PR #26)
- `hypothesis` 6.152.5 → 6.152.7 (dev test framework; Dependabot PR #25)
- `mypy` 2.0.0 → 2.1.0 (dev type-checker; Dependabot PR #27)
- `pymdown-extensions` 10.21.2 → 10.21.3 (docs build; Dependabot PR #28)

Plus the following transitives also advanced inside the lockfile but
were not flagged by Dependabot: `cachetools` 7.1.1→7.1.2,
`click` 8.3.3→8.4.0, `cyclopts` 4.11.2→4.13.0,
`fonttools` 4.62.1→4.63.0, `idna` 3.14→3.15,
`jaraco-functools` 4.4.0→4.5.0, `numpy` 2.4.4→2.4.5,
`python-discovery` 1.3.0→1.3.1, `python-multipart` 0.0.28→0.0.29,
`requests` 2.33.1→2.34.2, `ruff` 0.15.12→0.15.13,
`sse-starlette` 3.4.2→3.4.4, `uvicorn` 0.46.0→0.47.0,
`virtualenv` 21.3.1→21.3.3.

### Changed (GitHub Actions bumps)

- `astral-sh/setup-uv` v4 → v7 across `ci.yml`, `docs.yml`,
  `release.yml` (Dependabot PR #24).
- `actions/upload-artifact` v4 → v7 across `ci.yml`, `scorecard.yml`,
  `release.yml` (Dependabot PR #20).
- `github/codeql-action/*` v3 → v4 in `ci.yml` (init + analyze) and
  `scorecard.yml` (upload-sarif) (Dependabot PR #22).
- `codecov/codecov-action` v4 → v6 in `ci.yml` (Dependabot PR #23).
- `ossf/scorecard-action` v2.4.0 → v2.4.3 in `scorecard.yml`
  (Dependabot PR #21).

### Added — documentation

- CHANGELOG `[1.1.5]` section (this entry) enumerating which
  Dependabot PRs were absorbed and which was deferred and why.

### Verified

- `uv lock` clean (no unexpected transitive drift beyond what was
  triggered by the named bumps)
- `pytest` 677/677 passing
- `ruff check` + `ruff format --check` clean on CI-scoped paths
- `mypy --strict` clean on the constrained mypy 2.0.x
- All six authoritative version sources read `1.1.5`; concept DOI
  unchanged (`10.5281/zenodo.20134773`).

### Closes Dependabot PRs

All ten open Dependabot PRs (#20–#29) superseded by this
consolidated release. Their lockfile / workflow updates are folded
into this commit and verified together by a single CI run, rather
than landing as ten separate merges.

---

## [1.1.4] - 2026-05-17

An accuracy patch. Closes one bibliographic error, two stale-claim
errors, and seven smaller drifts found during a self-audit of every
"claim" file in the repo. No code, runtime, or dependency changes.

### Fixed
- **Zenodo concept DOI**. Six metadata fields cited
  `10.5281/zenodo.20134774`, which is the v1.1.0-rc1 *version-specific*
  DOI rather than the project's concept DOI. The actual concept DOI
  (the one that always redirects to the latest archived version) is
  `10.5281/zenodo.20134773`. Citations of the previous value were
  silently pinned to v1.1.0-rc1; the correct concept DOI now resolves
  to v1.1.3 today and will resolve to v1.1.4 once this release
  archives. The `CITATION.cff` header comment that mislabelled the
  rc1 DOI as "the concept DOI minted on the v1.1.0 release" is also
  rewritten to describe Zenodo's concept-vs-version model accurately.
  Files corrected: `CITATION.cff`, `README.md` (DOI badge + bibtex),
  `STATUS.md`, `server.json`, `.well-known/mcp.json`.
- **`README.md` `uvx` install example** still showed
  `uvx --from alphafold-sovereign-mcp alphafold-sovereign-mcp`, the
  pre-#17 form. PR #17 simplified this to `uvx alphafold-sovereign-mcp`
  in `docs/installation.md` per a Gemini suggestion but missed the
  README copy. Now consistent.
- **`STATUS.md` Zenodo claim**. The earlier wording
  *"minted automatically on every GitHub Release"* was historically
  inaccurate: the GitHub-Zenodo webhook was installed only for
  v1.1.0-rc1, broke between then and v1.1.3, and was reinstalled today
  before v1.1.3 published. Rewritten to describe what is now true and
  verifiable: the concept DOI redirects to the latest archived
  version, and the integration mints a new version-specific DOI on
  each GitHub Release.
- **`STATUS.md` module count**. The "20 modules" line was
  approximate; the actual surface is 5 subpackages with 18 substantive
  `.py` modules (10 client modules, 1 domain module, 4 tool modules,
  1 storage module, 2 server modules). Reworded to match.
- **`AUDIT.md` audit log**. The previous table listed only the PR #2
  Gemini review, undersurfacing the cumulative engineering review
  history. Expanded to enumerate the seven PRs reviewed by
  `gemini-code-assist[bot]` between 2026-05-11 and 2026-05-17 (PRs
  #2, #6, #16, #17, #18, #19 + the consolidation PR #15) and the
  commits that resolved each batch of findings. Also clarified the
  threat-model row (the maturity expectation for an external STRIDE
  audit was unclear; now stated as "defer until external security
  audit"). This brings AUDIT.md into honest agreement with the
  actual review trail visible in the PR archive.
- **`LIMITATIONS.md` self-references**. The "as of v1.1.0" anchor
  in the preamble was three releases stale (now "as of v1.1.4"). The
  "~3,000 statements" approximation in L6 is replaced by the verified
  exact count from `pytest --cov` output (2,868 statements).
- **Stale "Last updated" dates** in `AUDIT.md` (2026-05-11),
  `STATUS.md` (2026-05-16), and `LIMITATIONS.md` (2026-05-11) are all
  refreshed to today, 2026-05-17.
- **`AUDIT.md` as-of line** and `INCIDENT_RESPONSE.md` as-of line
  re-anchored from v1.1.3 to v1.1.4.

### Verified correct (no change)
For traceability, the following claims were verified against the
codebase during this audit and do not need correction:

- 677 tests (`pytest --collect-only` returns 677)
- 100% line and branch coverage (2868/2868 statements, 776/776
  branches per `pytest --cov` on this commit)
- 29 MCP tools (12 disease + 6 precision medicine + 6 structure
  intelligence + 5 knowledge graph; confirmed via `grep -c "^@mcp.tool"`
  per module)
- 14 data sources (AlphaFold DB + 13 others, per the README table)
- Version 1.1.4 consistent across `pyproject.toml`,
  `src/alphafold_sovereign/__init__.py`, `server.json`,
  `.well-known/mcp.json`, `smithery.yaml`, `CITATION.cff`

---

## [1.1.3] - 2026-05-17

A dependency-trimming patch that reduces the runtime surface and closes
the open Dependabot alert.

### Removed
- Seven pre-positioned runtime dependencies that no code path imported.
  Each was annotated in `pyproject.toml` with a comment describing
  future work (`# JWT — OAuth 2.1 bearer tokens`,
  `# Cryptography (signing, FIPS)`,
  `# Optional: OpenTelemetry (graceful no-op if not installed)`,
  `# Optional: Prometheus metrics`) that was never written. Removed:
  `mcp` (still pulled in transitively via `fastmcp`),
  `pydantic-settings`,
  `cryptography`,
  `python-jose[cryptography]`,
  `opentelemetry-sdk`,
  `opentelemetry-exporter-otlp-proto-grpc`,
  `prometheus-client`.
  The HTTP transport, observability layer, and bearer-token handling
  will declare their own dependencies at the time they actually ship,
  when the choice can be made against real requirements.
- The dead `jose.*` entry from the `[[tool.mypy.overrides]]` block that
  matched the removed `python-jose` package.

### Security
- Resolves the GHSA-w8m6-9963-pmpv "Minerva timing attack on P-256 in
  python-ecdsa" Dependabot alert. `ecdsa` was a transitive of
  `python-jose`; removing the latter drops the former from the install
  tree.

### Changed
- `uv.lock` regenerated. Thirteen packages drop out of the install tree:
  `ecdsa`, `python-jose`, `rsa`, `pyasn1`, `prometheus-client`, `grpcio`,
  `protobuf`, `googleapis-common-protos`,
  `opentelemetry-exporter-otlp-proto-common`,
  `opentelemetry-exporter-otlp-proto-grpc`, `opentelemetry-proto`,
  `opentelemetry-sdk`, `opentelemetry-semantic-conventions`.
  `pydantic-settings` and `opentelemetry-api` remain in the lockfile as
  legitimate transitives of `mcp` and `openapi-pydantic` respectively.
- New `.github/dependabot.yml` adds weekly automated dependency-update
  PRs for both the Python ecosystem and GitHub Actions, closing the
  OpenSSF Scorecard `Dependency-Update-Tool` finding.
- `AUDIT.md` and `INCIDENT_RESPONSE.md` re-anchor the still-true
  "as of <version>" claims to v1.1.3.

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

[Unreleased]: https://github.com/smaniches/alphafold-sovereign-mcp/compare/v1.1.5...HEAD
[1.1.5]: https://github.com/smaniches/alphafold-sovereign-mcp/compare/v1.1.4...v1.1.5
[1.1.4]: https://github.com/smaniches/alphafold-sovereign-mcp/compare/v1.1.3...v1.1.4
[1.1.3]: https://github.com/smaniches/alphafold-sovereign-mcp/compare/v1.1.2...v1.1.3
[1.1.2]: https://github.com/smaniches/alphafold-sovereign-mcp/compare/v1.1.1...v1.1.2
[1.1.1]: https://github.com/smaniches/alphafold-sovereign-mcp/compare/v1.1.0-rc1...v1.1.1
[1.1.0-rc1]: https://github.com/smaniches/alphafold-sovereign-mcp/releases/tag/v1.1.0-rc1
[1.0.0]: https://github.com/smaniches/alphafold-sovereign-mcp/releases/tag/v1.0.0
