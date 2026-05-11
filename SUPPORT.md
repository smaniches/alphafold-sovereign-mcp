# Getting Support

## Community Support (Free)

| Channel | Purpose |
|---|---|
| [GitHub Discussions](https://github.com/smaniches/alphafold-sovereign-mcp/discussions) | Questions, ideas, show-and-tell |
| [GitHub Issues](https://github.com/smaniches/alphafold-sovereign-mcp/issues) | Confirmed bugs, feature requests |
| [Docs site](https://docs.topologica.ai) | Reference, recipes, compliance |

Response time for community issues: best-effort, typically 5–10
business days from a Committer or TSC member.

**Do not use GitHub Issues for security vulnerabilities.** See
[`SECURITY.md`](./SECURITY.md).

## Enterprise Support (Paid)

Enterprise Edition subscribers receive:

| Tier | SLA | Channels |
|---|---|---|
| Standard | 24-hour business response | Email + private GitHub |
| Priority | 8-hour response (24/7 for Sev-1) | Email + Slack connect + calls |
| Mission-Critical | 2-hour response (24/7, all severities) | Dedicated Slack + on-call |

Contact `enterprise@topologica.ai` to discuss.

## Government / Regulated-Industry Support

For FedRAMP, GxP, 21 CFR Part 11, or national-security deployments,
write to `gov@topologica.ai`. We offer scoped architecture reviews,
validation packages, and documentation suitable for regulatory audits.

## How to File a Great Bug Report

The faster we can reproduce it, the faster we fix it. Ideal reports
include:

1. AlphaFold Sovereign MCP version (`python -m alphafold_sovereign --version`).
2. Python version, OS, deployment mode (stdio / HTTP).
3. Minimal config (`--config` or env vars, redacted of credentials).
4. The exact tool call that failed (MCP JSON or `mcp-inspector` dump).
5. Full stderr / structured log output.
6. What you expected vs. what happened.
7. Whether it is reproducible, and how often.

We triage daily. An issue without a reproduction takes 5× longer to
fix, and may be closed as `needs-info` after 14 days.
