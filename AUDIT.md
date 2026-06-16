# External Audit Status

> **As of v1.2.1: no external audit has been performed.**

This document tracks the audit posture of `alphafold-sovereign-mcp`.
Audit findings, when they exist, will be summarised here with the
issue and PR numbers that resolved them.

## What has been audited

The repository receives automated code review on its pull requests from
`gemini-code-assist[bot]` and `chatgpt-codex-connector[bot]`. Cumulative review
activity through v1.2.1:

| Surface | Auditor | Date(s) | PRs reviewed | Outcome |
|---|---|---|---|---|
| Engineering (code, docs, tests, CI, manifests, release process) | `gemini-code-assist[bot]` (automated) | 2026-05-11 → 2026-05-17 | [#2](https://github.com/smaniches/alphafold-sovereign-mcp/pull/2), [#6](https://github.com/smaniches/alphafold-sovereign-mcp/pull/6), [#15](https://github.com/smaniches/alphafold-sovereign-mcp/pull/15), [#16](https://github.com/smaniches/alphafold-sovereign-mcp/pull/16), [#17](https://github.com/smaniches/alphafold-sovereign-mcp/pull/17), [#18](https://github.com/smaniches/alphafold-sovereign-mcp/pull/18), [#19](https://github.com/smaniches/alphafold-sovereign-mcp/pull/19), [#30](https://github.com/smaniches/alphafold-sovereign-mcp/pull/30) | Cumulative ~13 inline suggestions across docs, manifests, dependency hygiene, and ACMG warning surfaces. Every suggestion resolved via a follow-up commit; see each PR's *Conversation* tab for the resolution trail. |
| Engineering (full-tree typing, metadata/release contracts, capability-claim accuracy, dependency security) | `gemini-code-assist[bot]` + `chatgpt-codex-connector[bot]` (automated) | 2026-06-16 | [#101](https://github.com/smaniches/alphafold-sovereign-mcp/pull/101), [#102](https://github.com/smaniches/alphafold-sovereign-mcp/pull/102), [#107](https://github.com/smaniches/alphafold-sovereign-mcp/pull/107), [#108](https://github.com/smaniches/alphafold-sovereign-mcp/pull/108) | 8 inline suggestions across the v1.2.0 → v1.2.1 hardening. Applied where correct (a residue-count `int` fix; a self-referential test-count contract de-numbered; a shared small-molecule-tractability predicate); declined with recorded rationale: one genuine false positive (a coroutine flagged as synchronous), and three runtime-identical `typing.cast()` style suggestions kept in quoted form to satisfy the project's ruff TC006 rule. All threads resolved before merge. |

## What has NOT been audited

| Surface | Why this matters | When | Tracked at |
|---|---|---|---|
| ACMG/AMP criterion mapping (`tools/precision_medicine.py`) | The mapping is implemented from Richards et al. 2015 but no clinical geneticist has signed off. | Roadmap step 3 of v1.2.0 — see [STATUS.md](https://github.com/smaniches/alphafold-sovereign-mcp/blob/main/STATUS.md) | [LIMITATIONS L1](https://github.com/smaniches/alphafold-sovereign-mcp/blob/main/LIMITATIONS.md#l1--acmg-criterion-mapping-is-not-independently-validated) |
| Druggability tier heuristic (`tools/precision_medicine.py`) | The score cut-offs (HOT/WARM/COLD) are author judgement, not calibrated. | Roadmap step 4 of v1.2.0 | [LIMITATIONS L2](https://github.com/smaniches/alphafold-sovereign-mcp/blob/main/LIMITATIONS.md#l2--druggability-tier-thresholds-are-unvalidated-heuristics) |
| End-to-end real-API behaviour | All tests mock the upstream APIs. We have not run the pipeline against held-out variants/targets with known expected outputs. | Roadmap step 1 of v1.2.0 (`examples/` golden notebooks) | [LIMITATIONS L3](https://github.com/smaniches/alphafold-sovereign-mcp/blob/main/LIMITATIONS.md#l3--upstream-api-schemas-are-not-pinned) |
| Threat model | First STRIDE-style review was written by the maintainer in v1.1.0-rc1 (see `docs/threat-model.md`). External STRIDE review by a security professional has not been performed. | Defer until external security audit | [`docs/threat-model.md`](https://github.com/smaniches/alphafold-sovereign-mcp/blob/main/docs/threat-model.md) |
| Independent security audit | No external penetration test or code-security audit yet. | Not yet scheduled | This document |
| Performance / load behaviour | No production deployment yet. | Defer until first real deployment | [LIMITATIONS L4](https://github.com/smaniches/alphafold-sovereign-mcp/blob/main/LIMITATIONS.md#l4--no-production-deployment-experience) |

## How to request an audit

If you are a researcher, auditor, or compliance officer interested in
reviewing this project, please:

1. Open a GitHub issue with the `audit` label describing the audit
   scope you have in mind.
2. Mention the maintainer (`@smaniches`).
3. For sensitive findings, follow the disclosure process in
   [SECURITY.md](https://github.com/smaniches/alphafold-sovereign-mcp/blob/main/SECURITY.md).

## Audit log

This section is appended to when audits complete. Each entry has:
- Date
- Auditor identity and credentials
- Scope reviewed
- Findings (high / medium / low / informational)
- Resolution PRs

| Date | Auditor | Scope | Findings | Status |
|---|---|---|---|---|
| 2026-05-11 | `gemini-code-assist[bot]` | PR #2 — STATUS / LIMITATIONS docs review | 2 inline suggestions on ACMG warning surfaces | Resolved in commit `ae42b59` |
| 2026-05-16 | `gemini-code-assist[bot]` | PR #6 — MONDO disease-label fix | 1 inline suggestion (direct attribute access vs. `getattr` default) | Resolved in [PR #13](https://github.com/smaniches/alphafold-sovereign-mcp/pull/13) |
| 2026-05-17 | `gemini-code-assist[bot]` | PR #16 — prepare v1.1.1 release | 3 inline suggestions (maturity field consistency across `smithery.yaml`, `server.json`, `.well-known/mcp.json`) | Resolved in [PR #17](https://github.com/smaniches/alphafold-sovereign-mcp/pull/17) |
| 2026-05-17 | `gemini-code-assist[bot]` | PR #17 — finish v1.1.1 stable-release framing pass | 2 inline suggestions (`uvx` idiom; `Development Status :: 5 - Production/Stable` classifier) | Resolved in commit `ed08229` |
| 2026-05-17 | `gemini-code-assist[bot]` | PR #18 — v1.1.2 metadata-coherence | 2 inline suggestions (CHANGELOG `PRs #17` → `PR #17`; `smithery.yaml` missing `maturity: stable`) | Resolved in commit `a5a4202` |
| 2026-05-17 | `gemini-code-assist[bot]` | PR #19 — v1.1.3 dep-trim + Minerva CVE close | 2 inline suggestions (CHANGELOG `Six` → `Seven`; Dependabot ecosystem `pip` → `uv`) | Resolved in commit `61ed61c` |
| 2026-05-17 | `gemini-code-assist[bot]` | PR #30 — v1.1.4 accuracy patch | 1 inline suggestion (internal consistency: this audit summary itself said "through v1.1.3" while the document header said "As of v1.1.4") | Resolved in this commit |
| 2026-06-16 | `gemini-code-assist[bot]` + `chatgpt-codex-connector[bot]` | [PR #101](https://github.com/smaniches/alphafold-sovereign-mcp/pull/101) — metadata contract tests + Zenodo deposition metadata | 2 suggestions: a coroutine (`mcp.list_tools()`) flagged as a synchronous call; a test-count contract flagged as self-referential | Resolved before merge (`70db7c0`): the coroutine finding declined with rationale (`list_tools` is `async` under FastMCP 3.4.2); the published test count de-numbered across four documentation surfaces and the contract test inverted to forbid any surface from publishing a volatile count |
| 2026-06-16 | `gemini-code-assist[bot]` | [PR #102](https://github.com/smaniches/alphafold-sovereign-mcp/pull/102) — full source tree under `mypy --strict` | 4 suggestions: three to unquote `typing.cast()` type expressions; one to change a residue count from `float` to `int` | Resolved before merge (`772dd3d`): the `int` fix applied; the three unquote suggestions declined — ruff rule TC006 requires the cast type expression to be quoted |
| 2026-06-16 | `gemini-code-assist[bot]` + `chatgpt-codex-connector[bot]` | [PR #107](https://github.com/smaniches/alphafold-sovereign-mcp/pull/107) — align user-facing capability claims with the implementation; ship `py.typed` | 2 inline suggestions (gemini + codex): gate the HOT actionability clause on the same small-molecule-tractability predicate the score uses, and ignore null/empty/whitespace tractability labels | Resolved before merge (`590583e`): a shared `_has_small_molecule_tractability()` predicate introduced so both code paths agree |
| 2026-06-16 | `gemini-code-assist[bot]` | [PR #108](https://github.com/smaniches/alphafold-sovereign-mcp/pull/108) — bump starlette / python-multipart / cryptography | Summary review; no inline change requested | Merged (`a9a658d`); cleared 9 Dependabot alerts (resolved by the dependency upgrades) |

---

Last updated: 2026-06-16.
