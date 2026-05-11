# Security Policy

The AlphaFold Sovereign MCP project takes security seriously. We are
relied upon by pharmaceutical, clinical-research, defense, and
intelligence users who operate under regulatory regimes where a
single unreported vulnerability can cost lives or compromise national
security. This document specifies how we receive, triage, and resolve
security reports.

## Supported Versions

We accept vulnerability reports against the following versions:

| Version | Supported | Until |
|---|---|---|
| `main` branch | ✅ | always |
| Latest minor release | ✅ | next minor release + 6 months |
| Previous minor release | ✅ | next minor release + 6 months |
| LTS releases (Enterprise Edition) | ✅ | 24 months from GA |
| All other older releases | ❌ | — |

## Coordinated Disclosure

**Please do not file public GitHub issues for security vulnerabilities.**

Send reports privately to one of:

| Channel | Address |
|---|---|
| Email | `security@topologica.ai` |
| GitHub Security Advisories | <https://github.com/smaniches/alphafold-sovereign-mcp/security/advisories/new> |

Encrypt sensitive reports with our PGP key:

- Fingerprint: *(to be published with the v1.0 GA release; until then,
  use GitHub Security Advisories, which encrypt at rest)*
- Key location: `https://topologica.ai/security/pgp.asc`

When in doubt, write to `security@topologica.ai`. We confirm receipt
within **24 hours** for any submission, weekdays or weekends.

## What to Include

A complete report contains:

1. **Affected version(s)** and configuration (transport, OS, auth
   mode, deployment topology).
2. **Vulnerability class** — CWE if known, or a one-line description.
3. **Proof of concept** — minimal reproduction. We accept attachments,
   private gists, signed PRs to a security advisory draft, or video.
4. **Impact** — what an attacker gains. Specify confidentiality,
   integrity, availability, or compliance impact (e.g., breaks 21 CFR
   Part 11 audit-trail immutability).
5. **Suggested mitigation** if you have one. Optional.
6. **Whether you wish to be credited** in the published advisory, and
   how (handle, real name, employer, ORCID, etc.).

## Our Response SLA

| Severity (CVSS v4) | First response | Investigation | Patch & advisory |
|---|---|---|---|
| Critical (≥ 9.0) | 24 hours | 72 hours | 7 days |
| High (7.0–8.9) | 48 hours | 7 days | 30 days |
| Medium (4.0–6.9) | 5 business days | 30 days | next minor release |
| Low (< 4.0) | 10 business days | 60 days | next minor release |

We will keep you informed at every step. If we cannot meet the above
SLA for any reason, we will tell you in writing why, and propose a
revised plan.

## Defensive-Bio Reports — Special Handling

This project ships sequence-of-concern screening tooling aligned with
the HHS *Framework for Nucleic Acid Synthesis Screening*. Reports
related to that tooling — whether bypasses, false negatives, or
suspected misuse — are routed immediately to a small bioethics-aware
response cell. We respond within **24 hours** regardless of CVSS
score because operational misuse can have consequences beyond
software.

If your report concerns suspected operational misuse (rather than a
software defect), you may CC `biosec@topologica.ai`.

## Safe Harbor

We will not pursue legal action against researchers who:

1. Make a good-faith effort to comply with this policy.
2. Avoid privacy violations, destruction of data, and interruption or
   degradation of our services and our users' services.
3. Give us a reasonable time to investigate and resolve the issue
   before any public disclosure.
4. Do not exploit a vulnerability beyond the minimum necessary to
   demonstrate it.

This safe-harbor commitment is binding on TOPOLOGICA LLC and on its
Enterprise customers via the standard Enterprise Edition contract.

## Disclosure Timeline

Our default is a **90-day disclosure window** from initial report to
public CVE publication, extendable by mutual agreement. After the
window expires we publish the advisory regardless of whether all
downstream users have patched, because silence helps no one.

Critical vulnerabilities exploited in the wild may be disclosed
faster, with explicit coordination with the reporter, CISA's KEV
program, and major downstream packagers (Linux distros, conda-forge,
cloud marketplaces).

## Hall of Fame

We list every researcher who reports a confirmed vulnerability in the
**SECURITY HALL OF FAME** appended to each release advisory, with
their preferred name and link, unless they request anonymity.

No bug bounty is offered at this time. The Enterprise Edition
contract may add one; ask `enterprise@topologica.ai`.

## Supply-Chain Provenance

Every release ships with:

- **CycloneDX** and **SPDX** Software Bills of Materials.
- **SLSA Level 3** build-provenance attestations.
- **Sigstore / cosign** keyless signatures (Fulcio + Rekor).
- **Reproducible-build verification scripts** under `scripts/replicate.sh`
  (POSIX) and `scripts/replicate.ps1` (Windows).

Verify a release before deploying with:

```bash
./scripts/replicate.sh <version>
```

Any discrepancy is itself a security issue under this policy.

---

*Last updated: 2026-05-10*
