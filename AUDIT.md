# External Audit Status

> **As of v1.1.3: no external audit has been performed.**

This document tracks the audit posture of `alphafold-sovereign-mcp`.
Audit findings, when they exist, will be summarised here with the
issue and PR numbers that resolved them.

## What has been audited

| Surface | Auditor | Date | Outcome | Reference |
|---|---|---|---|---|
| Engineering (code, tests, CI) | `gemini-code-assist` (automated) | 2026-05-11 | 2 inline suggestions accepted; both small (clarify ACMG warnings to name `classify_variant_acmg` alongside `generate_variant_clinical_report`). | [PR #2](https://github.com/smaniches/alphafold-sovereign-mcp/pull/2) |

## What has NOT been audited

| Surface | Why this matters | When | Tracked at |
|---|---|---|---|
| ACMG/AMP criterion mapping (`tools/precision_medicine.py`) | The mapping is implemented from Richards et al. 2015 but no clinical geneticist has signed off. | Roadmap step 3 of v1.2.0 — see [STATUS.md](STATUS.md) | [LIMITATIONS L1](LIMITATIONS.md#l1--acmg-criterion-mapping-is-not-independently-validated) |
| Druggability tier heuristic (`tools/precision_medicine.py`) | The score cut-offs (HOT/WARM/COLD) are author judgement, not calibrated. | Roadmap step 4 of v1.2.0 | [LIMITATIONS L2](LIMITATIONS.md#l2--druggability-tier-thresholds-are-unvalidated-heuristics) |
| End-to-end real-API behaviour | All tests mock the upstream APIs. We have not run the pipeline against held-out variants/targets with known expected outputs. | Roadmap step 1 of v1.2.0 (`examples/` golden notebooks) | [LIMITATIONS L3](LIMITATIONS.md#l3--upstream-api-schemas-are-not-pinned) |
| Threat model | First STRIDE-style review is being written for v1.1.0-rc1. | This release | [`docs/threat-model.md`](docs/threat-model.md) |
| Independent security audit | No external penetration test or code-security audit yet. | Defer until v1.2.0 release | This document |
| Performance / load behaviour | No production deployment yet. | Defer until first real deployment | [LIMITATIONS L4](LIMITATIONS.md#l4--no-production-deployment-experience) |

## How to request an audit

If you are a researcher, auditor, or compliance officer interested in
reviewing this project, please:

1. Open a GitHub issue with the `audit` label describing the audit
   scope you have in mind.
2. Mention the maintainer (`@smaniches`).
3. For sensitive findings, follow the disclosure process in
   [SECURITY.md](SECURITY.md).

## Audit log

This section is appended to when audits complete. Each entry has:
- Date
- Auditor identity and credentials
- Scope reviewed
- Findings (high / medium / low / informational)
- Resolution PRs

| Date | Auditor | Scope | Findings | Status |
|---|---|---|---|---|
| 2026-05-11 | `gemini-code-assist[bot]` | PR #2 docs review | 2 inline suggestions, both accepted | Resolved in commit `ae42b59` |

---

Last updated: 2026-05-11.
