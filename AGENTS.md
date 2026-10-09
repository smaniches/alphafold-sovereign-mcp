# Instructions for AI coding agents

This is an independently maintained, public research-oriented MCP server,
**not** an AlphaFold prediction model or clinical decision-support product.
Make minimal, reviewable changes with explicit evidence. No agent should
self-approve, bypass branch protections, publish, or silently merge changes.

## Canonical repository references

- `README.md`: user-facing capabilities, installation, non-affiliation.
- `ARCHITECTURE.md`: shipped module and protocol boundaries.
- `STATUS.md` and `LIMITATIONS.md`: actual validation and known gaps.
- `docs/afdb-compatibility.md`: AlphaFold DB field renames, isoform
  selection, fragment limitations, and experimental annotation boundaries.
- `docs/tools/`: documented tool arguments and usage.
- `.github/workflows/ci.yml` and `release.yml`: required checks and
  authenticated release workflow.

Prefer these files over older discussions or cached context. Update them
when a code change modifies a published contract; avoid duplicated claims.

## Safe development

1. Inspect production modules and tests before modifying behavior.
2. Keep the current 30 public MCP tools backwards compatible unless a
   deliberately versioned protocol change is justified.
3. Preserve meaningful identifier provenance: UniProt accession and
   isoform, model entity, source release/version, publication, and
   residue numbering. Do not silently equate PDB, UniProt and predicted
   model residue indices.
4. New upstream clients must validate remote hosts and schemas, respect
   timeouts/rate limits, and avoid uncontrolled egress in offline mode.
   An upstream error is not proof of biological absence.
5. Use deterministic `respx` fixtures, negative/edge cases, and regression
   tests; add a recorded or manually verified live API example when an
   upstream schema changes. Do not rely only on import smoke tests.
6. Verify lint, strict typing, security audit, unit/property and protocol
   tests, package build, release-path proof and relevant fuzz checks.
   Follow CI for the authoritative commands and platform matrix.
7. Keep `pyproject.toml` and `uv.lock` in sync. Major library upgrades
   require protocol/client behavior tests, not just a green import.
8. Do not edit packaged distribution artifacts, claim a release happened,
   or manufacture validation results. PyPI/GitHub signing and release
   verification are handled by `.github/workflows/release.yml`.
9. Never auto-merge bot PRs just because routine checks passed.
   Review API contracts and dependency behavior; use the protected PR
   workflow and preserve an auditable diff.

## Scientific and medical claims

- AlphaFold structures are predictions; pLDDT and PAE are model
  uncertainty indicators, **not** experimental confirmation.
- Drug-target tiers and ACMG evidence drafts are uncalibrated/unreviewed
  aids, not clinical classifications or treatment recommendations.
- A 100% line/branch coverage score demonstrates exercised code paths,
  not scientific or clinical correctness, production reliability or
  completeness of upstream data.
- AlphaFold DB's 2026 literature-derived residue annotations are
  upstream functionality; the server must not claim to expose or
  independently validate those annotations until a documented API,
  source evidence and SIFTS coordinate mapping have been implemented
  and tested.
- Document limitations and counterexamples before broadening claims.

## Writing and support

Prefer concise, accessible tool descriptions that state inputs, outputs,
source of evidence, and limitations. Error messages should distinguish
missing data from network/API failure where feasible. Minimize automation
noise; keep security, release integrity, and regression gates intact.
