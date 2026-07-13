# Project Status

**Version:** v1.4.0 <!-- x-release-please-version -->
**Stage:** Beta. Engineering-validated infrastructure; scientifically
unvalidated by independent domain experts.

This document exists so that any reader — reviewer, auditor, potential
contributor, downstream user — can in 60 seconds form an accurate
expectation of what this project is and is not.

---

## Validation matrix

| Dimension | Status | Evidence |
|---|---|---|
| Offline unit tests | Passing | `uv run pytest tests/` on every PR; CI matrix across Python 3.10–3.13 |
| Line + branch coverage | 100% on shipped surface | `nox -s cov`; enforced by `--cov-fail-under=100` |
| Static analysis | Clean | `ruff check`, `mypy --strict`, `bandit` on every PR |
| Security scanning | Clean | CodeQL `security-extended` on every push; no open findings |
| Release provenance | Sigstore signature bundles + CycloneDX SBOM attached; SLSA L3 generated in CI | `release.yml`; `scripts/replicate.sh` checks the PyPI wheel hash and SBOM/provenance presence (`cosign verify-blob` of the bundles is a roadmap item) |
| Integration tests (live APIs) | Not run in CI | Tests mock all upstreams via `respx`; no live-API CI job |
| Scientific validation | Not performed | ACMG mapping and druggability tier are unreviewed by domain experts |
| Clinical validation | Not performed | No clinical geneticist has signed off on any output |
| Regulatory certification | None | Not certified for HIPAA, GxP, 21 CFR Part 11, FedRAMP, FIPS, or SOC 2 |
| Production deployment | None | Never deployed as a long-running service for real users |

---

## What is solid

### Code architecture
- Five subpackages with clear single responsibilities — ``clients/``
  (9 upstream clients + 1 shared base), ``domain/`` (2 modules: disease
  types + the pure druggability heuristic), ``tools/`` (4
  MCP-tool modules), ``storage/`` (2 modules: SQLite KG + boot seed),
  ``server/`` (2 transport modules). 20 substantive ``.py`` files on the
  shipped surface.
- The previous monolith (~6,000 lines) is archived under
  ``_archive/legacy/`` and excluded from coverage and lint.
- No circular imports; client retry/circuit-breaker logic is a
  single module reused by every upstream client.

### Test suite
- **Comprehensive offline unit-test suite** (including parametrised expansions) across the shipped surface.
- **100% line + branch coverage** on the shipped surface
  (``src/alphafold_sovereign/``, excluding the archived monolith).
- Tests use ``respx`` to mock HTTP semantics (not just return values),
  ``hypothesis`` for property tests on parsers, and ``pytest-asyncio``
  for async client tests.
- The ACMG mapping, druggability tier scoring, and KG queries all have
  parametrised tests covering known input/output pairs from the
  implementation.

### Security & supply chain
- Bandit + pip-audit on every PR (Safety in the local ``nox -s security`` session).
- CodeQL ``security-extended`` on every push (public repo).
- CycloneDX SBOM generated from the installed package on every release
  tag (an SPDX document is also attached; populating it from the full
  dependency tree is a roadmap item).
- SLSA L3 in-toto build provenance generated in CI; Sigstore
  (``cosign``) keyless signing of every release artefact.
- PyPI publishing via OIDC Trusted Publishing (no API tokens stored
  in repo secrets).
- SQL parameterised everywhere; CWE-89 closed.

### Distribution
- Published to PyPI at https://pypi.org/project/alphafold-sovereign-mcp/
  (install with ``pip install alphafold-sovereign-mcp``).
- Zenodo concept DOI: 10.5281/zenodo.20134773 — version-independent
  identifier that redirects to the latest archived version. Each
  tagged GitHub Release mints its own version-specific DOI under
  this concept via the GitHub-Zenodo integration (verified on v1.1.3
  at 10.5281/zenodo.20262463).
- mkdocs documentation site auto-deploys to GitHub Pages on every
  push to main.

### CI matrix
- Python 3.10 / 3.11 / 3.12 / 3.13 on Ubuntu and macOS.
- Lint (ruff), format (ruff format), type-check (mypy strict),
  build (sdist + wheel), MCP schema validation.

