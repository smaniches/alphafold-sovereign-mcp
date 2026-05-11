# Changelog

All notable changes to AlphaFold Sovereign MCP are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added — Wave 1: Production hardening (continued)
- 100% line + branch coverage on every shipped module (clients, tools, domain,
  storage, server). Coverage gate raised from 30 → 100 in CI.
- `tests/conftest.py` with shared respx + retry-collapsing + rate-limit-off
  fixtures for hermetic, sub-second test runs.
- `tests/test_base_client_full.py` — full-coverage suite for the async base
  client: circuit breaker, retry, air-gap, JSON parsing errors, rate-limiter
  branch.
- `tests/test_client_*.py` — respx-based contract tests for every upstream
  client (AlphaFold, ChEMBL, ClinVar, DisGeNET, Ensembl, gnomAD, HPO, MONDO,
  Open Targets).
- `tests/test_tool_*.py` — mocked-client tests for the 4 flagship tool
  modules.
- `src/alphafold_sovereign/server/stdio.py` — stdio transport entry-point
  that aggregates each tool module's `FastMCP` instance.

### Fixed — Wave 1: Production hardening
- SQL injection (CWE-89) in `storage/knowledge_graph.py`: parameterised
  `LIMIT` clauses and added the `_ALLOWED_TABLES` allow-list guarding
  `export_to_dict(tables=...)`.
- `__init__.py` no longer eagerly imports legacy `parsers`/`core`/`features`/
  `topology` modules.  `import alphafold_sovereign` now succeeds without
  `numpy` (the CI Build-Distribution `--no-deps` check passes).
- 24 mypy strict errors across the client modules (proper return-type casts
  for `Any`-typed upstream responses; removal of stale `# type: ignore`
  comments).
- 5 bandit/CodeQL `B608` hardcoded-SQL flags eliminated.
- Dead `except RetryError` branch in `_base.py` removed (`reraise=True`
  means it was unreachable).

### Changed — Wave 1: Production hardening
- **Monolith archived.** `alphafold_mcp.py` (5,840 LOC) and its supporting
  modules (`parsers`, `core`, `features`, `topology`, `fetcher`, `cache`)
  moved to `_archive/legacy/` with a deprecation timeline (removed in v1.2,
  deleted in v2.0).  Not packaged in the wheel; excluded from lint, type,
  coverage, and security tooling.
- `pyproject.toml`: coverage `omit` reduced to `tests/*` and `_archive/*`;
  `fail_under = 100`.
- `__main__.py` entry-point now invokes `server.stdio.run_stdio()` rather
  than the archived monolith.

### Added — Wave 0: Legal, Governance & Professionalization
- Apache 2.0 license replacing proprietary license (full open-core model)
- `LICENSE-COMMERCIAL.md` describing Enterprise Edition contractual guarantees
- `PATENTS.md` with explicit Apache §3 grant and reservation of topology IP
- `TRADEMARKS.md` specifying permitted and prohibited use of project marks
- `NOTICE` with upstream data-source attributions (AlphaFold DB, UniProt, GO, PDB)
- `SECURITY.md` with coordinated-disclosure policy, 24-hour Sev-1 SLA, safe harbor
- `CODE_OF_CONDUCT.md` — Contributor Covenant 2.1 plus biosecurity enforcement clause
- `CONTRIBUTING.md` — DCO sign-off, 6-layer test pyramid, conventional commits, PR checklist
- `GOVERNANCE.md` — BDFL-with-council model, TSC, Biosecurity Advisory Board
- `SUPPORT.md` — community vs. enterprise SLAs, government/regulated-industry contact
- `PRIVACY.md` — data inventory, telemetry-off-by-default commitment, GDPR/HIPAA boundaries
- `CITATION.cff` — machine-readable citation metadata for academic use
- `ARCHITECTURE.md` — full system design, module map, data-flow diagrams
- `OVERVIEW.md` — 2-page executive summary for procurement teams
- `AUDIT.md` — pre-v1.0 security audit findings and remediation status
- `ROADMAP.md` — 9-wave execution plan from legal hardening to federated mesh
- `docs/THREAT_MODEL.md` — STRIDE + LINDDUN analysis of all attack surfaces
- `docs/INCIDENT_POLICY.md` — severity definitions, escalation, postmortem process
- `docs/POSTMORTEM_TEMPLATE.md` — blameless postmortem template
- `docs/MUTATION_SCORES.md` — per-module mutation test scores baseline
- `docs/COMPETITIVE_LANDSCAPE.md` — survey of 14 bio/structural MCP servers
- `scripts/replicate.sh` / `scripts/replicate.ps1` — cryptographic supply-chain verification
- `.github/` — CI workflows, CODEOWNERS, issue/PR templates, dependabot, FUNDING.yml
- SPDX `Apache-2.0` headers on all source files
- `_archive/` — dev artifacts moved from repo root (PHASE1_BUGFIX.py, qa_test_phase1.py)

