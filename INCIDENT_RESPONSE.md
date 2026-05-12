# Incident Response

This document describes how the `alphafold-sovereign-mcp` project
handles security incidents and operational outages. It is the
companion to [`SECURITY.md`](SECURITY.md) (vulnerability disclosure
policy) and complements [`AUDIT.md`](AUDIT.md) (audit posture) and
[`docs/threat-model.md`](docs/threat-model.md).

## What counts as an incident

Any of the following:

| Category | Example |
|---|---|
| **Security** | A vulnerability is reported via private disclosure. A secret is accidentally committed. A dependency is found to be backdoored. |
| **Data integrity** | A user reports that the server produced systematically wrong output (e.g., wrong ACMG criteria for a class of variants). |
| **Supply chain** | A release artefact's checksum/signature does not verify against the SLSA provenance. PyPI account is compromised (does not apply to v1.1.0-rc1 since we are not on PyPI). |
| **Outage** (informational only, no SLA) | Upstream API change breaks tool output. Server cannot start on a supported platform. |

## Severities

| Severity | Definition | First-response target |
|---|---|---|
| **Critical** | Exploitable RCE, secret exposure, or data corruption affecting committed users. | 1 business day |
| **High** | Vulnerability with workaround; systematic incorrect output; broken release artefact. | 3 business days |
| **Medium** | Vulnerability requiring user interaction; non-systematic incorrect output. | 1 week |
| **Low / informational** | Hygiene issue, doc bug, minor mis-claim. | Best effort |

**Note**: This is a single-maintainer project. "Business day" means
working hours of the maintainer. SLAs are aspirational targets, not
contractual commitments.

## Response flow

```
       ┌─────────────────────┐
       │ Incident reported   │
       │ (issue, advisory,   │
       │  email, in-person)  │
       └──────────┬──────────┘
                  ▼
       ┌─────────────────────┐
       │ Triage:              │
       │  - confirm           │
       │  - assign severity   │
       │  - assign owner      │
       └──────────┬──────────┘
                  ▼
       ┌─────────────────────┐         ┌──────────────────────┐
       │ Stabilise:           │ ◄────── │ Coordinated          │
       │  - mitigate or roll  │         │ disclosure (private  │
       │    back              │         │ until fix is ready)  │
       │  - communicate       │         └──────────────────────┘
       └──────────┬──────────┘
                  ▼
       ┌─────────────────────┐
       │ Fix:                 │
       │  - patch PR          │
       │  - tests covering    │
       │    the regression    │
       │  - cut release       │
       └──────────┬──────────┘
                  ▼
       ┌─────────────────────┐
       │ Postmortem (PM):    │
       │  - root cause       │
       │  - timeline         │
       │  - action items     │
       │  - publish to       │
       │    AUDIT.md log     │
       └─────────────────────┘
```

## Communication channels

| Audience | Channel |
|---|---|
| Reporter (during private disclosure) | Email reply to `security@topologica.ai` or GitHub Security Advisory thread |
| Affected users | GitHub Release notes; CHANGELOG.md; STATUS.md if posture changes |
| Public audit log | `AUDIT.md` (post-resolution summary) |
| Subscribers / watchers | GitHub repo "watch" notifications |

## Postmortem template

When an incident closes, the resolver writes a brief postmortem in
the issue (or, for security incidents, in `AUDIT.md` after the
disclosure window expires). The template:

```markdown
## Postmortem: <short title>

**Severity:** Critical | High | Medium | Low
**Detected:** <UTC timestamp>
**Resolved:** <UTC timestamp>
**Affected versions:** <range>
**Reporter:** <name or "internal">

### Summary
One-paragraph plain-English description of what happened and what the
impact was on users.

### Timeline (UTC)
- HH:MM — first signal
- HH:MM — confirmed
- HH:MM — mitigation deployed
- HH:MM — fix released

### Root cause
What in the code, dependencies, or process let this happen.

### What worked
- …

### What didn't
- …

### Action items
- [ ] PR #N: <description> — owner @<handle> — due <date>
- [ ] …

### Lessons
What we change going forward.
```

## Postmortem archive

Historical postmortems will be linked from this section as they are
written. As of v1.1.0-rc1 there are none.

| Date | Title | Severity | Link |
|---|---|---|---|
| — | (none yet) | — | — |

---

Last updated: 2026-05-11.