### Legal kit
- Apache 2.0 (``LICENSE``). Pure Apache 2.0 — no commercial-edition
  carve-out.
- ``NOTICE``, ``PATENTS``, ``TRADEMARKS``, ``CONTRIBUTING``,
  ``SECURITY``, ``CODE_OF_CONDUCT``, ``GOVERNANCE``,
  ``INCIDENT_RESPONSE``, ``AUDIT``, ``PRIVACY``, ``SUPPORT``.

---

## What is NOT solid

### Scientific / clinical validation
- **No clinical geneticist has reviewed the ACMG mapping.** The
  implementation follows the 2015 Richards et al. guidelines but no
  independent expert has signed off on the criterion-by-criterion
  mapping. Use ``generate_variant_clinical_report`` or
  ``classify_variant_acmg`` as a research aid, never as clinical
  decision support.
- **The druggability tier scoring is a heuristic.** Cut-offs for the
  HOT / WARM / COLD / NOT_DRUGGABLE buckets were chosen by the author
  based on rough literature priors. They have not been calibrated
  against a benchmark of known druggable / non-druggable targets and
  are not citation-backed.
- **No end-to-end validation against real-world cases.** The test
  suite mocks every upstream API. The pipeline has not been run
  against a held-out set of variants/targets/diseases with known
  expected outputs.
- **No outcome data.** Nobody has measured how often the report
  agrees with a human geneticist, or how often the druggability tier
  predicts actual drug-discovery success.

### Operational
- **No production deployment.** This software has never been deployed
  as a long-running service for real users. Memory, latency,
  rate-limit, and failure-mode behaviour at scale is unknown.
- **No usage telemetry.** We do not collect any data on which tools
  are called, with what arguments, or whether results are useful.
- **No SLA.** Upstream APIs (Ensembl, Open Targets, ClinVar, gnomAD,
  AlphaFold DB, etc.) can change schema or go down; we do best-effort
  retries but make no availability guarantees.

### Project maturity
- **Single maintainer.** No bus factor > 1.
- **No external contributors yet.** Review process is documented in
  ``CONTRIBUTING.md`` but has not been exercised.
- **No formal release cadence.** v1.4.0 is the current release; <!-- x-release-please-version -->
  later versions will be tagged as the validation milestones below
  are met.

---

## What this means for users

| If you are …                  | You can use this project for …                             | You should NOT use this project for …                                                                            |
|-------------------------------|------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------|
| A researcher exploring a target | Pulling and joining data from 9 upstream sources via MCP | Making a final go/no-go decision on a drug programme                                                            |
| A clinical geneticist          | Quickly assembling a literature snapshot for a variant     | Issuing a clinical report; ACMG calls produced here are not validated and should be re-derived from raw sources |
| A platform engineer            | Studying a tested example of an MCP server with retries    | Production deployment without your own validation, monitoring, and SLA work                                     |
| A bioinformatician             | Prototyping a workflow that calls 9 sources behind one API| Reproducible publication-grade analyses (upstream APIs are not pinned by us)                                    |

---

## Roadmap (validation, post-1.2.0)

The validation gap is the highest-priority work after v1.2.0. The
planned, sequenced steps are:

1. **End-to-end golden examples.** Three documented notebooks under
   ``examples/`` running the full pipeline against well-characterised
   variants (BRCA1 c.5266dupC, TP53 R175H, EGFR L858R) with expected
   output stored as JSON and diffed in CI.
2. **ACMG traceability matrix.** A markdown table mapping each
   criterion (PVS1, PS1–4, PM1–6, PP1–5, BA1, BS1–4, BP1–7) to the
   line of code that implements it, the test that exercises it, and
   the 2015 Richards et al. section it derives from.
3. **External review.** One clinical geneticist to review the ACMG
   mapping; one medicinal chemist to review the druggability heuristic.
   Findings published as issues, then closed by PRs.
4. **Benchmark calibration.** Run druggability on a held-out set of
   approved-drug targets vs. failed-development targets and report
   precision/recall.
5. **Schema pinning.** Pin upstream API schemas to specific dates,
   with a documented refresh policy.

---

## Last updated

2026-06-16. This document is part of the repo; PRs to correct or
expand it are welcome.