### Added — Wave 1 Code: Disease Ontology Integration
- `src/alphafold_sovereign/clients/_base.py` — async httpx base client with
  tenacity retry, aiolimiter rate-limiting, circuit breaker, structured logging
- `src/alphafold_sovereign/clients/mondo.py` — MONDO disease ontology client
  (OLS4 + Monarch APIs); term lookup, ancestors, descendants, cross-references
- `src/alphafold_sovereign/clients/hpo.py` — Human Phenotype Ontology client;
  phenotype-disease links, HPO ancestor traversal, annotation-set queries
- `src/alphafold_sovereign/clients/opentargets.py` — Open Targets GraphQL client;
  disease-target evidence scores, association evidence types, disease profile
- `src/alphafold_sovereign/clients/clinvar.py` — ClinVar E-utilities client;
  variant interpretation, pathogenicity classifications, molecular consequences
- `src/alphafold_sovereign/clients/gnomad.py` — gnomAD GraphQL client;
  population allele frequencies per ancestry group, constraint metrics, pext
- `src/alphafold_sovereign/clients/disgenet.py` — DisGeNET REST client;
  gene-disease associations, GDA scores, evidence types
- `src/alphafold_sovereign/tools/disease.py` — 18 new MCP tools covering:
  - MONDO lookup and hierarchy traversal
  - HPO phenotype-disease associations
  - Common-disease protein target profiling (cardiovascular, oncology,
    neurodegeneration, diabetes, autoimmune, infectious, respiratory)
  - Disease-target evidence scoring (Open Targets)
  - Variant 3-D triage (HGVS → structure → AlphaMissense → ClinVar → gnomAD)
  - Phenotype-to-structure pipeline
  - Orphan disease structural atlas
  - Cross-disease structural comparison
- `src/alphafold_sovereign/domain/disease.py` — pure-Python domain types:
  `DiseaseRecord`, `PhenotypeAssociation`, `TargetEvidenceScore`, `VariantReport`

### Fixed
- `structlog` added to `pyproject.toml` dependencies (was imported but undeclared)
- Hardcoded Windows paths replaced with `platformdirs` in `core.py` and `alphafold_mcp.py`
- `tests/test_mcp.py` — removed hardcoded `C:\TOPOLOGICA_FRAMEWORK\` path and `exec(open(...))` anti-pattern
- README GitHub URL corrected to `smaniches/alphafold-sovereign-mcp`

### Changed
- `pyproject.toml` migrated to hatchling build backend; `uv.lock` added
- All `@mcp.tool()` decorators now include `annotations` with `readOnlyHint`,
  `idempotentHint`, `openWorldHint`, and `title`

---

## [1.0.0] — 2026-03-01 (Phase 1 baseline)

### Added
- 25 MCP tools: 7 core structure, 9 enrichment, 9 advanced analysis
- FastMCP server over stdio transport
- Hybrid local-first / AlphaFold DB fallback architecture
- Persistent homology via Vietoris-Rips (Betti numbers β₀, β₁, β₂)
- PAE matrix extraction and domain detection
- Intrinsic disorder prediction
- GO semantic similarity (Resnik, Lin, Jiang)
- UniProt metadata enrichment
- Dynamic structure index (O(1) lookup)
- Multi-device cache modes (sovereign / readonly / disabled)
- HTML5 API documentation

[Unreleased]: https://github.com/smaniches/alphafold-sovereign-mcp/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/smaniches/alphafold-sovereign-mcp/releases/tag/v1.0.0
