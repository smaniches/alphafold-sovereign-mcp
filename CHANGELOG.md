# Changelog

All notable changes to this project are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/).

---

## [1.3.0](https://github.com/smaniches/alphafold-sovereign-mcp/compare/v1.2.3...v1.3.0) (2026-06-23)

> **Behavior change (error reporting):** failed disease-tool calls now return an MCP error result (`isError=true`) instead of a *successful* result whose text content was an error-shaped JSON string (`{"status": "error", ...}`). Clients that parsed that JSON to detect failures should switch to checking `isError` on the result. Successful results and not-found / no-results negative results are unchanged. See [#133](https://github.com/smaniches/alphafold-sovereign-mcp/pull/133); mirrors uniprot-mcp [#88](https://github.com/smaniches/uniprot-mcp/pull/88).


### Features

* **disease:** raise ToolError on tool failures so isError is set (mirrors [#88](https://github.com/smaniches/alphafold-sovereign-mcp/issues/88)) ([66b9379](https://github.com/smaniches/alphafold-sovereign-mcp/commit/66b93798e7cf121435fa20c23ad59ac6614bb724))


### Bug Fixes

* **storage:** set SQLite busy_timeout in _open_db ([#128](https://github.com/smaniches/alphafold-sovereign-mcp/issues/128)) ([4a1c3d1](https://github.com/smaniches/alphafold-sovereign-mcp/commit/4a1c3d1749a47c939165a39a0f1a43323f79c291))


### Documentation

* add limitation issue template ([#129](https://github.com/smaniches/alphafold-sovereign-mcp/issues/129)) ([9e58a33](https://github.com/smaniches/alphafold-sovereign-mcp/commit/9e58a3343396f5425b528ff52fb3f41618bccfd3))


### CI/CD

* scope workflow token permissions to job level (OpenSSF Scorecard) ([#132](https://github.com/smaniches/alphafold-sovereign-mcp/issues/132)) ([b8fc96e](https://github.com/smaniches/alphafold-sovereign-mcp/commit/b8fc96e4c27090e5b1d4fc142899a73d5aa78df6))
* stabilise the macOS/Python 3.11 test flake (scoped retry) ([#131](https://github.com/smaniches/alphafold-sovereign-mcp/issues/131)) ([40bd931](https://github.com/smaniches/alphafold-sovereign-mcp/commit/40bd931410e9c0a963b78b59a51ad260de56c7b6))

## [1.2.3](https://github.com/smaniches/alphafold-sovereign-mcp/compare/v1.2.2...v1.2.3) (2026-06-22)


### Dependencies

* **security:** bump msgpack 1.1.2 -> 1.2.1, addressing a high-severity use-after-free / out-of-bounds read on `Unpacker` reuse after a caught error ([#127](https://github.com/smaniches/alphafold-sovereign-mcp/issues/127))
* **security:** bump pydantic-settings 2.14.1 -> 2.14.2, addressing a path-traversal / link-following advisory in `NestedSecretsSettingsSource` ([#126](https://github.com/smaniches/alphafold-sovereign-mcp/issues/126))
* bump the production-minor-patch group with 3 updates ([#125](https://github.com/smaniches/alphafold-sovereign-mcp/issues/125))
* bump actions/checkout 6 -> 7 ([#124](https://github.com/smaniches/alphafold-sovereign-mcp/issues/124))


### Bug Fixes

* restore the verbatim Apache-2.0 Section 9 text in `LICENSE` so the license is correctly detected ([#123](https://github.com/smaniches/alphafold-sovereign-mcp/issues/123))

### Documentation

* add README motivation lead and align supply-chain, offline, and pLDDT claims with the code ([#116](https://github.com/smaniches/alphafold-sovereign-mcp/issues/116)) ([5bd6b7f](https://github.com/smaniches/alphafold-sovereign-mcp/commit/5bd6b7f79762651a1fffadf349be3d17d4d0f0cc))

## [1.2.2](https://github.com/smaniches/alphafold-sovereign-mcp/compare/v1.2.1...v1.2.2) (2026-06-16)


### Bug Fixes

* align governance, supply-chain, and science claims with the implementation ([#111](https://github.com/smaniches/alphafold-sovereign-mcp/issues/111)) ([6c170db](https://github.com/smaniches/alphafold-sovereign-mcp/commit/6c170dbcb53199ce933bf846734a852f18b72227))


### Documentation

* align CONTRIBUTING Python prerequisite with the 3.10+ support matrix ([#112](https://github.com/smaniches/alphafold-sovereign-mcp/issues/112)) ([86db87f](https://github.com/smaniches/alphafold-sovereign-mcp/commit/86db87f668c222c330d3572d2ed50d0ae7de5a65))
* bump human-readable version stamps to 1.2.2 ([#114](https://github.com/smaniches/alphafold-sovereign-mcp/issues/114)) ([245fb2e](https://github.com/smaniches/alphafold-sovereign-mcp/commit/245fb2e9f227fba290d057f16e7ba25d7eb8bfc9))
* log the v1.2.1 hardening review in AUDIT.md; correct CITATION release date ([#109](https://github.com/smaniches/alphafold-sovereign-mcp/issues/109)) ([4b0ff1d](https://github.com/smaniches/alphafold-sovereign-mcp/commit/4b0ff1dde31b119301a44a65c272ddcb534222a5))

## [1.2.1](https://github.com/smaniches/alphafold-sovereign-mcp/compare/v1.2.0...v1.2.1) (2026-06-16)


### Bug Fixes

* align user-facing capability claims with the implementation; ship py.typed ([#107](https://github.com/smaniches/alphafold-sovereign-mcp/issues/107)) ([590583e](https://github.com/smaniches/alphafold-sovereign-mcp/commit/590583e779a29215df39fdc5f3c47ec9cc38468e))
* **deps:** bump starlette, python-multipart, cryptography (clears 9 Dependabot alerts) ([#108](https://github.com/smaniches/alphafold-sovereign-mcp/issues/108)) ([a9a658d](https://github.com/smaniches/alphafold-sovereign-mcp/commit/a9a658d05c13cb3f960ef41d564654441f3b90a2))


### Testing

* add metadata contract tests and Zenodo deposition metadata ([#101](https://github.com/smaniches/alphafold-sovereign-mcp/issues/101)) ([70db7c0](https://github.com/smaniches/alphafold-sovereign-mcp/commit/70db7c08bf03699a302e442c43688a75f13dfef3))


### Refactoring

* type-check the full source tree under mypy --strict ([#102](https://github.com/smaniches/alphafold-sovereign-mcp/issues/102)) ([772dd3d](https://github.com/smaniches/alphafold-sovereign-mcp/commit/772dd3dab1c5db0801e30d16af975e57253c0ee2))

## [Unreleased]

## [1.2.0] - 2026-06-08

The "live-API validation" milestone. Every tool was exercised end-to-end
against the real upstream APIs (Open Targets, ChEMBL, UniProt, Ensembl,
ClinVar, gnomAD, HPO, AlphaFold DB); four that were non-operative were fixed,
the local knowledge graph now seeds itself, and the documentation/examples
were brought in line with what the code actually returns.

### Added
- **The local knowledge graph seeds itself on first use.** A curated seed
  dataset (the BCR-ABL/CML and BRCA1/breast-cancer entities used in the worked
  examples) is loaded when the graph is empty, so `query_protein_database`,
  `query_variant_database`, `export_research_dataset`, and
  `find_drug_gene_network` return representative results out of the box. Set
  `AFSMCP_DISABLE_KG_SEED=1` to keep the graph empty. New relationship-write
  methods (`store_protein_drug`, `store_protein_disease`, `store_variant_disease`)
  back the seed.
- **EFO disease resolution + supporting client methods.** `DiseaseRecord.efo_ids`
  (MONDO→EFO cross-reference), `OpenTargetsClient.resolve_disease_efo` (name→EFO
  via search), `ChEMBLClient.molecule_names` (bulk ID→name, chunked), and
  `EnsemblClient.ncbi_gene_id` (HGNC symbol→Entrez).

### Fixed
- **`map_disease_drug_landscape` returned no drugs or targets for any disease.**
  It passed a MONDO ID into ChEMBL's EFO-keyed `drug_indication` filter and into
  Open Targets. Now resolves MONDO→EFO (via the term's xref, falling back to an
  Open Targets name search for terms without one — e.g. "breast cancer"), backfills
  drug names, and retries Open Targets via the EFO ID. CML now returns 9 approved
  drugs (imatinib, dasatinib, nilotinib, ponatinib, bosutinib, asciminib, …) and
  ABL1/BCR/KIT targets.
- **Three phenotype tools returned HTTP 404.** The HPO REST API moved from
  `hpo.jax.org` to `ontology.jax.org`; the client was repointed and its parsing
  rewritten. `lookup_phenotype`, `get_gene_phenotype_profile`, and
  `phenotype_to_structures` are operative again.
- **`find_evolutionary_structural_shifts` found no orthologs.** Ensembl's
  homology-by-ID endpoint now requires the species in the path
  (`/homology/id/{species}/{id}`).
- **`triage_variant_3d` rejected standard HGVS.** The parser now accepts the
  canonical ClinVar form (`NM_…(GENE):c.…`) and no longer mis-reads genomic
  accessions or chromosome names as gene symbols.
- **`synthesize_protein_dossier` provenance** stamped the wrong field and omitted
  several sources; scientific-accuracy and source-honesty defects (licenses,
  ACMG PS1→PP5, MONDO/version claims) were corrected across the docs. It now also
  stamps `alphafold_db` (queried for pLDDT) in both the provenance footer and the
  `data_sources` map.
- **Seed scientific accuracy:** the curated KG seed linked olaparib as a
  drug-*target* of BRCA1; olaparib targets **PARP1** (synthetic lethality in
  BRCA-mutant tumours), so the edge was corrected to PARP1 (P09874).
- **KG read-only contract:** the curated seed is now loaded once at server
  startup, not lazily on first tool access, so the `readOnlyHint: true`
  query/export tools never write. The emptiness check counts every entity table
  (not just `proteins`), so an existing variants-only DB is never overwritten.
- **Provenance version stamps refreshed to the live releases:** ChEMBL
  `v36`→`v37`, Open Targets `24.06`→`26.03`.
- **Relationship upserts** (`store_protein_disease` / `store_protein_drug` /
  `store_variant_disease`) now refresh all mutable evidence columns on conflict.

### Changed
- **All three worked examples re-captured from live runs** and relabelled
  "Captured live": 01 (BRCA1 c.181T>G → ClinVar Pathogenic / ACMG PP3+PP5),
  02 (EGFR druggability → HOT), 03 (CML drug landscape), each with the real
  output and transparent notes on the heuristic's limitations.
- **CI:** Dependabot grouping + low-risk auto-merge; `fetch-metadata` v3.1.0.

### Security
- **Forces patched `pyjwt` 2.13.0 into the runtime tree.** `pyjwt` enters the
  install tree transitively through `fastmcp` → `mcp` 1.27.1, which pins
  `pyjwt[crypto]>=2.10.1`. That loose floor resolved to 2.12.1, which carries
  four advisories — PYSEC-2026-175, -177, -178, -179 — all fixed in 2.13.0
  (confirmed by `pip-audit`). A direct `pyjwt[crypto]>=2.13.0` floor was added
  to `[project.dependencies]`. Unlike a uv-only `[tool.uv]` constraint, a
  `[project.dependencies]` floor lands in the published wheel's `Requires-Dist`,
  so every installer (not just `uv`) is forced onto the patched release. No code
  path imports `jwt`; this is a security version floor on a package already in
  the tree, not a re-introduction of the direct functional dependency removed in
  v1.1.3. `uv.lock` regenerated: `pyjwt` 2.12.1 → 2.13.0, the only package that
  changed.

## [1.1.10] - 2026-06-05

Two reviewer-flagged residuals from the v1.1.9 audit, plus the
release-workflow fix that was merged to `main` after the v1.1.9 tag but never
shipped in a tagged release. The tool surface and tool count (29) are
unchanged; the only behaviour change is the canonical form of the
`disease_mondo_id` field returned by the Open Targets disease/target tools.

### Fixed
- **`server.json` `tags` still advertised the five non-integrated sources.**
  v1.1.9 corrected the data-source *count* (14 → 9) in the description and the
  README/manifest prose, but the `server.json` `tags` array still listed
  `uniprot`, `rcsb-pdb`, `interpro`, `gene-ontology`, and
  `human-protein-atlas` — none of which has a client. The nine integrated
  upstreams are AlphaFold DB, Open Targets, ChEMBL, Ensembl, ClinVar, gnomAD,
  MONDO, HPO, and DisGeNET. The five stale tags were removed so the manifest
  matches the corrected count.
- **Open Targets disease ids are now returned as canonical colon-form CURIEs.**
  v1.1.9 normalised disease ids on the *input* path (so `get_disease_targets`
  returns results); the *output* `disease_mondo_id` still echoed the
  underscore form the live API returns (e.g. `MONDO_0007254`) or the raw
  caller input. A new idempotent `_to_curie` helper canonicalises the returned
  id to colon form (`MONDO:0007254`, `EFO:0000305`, …) at both construction
  sites (`associated_targets` and `_row_to_score`). It is prefix-agnostic, so
  EFO / Orphanet ids keep their own prefix rather than being forced to MONDO.
  Seven regression tests were added — the live underscore form was previously
  exercised only by colon-form mocks, so the gap shipped unnoticed.

### Changed
- **Release workflow.** v1.1.10 is the first tagged release built from the
  fully fixed `release.yml`: it ships the `cosign` v3 fix (one self-contained
  `.sigstore` bundle; the ignored legacy `--output-signature` /
  `--output-certificate` flags are gone) that was merged to `main` after the
  v1.1.9 tag.
- **Counts.** 689 → **696** tests; 2,949 → **2,957** statements (790 → 794
  branches); 100% line + branch coverage unchanged.

## [1.1.9] - 2026-06-04

Audit-and-polish work accumulated since v1.1.8, plus one functional fix:
`get_disease_targets` now returns results (it previously returned an empty
list for every disease). The remaining changes — residual version drift, a
stale statement count, a lint-scope gap that let one style violation ship,
a coverage-gate inconsistency, a **data-source overclaim** (docs advertised
14 sources; only 9 are actually queried), an MCP handshake that reported
the framework version instead of the product version, and an
`ARCHITECTURE.md` / documentation-site accuracy pass — do not change
runtime behaviour. The tool surface and tool count (29) are unchanged.

### Fixed
- **`get_disease_targets` returned no targets for any disease.** The tool
  passed colon-form CURIEs (e.g. `MONDO:0009061`) to Open Targets, which
  keys disease records on the underscore form, so every query matched no
  disease and returned an empty list under a `success` status. The
  normalisation now lives in `OpenTargetsClient.associated_targets`, so all
  callers are robust. Verified against the live API: cystic fibrosis now
  returns CFTR (UniProt P13569) as its top target. (#52)
- **Residual version drift.** `examples/README.md` still printed
  `--version → 1.1.7`; updated to `1.1.8` to match every other manifest
  and document (the v1.1.8 drift sweep missed this one file).
- **Stale statement count.** `LIMITATIONS.md` L6 carried the v1.1.4
  figure (`2,868` statements) under an "as of v1.1.8" label. The
  verified `pytest --cov` count is `2,949` statements / 790 branches
  (this includes the one-line `__version__` import added below;
  identical across Python 3.10–3.13, since no source uses
  version-conditional branches).
- **Unlinted entry point.** `src/alphafold_sovereign/__main__.py`
  contained an `E501` (over-length `--self-test` help string) that
  shipped because neither the CI `ruff` step nor `noxfile`'s
  `SRC_DIRS_LINT` covered the file. The string is wrapped; the file is
  now linted.
- **Data-source overclaim corrected (14 → 9).** The README, registry
  manifests (`server.json`, `.well-known/mcp.json`, `smithery.yaml`),
  the PyPI / `pyproject` description, `CITATION.cff`, `STATUS.md`,
  `LIMITATIONS.md`, `docs/index.md`, and the package docstrings
  advertised "AlphaFold DB + 13 other data sources." Only **9**
  upstreams are actually queried (AlphaFold DB, Open Targets, ChEMBL,
  Ensembl, ClinVar, gnomAD, MONDO, HPO, DisGeNET). RCSB PDB, Gene
  Ontology, and InterPro are never contacted; UniProt is used only as an
  identifier namespace; Human Protein Atlas is at most a transitive Open
  Targets score. The five were removed from the source lists, the count
  corrected to 9, and an explicit "not integrated in this release" note
  added to the README data-sources table.
- **MCP server version.** The `initialize` handshake reported FastMCP's
  own version (`3.3.1`) instead of the product version, because
  `server/app.py` constructed `FastMCP("alphafold-sovereign")` with no
  `version=`. It now passes `version=__version__`, so a connecting
  client sees `1.1.8`.

### Changed
- **CI lint scope now matches the package.** The `lint` job runs
  `ruff check src/` (was four hand-listed subpackages), so `server/`
  and `__main__.py` can no longer drift out of coverage.
- **CI type-check scope aligned with `noxfile`.** The `typecheck` job
  now also covers `server/` and `__main__.py`; the `noxfile` `type`
  session already did, so CI and local `nox` results agree as
  `noxfile.py` documents.
- **`noxfile` lint scope** now includes `__main__.py`, matching its
  `type` session.
- **Coverage gate.** `[tool.coverage.report] fail_under` raised from
  `99` to `100`, matching the threshold CI and the `nox` `cov` session
  already enforce on the command line (`--cov-fail-under=100`) and the
  100% figure advertised throughout the docs.
- **`server.json` capability.** `tools.listChanged` corrected from
  `false` to `true` to match what the running FastMCP server advertises
  in the `initialize` handshake.
- **Dependency hygiene (Dependabot).** Consolidated four routine updates,
  none touching the runtime dependency tree: dev tools `ruff` 0.15.13 →
  0.15.15 and `hypothesis` 6.152.7 → 6.155.0 (lockfile), and the pinned
  CI-action SHAs for `github/codeql-action` (4.35.5 → 4.36.0) and
  `codecov/codecov-action` (6.0.0 → 6.0.1). Closes #44, #45, #46, #47.
- **Release workflow fix.** `release.yml` references the SLSA provenance
  generator reusable workflow by its `v2.1.0` tag rather than a commit SHA.
  The generator self-verifies its own ref (`refs/tags/vX.Y.Z`) and rejects
  SHA pins, so the earlier Scorecard "pin actions by hash" pass had silently
  broken the release pipeline; this restores a working PyPI publish + SLSA
  provenance + Sigstore-signed GitHub Release.

### Documentation
- **`ARCHITECTURE.md` rewritten to match the shipped code.** The previous
  module map described an aspirational system of roughly fifty modules,
  most of which do not ship — an HTTP transport with OAuth, MCP resources
  and prompts, a multi-layer Redis cache, federation, biothreat
  screening, ed25519 signing, and client modules for UniProt, RCSB PDB,
  InterPro, openFDA, ClinicalTrials, and PubMed. It now documents only
  what ships: the stdio transport, the single FastMCP application with 29
  tools, the nine upstream clients plus the shared base, the `domain`
  types, and the SQLite knowledge graph. A clearly delimited "Roadmap
  (not yet shipped)" section records the unimplemented items, and the six
  empty namespace packages are named as reserved. Broken cross-references
  (`docs/THREAT_MODEL.md`, `docs/adr/`) were corrected.
- **Documentation site is link-clean.** Corrected the residual "13 other
  data sources" claim in the `mkdocs.yml` site description and the "14
  upstream APIs" figure in the threat-model diagram (both now 9), fixed
  the broken `docs/adding-a-client.md` reference in `CONTRIBUTING.md`, and
  repaired the cross-document links that resolved on GitHub but not in the
  rendered site (absolute URLs for the snippet-included root documents;
  in-site relative links for the example pages). `mkdocs build` now emits
  no broken-link warnings.
- **mkdocstrings.** Disabled griffe's `warn_unknown_params` so the
  deliberate single-`params`-model docstring convention no longer
  produces spurious build warnings.
- **Social-preview cards.** Enabled mkdocs-material's `social` plugin so
  the documentation site generates an Open Graph card per page (title plus
  the accurate, non-overclaiming site description); shared links now render
  a preview instead of a bare URL. Adds the `imaging` extra to the docs
  dependency group and the Cairo/Pango system libraries to the docs CI
  workflow.

---

## [1.1.8] - 2026-05-24

A metadata-consistency and validation-posture patch. Closes version
drift between `pyproject.toml` / `__init__.py` (which were bumped to
1.1.8 in PR #43) and the 12+ documentation and manifest files that
still read `1.1.7`. Downgrades the maturity claim from
`Production/Stable` to `Beta` to match the project's actual
deployment and validation status.

### Fixed
- **Version drift.** 12 files (`README.md`, `STATUS.md`,
  `LIMITATIONS.md`, `CITATION.cff`, `docs/index.md`,
  `docs/installation.md`, `mkdocs.yml`, `server.json` status_note)
  still read `1.1.7` after the `pyproject.toml` / `__init__.py` /
  `server.json` / `.well-known/mcp.json` / `smithery.yaml` version
  fields were bumped to `1.1.8` in PR #43.
- **Stale test count.** All references to "677 tests" updated to
  689, the current `pytest --collect-only` count (includes
  parametrised expansions).
- **`CONTRIBUTING.md` overclaims.** Removed unsubstantiated claims
  that the software is "used by pharmaceutical, clinical-research,
  and defense organizations" and that "real clinicians, researchers,
  and analysts use [it] to make consequential decisions." No evidence
  supports either claim; `STATUS.md` explicitly states no production
  deployment has occurred.
- **`CONTRIBUTING.md` nox sessions.** The "How to Run the Test
  Pyramid" section listed 9 nox sessions (`unit`, `property`,
  `contract`, `client`, `integration`, `benchmark`, `security`,
  `mutation`, `perf`) that do not exist in `noxfile.py`. Replaced
  with the actual sessions.
- **`CONTRIBUTING.md` coverage gate.** Stated "≥ 95% line, ≥ 90%
  branch" but `noxfile.py` enforces `--cov-fail-under=100` and
  `pyproject.toml` sets `fail_under = 99`. Corrected to "100% line
  and branch".

### Changed
- **PyPI classifier** downgraded from
  `Development Status :: 5 - Production/Stable` to
  `Development Status :: 4 - Beta`. The project has no production
  deployment experience (LIMITATIONS L4), no scientific validation
  (STATUS.md), and no external contributors. `Production/Stable`
  was not supported by evidence.
- **Maturity field** in `server.json`, `.well-known/mcp.json`, and
  `smithery.yaml` changed from `"stable"` to `"beta"`.
- **Language throughout** changed from "engineering-grade" to
  "engineering-validated" to avoid implying a maturity level the
  project has not reached.

### Added
- **`STATUS.md` validation matrix.** A table distinguishing
  engineering validation (unit tests, coverage, static analysis,
  security scanning, release provenance) from scientific validation,
  clinical validation, and regulatory certification — all three
  marked as "Not performed" / "None".
- **`REVIEWER.md`.** Step-by-step guide for a cold reviewer to
  install, self-test, run the offline test suite, inspect examples,
  and verify release provenance.

### Verified
- `grep -rn '1\.1\.7'` across all version-bearing files returns
  zero hits (only historical CHANGELOG entries remain).
- `grep -rn 'Production/Stable\|maturity.*stable'` across
  `pyproject.toml`, `server.json`, `.well-known/mcp.json`,
  `smithery.yaml` returns zero hits.
- 689 / 689 tests collected by `pytest --collect-only`.

---

## [1.1.7] - 2026-05-18

Ships the supply-chain hardening originally intended for v1.1.6.

### Context — why this is v1.1.7 and not a re-tagging of v1.1.6

The v1.1.6 release pipeline encountered two distinct interacting
issues that prevented the wheel from reaching PyPI and the signed
assets from reaching the GitHub release page:

1. The SLSA L3 reusable workflow ref was SHA-pinned alongside
   every other action. SLSA's trust model intentionally rejects
   SHA-pinned references because L3 attestations claim "this
   provenance was produced by a specific *named* version of the
   generator"; a commit SHA is not a named version. The
   `provenance / generator` job failed at validation. Fixed in
   PR #39 by reverting that single line to `@v2.0.0`.

2. The recovery attempt via `workflow_dispatch` from `main`
   (rather than re-tagging) was incompatible with SLSA L3's
   build-identity requirement: the generator's `final` job needs
   the calling workflow to be triggered by a tag-push so the
   build identity can be tied to an immutable named ref. A
   `workflow_dispatch` from a branch fails this check. The
   `provenance / final` job failed as a result.

v1.1.7 ships the *same workflow content* (every action SHA-pinned
except SLSA's reusable workflow, top-level minimum permissions on
ci.yml) via the supported `push: tags` trigger that v1.1.3,
v1.1.4, and v1.1.5 each used successfully. The v1.1.6 git tag and
its incomplete GitHub release (only the auto-generated source-code
zip + tar.gz assets, no wheel) are kept on the repo as an audit
artifact of the diagnostic process. The canonical released
version going forward is v1.1.7.

### Changed (same content as the v1.1.6 supply-chain hardening)

- Every `uses: <action>@<tag>` reference across `ci.yml`,
  `docs.yml`, `release.yml`, `scorecard.yml` is SHA-pinned to a
  40-character commit hash with a `# <tag>` trailing comment
  (closes the OpenSSF Scorecard `Pinned-Dependencies` findings).
- The SLSA L3 reusable workflow (`slsa-framework/slsa-github-
  generator/.github/workflows/generator_generic_slsa3.yml`) is
  kept on `@v2.0.0` per the trust-model requirement above, with
  the underlying commit SHA in a trailing comment for audit
  traceability.
- `ci.yml` declares a top-level `permissions: contents: read`
  block; the `codeql` job re-declares its own elevated
  permissions which take precedence (closes Scorecard
  `Token-Permissions` findings).

### Verified

- `uv lock` clean (only project version line changed)
- All four workflow YAML files parse with `yaml.safe_load`
- Every non-SLSA action ref is SHA-pinned (verified by
  `grep -rn 'uses: ' .github/workflows/ | grep -v '@[0-9a-f]{40}'
   | grep -v slsa-framework` returning zero hits)
- `ruff check` + `ruff format --check` clean on CI-scoped paths
- `mypy --strict` clean on CI-scoped paths (15 source files)
- Full pytest suite **677 / 677 passing**
- All six authoritative version sources read `1.1.7`; concept DOI
  unchanged (`10.5281/zenodo.20134773`).

### After release

This release MUST be triggered by pushing the `v1.1.7` git tag —
not by `workflow_dispatch`. The `release.yml` workflow will:
build the wheel; generate SLSA L3 provenance via the `@v2.0.0`
reusable workflow (now reachable through the supported trigger
path); publish to PyPI via OIDC trusted publishing; generate
CycloneDX + SPDX SBOMs; cosign keyless-sign each artifact; and
attach all 13 assets to the GitHub release. Zenodo's GitHub
integration will mint a fresh version-specific DOI under the
concept DOI as on every prior release.

---

## [1.1.6] - 2026-05-18

A supply-chain hardening patch. Closes the actionable
OpenSSF Scorecard findings (Token-Permissions × 3 and
Pinned-Dependencies × ~40) by SHA-pinning every GitHub Action
reference and tightening per-workflow `permissions:` blocks.
No functional code or dependency-tree changes — the only edits
to `src/` and `uv.lock` are the version-string bump from 1.1.5
to 1.1.6 (in `src/alphafold_sovereign/__init__.py` and the
project's own row in `uv.lock`); the dependency graph itself
is unchanged. 677/677 repo-wide tests still pass.

### Security — Pinned-Dependencies

Every `uses: <action>@<tag>` reference across the four workflow
files is now `uses: <action>@<40-char-SHA>  # <tag>`. This closes
the OpenSSF Scorecard `Pinned-Dependencies` findings (roughly 40
of them, one per `uses:` line) and prevents a hijacked-tag
supply-chain attack: an attacker who compromises an action's tag
to point at a malicious revision can no longer cause our workflow
to run that revision. The `# <tag>` trailing comment preserves
human readability; Dependabot's `uv` + `github-actions` ecosystem
config (added in v1.1.3) keeps pinned SHAs up-to-date when new
upstream versions release.

Actions SHA-pinned (commit SHA → tag for traceability):

| Action | SHA | Tag |
|---|---|---|
| `actions/checkout` | `34e114876b0b11c390a56381ad16ebd13914f8d5` | v4 |
| `actions/download-artifact` | `d3f86a106a0bac45b974a628896c90dbdf5c8093` | v4 |
| `actions/upload-artifact` | `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a` | v7 |
| `astral-sh/setup-uv` | `37802adc94f370d6bfd71619e3f0bf239e1f3b78` | v7 |
| `anchore/sbom-action` | `e22c389904149dbc22b58101806040fa8d37a610` | v0 |
| `codecov/codecov-action` | `57e3a136b779b570ffcdbf80b3bdc90e7fab3de2` | v6 |
| `github/codeql-action` | `9e0d7b8d25671d64c341c19c0152d693099fb5ba` | v4 |
| `ossf/scorecard-action` | `4eaacf0543bb3f2c246792bd56e8cdeffafb205a` | v2.4.3 |
| `pypa/gh-action-pypi-publish` | `cef221092ed1bacb1cc03d23a2d87d1d172e277b` | release/v1 |
| `sigstore/cosign-installer` | `398d4b0eeef1380460a10c8013a76f728fb906ac` | v3 |
| `slsa-framework/slsa-github-generator` | `5a775b367a56d5bd118a224a811bba288150a563` | v2.0.0 |

### Security — Token-Permissions

`ci.yml` now declares a top-level `permissions: contents: read`
block, which Scorecard's `Token-Permissions` check requires. The
`codeql` job inside `ci.yml` re-declares its own elevated
permissions (`security-events: write`, `actions: read`, `contents:
read`) — that job-level block takes precedence for codeql alone.
`release.yml` already had tight per-job permissions blocks
(introduced earlier in the release-readiness work); `docs.yml`
already had a minimum `contents: write` (the only privilege
`mkdocs gh-deploy` needs); `scorecard.yml` already had
appropriately scoped per-job permissions.

After this change, all four workflows declare their permissions
explicitly. Scorecard's `Token-Permissions` findings should
close on the next weekly Scorecard scan.

### Verified

- `uv lock` clean (no dependency changes; project version line
  only)
- All four workflow YAML files parse cleanly
- `grep -rn "uses: " .github/workflows/ | grep -v "@[0-9a-f]\{40\}"`
  returns zero hits (every action is SHA-pinned)
- `ruff check` + `ruff format --check` clean on CI-scoped paths
- Full pytest suite **677 / 677 passing**
- All six authoritative version sources read `1.1.6`; concept DOI
  unchanged (`10.5281/zenodo.20134773`).

### Scorecard findings that remain after this release

The following Scorecard findings are deliberately not addressed
here, with documented reasons:

- **Code-Review** (high) — requires a co-maintainer with a
  separate-approver workflow. Structurally unfixable while the
  project is solo-maintained; see `STATUS.md` "Project maturity".
- **Fuzzing** (medium) — OSS-Fuzz integration is out of scope for
  a project of this size composed mostly of thin API wrappers;
  most code paths are exercised exhaustively by the existing
  677-test hermetic suite with respx-mocked upstreams.
- **Branch-Protection** (high) — already addressed by the
  "Protect main" ruleset (https://github.com/smaniches/alphafold-sovereign-mcp/settings/rules)
  active since 2026-05-17; this finding will close on the next
  Scorecard scan when Scorecard re-reads the repo's protection
  rules.

The real vulnerability scanner — CodeQL `security-extended` —
continues to report zero findings on the shipped surface.

---

## [1.1.5] - 2026-05-17

A dependency-hygiene patch. Closes all ten Dependabot PRs
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
  Dependabot PRs were absorbed.

### Verified

- `uv lock` clean (no unexpected transitive drift beyond what was
  triggered by the named bumps)
- `pytest` 677/677 passing
- `ruff check` + `ruff format --check` clean on CI-scoped paths
- `mypy --strict` clean on mypy 2.1.x (CI-scoped paths)
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
    soberly in [`PATENTS.md`](https://github.com/smaniches/alphafold-sovereign-mcp/blob/main/PATENTS.md).
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

[Unreleased]: https://github.com/smaniches/alphafold-sovereign-mcp/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/smaniches/alphafold-sovereign-mcp/compare/v1.1.10...v1.2.0
[1.1.10]: https://github.com/smaniches/alphafold-sovereign-mcp/compare/v1.1.9...v1.1.10
[1.1.9]: https://github.com/smaniches/alphafold-sovereign-mcp/compare/v1.1.8...v1.1.9
[1.1.8]: https://github.com/smaniches/alphafold-sovereign-mcp/compare/v1.1.7...v1.1.8
[1.1.7]: https://github.com/smaniches/alphafold-sovereign-mcp/compare/v1.1.6...v1.1.7
[1.1.6]: https://github.com/smaniches/alphafold-sovereign-mcp/compare/v1.1.5...v1.1.6
[1.1.5]: https://github.com/smaniches/alphafold-sovereign-mcp/compare/v1.1.4...v1.1.5
[1.1.4]: https://github.com/smaniches/alphafold-sovereign-mcp/compare/v1.1.3...v1.1.4
[1.1.3]: https://github.com/smaniches/alphafold-sovereign-mcp/compare/v1.1.2...v1.1.3
[1.1.2]: https://github.com/smaniches/alphafold-sovereign-mcp/compare/v1.1.1...v1.1.2
[1.1.1]: https://github.com/smaniches/alphafold-sovereign-mcp/compare/v1.1.0-rc1...v1.1.1
[1.1.0-rc1]: https://github.com/smaniches/alphafold-sovereign-mcp/releases/tag/v1.1.0-rc1
[1.0.0]: https://github.com/smaniches/alphafold-sovereign-mcp/releases/tag/v1.0.0
