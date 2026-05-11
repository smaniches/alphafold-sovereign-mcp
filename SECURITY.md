# Security Policy

This project is independent open-source software. Security reports
are welcomed and handled with care, on a best-effort basis from a
small group of volunteer maintainers.

## Supported versions

| Version | Supported |
|---|---|
| `main` branch | ✓ |
| Latest minor release | ✓ |
| Previous minor release | ✓ (6 months after a new minor releases) |
| All older releases | ✗ |

## Coordinated disclosure

**Please do not file public GitHub issues for security
vulnerabilities.**

Use GitHub Security Advisories instead:

<https://github.com/smaniches/alphafold-sovereign-mcp/security/advisories/new>

GitHub Security Advisories are encrypted at rest and visible only to
the project maintainers until publication.

Acknowledgement of receipt: best-effort, typically within a few
business days. This is a volunteer project; we cannot guarantee a
24-hour response and we will not pretend otherwise.

## What to include

A useful report contains:

1. **Affected version(s)** and configuration (transport, OS,
   deployment topology).
2. **Vulnerability class** — CWE if known, or a short description.
3. **Proof of concept** — minimal reproduction. Attachments, private
   gists, or a draft pull request against a security advisory are all
   fine.
4. **Impact** — what an attacker gains.
5. **Suggested mitigation**, if any. Optional.
6. **Whether you wish to be credited** in the published advisory, and
   how.

## Triage approach

The project does not promise an SLA. In practice we triage
vulnerabilities by impact:

- Remote code execution, secret/credential exposure, integrity
  compromise of the local SQLite knowledge graph, or sandbox-escape
  bugs: investigated and patched as a priority.
- DoS, panic-on-input, or upstream-API misuse: investigated; patched
  in the next minor release where possible.
- Reports against archived modules under `_archive/legacy/`: noted
  but not actively patched, since those modules are deprecated.

## Defensive biology

If your report relates to sequence-of-concern screening or related
tooling — bypasses, false negatives, suspected misuse — please use
the GitHub Security Advisory channel and mark it as
biosecurity-sensitive in the report body. We will route it through
the project's coordinated-disclosure process before any public
discussion.

## Safe harbor

We will not pursue legal action against researchers who:

1. Make a good-faith effort to comply with this policy.
2. Avoid privacy violations, destruction of data, and interruption or
   degradation of services and users' services.
3. Give the project a reasonable time to investigate and resolve the
   issue before public disclosure.
4. Do not exploit a vulnerability beyond the minimum necessary to
   demonstrate it.

## Disclosure window

Default disclosure window: **90 days** from initial report to public
advisory, extendable by mutual agreement. Critical vulnerabilities
actively exploited in the wild may be disclosed faster with
coordination.

## Credit

Every researcher who reports a confirmed vulnerability is credited in
the published advisory with their preferred name and link, unless
they request anonymity.

No bug bounty is offered.

## Supply-chain provenance

Every release publishes:

- A **CycloneDX** SBOM.
- A reproducible-build verification script at
  `scripts/replicate.sh`.

Cosign signatures and SLSA build-provenance attestations are tracked
work items on the roadmap; they are not yet emitted by the release
pipeline.

---

*Last updated: 2026-05-11*
