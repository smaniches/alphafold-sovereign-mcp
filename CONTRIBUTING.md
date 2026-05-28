# Contributing to AlphaFold Sovereign MCP

Thank you for considering a contribution. This project aims to be
a well-tested, well-documented MCP server for biomedical data access.
We hold contributions to a high engineering bar — and we will help
you meet it.

This document is the single source of truth for "how do I contribute,
and what will happen to my contribution?"

## TL;DR

1. Open or claim an issue first.
2. Branch from `main`: `claude/<short-topic>` or `<gh-username>/<short-topic>`.
3. Make the change. Run `nox -s lint type test`. Add tests.
4. Sign your commits with `-s` (Developer Certificate of Origin).
5. Open a pull request with the PR template filled out.
6. A maintainer responds within 5 business days.

## Code of Conduct

This project adopts the **Contributor Covenant 2.1**, available in
[`CODE_OF_CONDUCT.md`](https://github.com/smaniches/alphafold-sovereign-mcp/blob/main/CODE_OF_CONDUCT.md). By participating you
agree to be bound by it. Report violations to
`conduct@topologica.ai`.

## Developer Certificate of Origin

We use the **Developer Certificate of Origin** (DCO) instead of a
Contributor License Agreement. The DCO requires no paperwork. You
attest to it by signing each commit:

```bash
git commit -s -m "feat(clients): add MONDO disease ontology client"
```

This appends `Signed-off-by: Your Name <you@example.com>` to the
commit message. The full DCO text is at <https://developercertificate.org/>.

Why DCO instead of CLA? Lower contributor friction, same legal
protection for the project, and you keep your copyright. Linux kernel,
Docker, Kubernetes, and most CNCF projects use the DCO for the same
reason.

If you forget to sign:

```bash
git commit --amend --no-edit --signoff
git push --force-with-lease
```

CI blocks unsigned commits.

## What We Accept

| Type | Status |
|---|---|
| Bug fixes | ✅ always welcome |
| Documentation improvements | ✅ always welcome |
| New upstream-API clients (under `clients/`) | ✅ welcome — model them on `clients/_base.py` and the nine shipped clients |
| New tools that compose existing capabilities | ✅ welcome |
| Performance improvements with benchmarks | ✅ welcome |
| Refactors of >500 LOC | 🟡 discuss in an issue first |
| Build-system overhauls | 🟡 discuss in an issue first |
| New transports beyond stdio + Streamable HTTP | 🟡 must include MCP-spec citation |
| Features that bypass biosecurity screening | ❌ not accepted |
| Features that ship credentials, default API keys, or call-home telemetry | ❌ not accepted |

## What We Do Not Accept

- **Anything that requires removing the Apache 2.0 license or NOTICE.**
- **Anything that weakens the audit trail** (e.g., mutable log
  storage, unsigned events, optional provenance).
- **Anything that disables biosecurity screening by default.**
- **Dependencies with restrictive licenses** (GPL family, SSPL, BUSL,
  CC-NC) without prior maintainer approval and a license-compatibility
  analysis in the PR description.
- **Generated code that the contributor cannot personally explain
  line-by-line in review.** This includes large LLM-produced diffs.
  AI-assisted code is welcome — code that the contributor does not
  understand is not.

## How to Set Up a Dev Environment

```bash
# Prerequisites: Python 3.13, uv, git, optionally Docker
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone & sync
git clone https://github.com/smaniches/alphafold-sovereign-mcp.git
cd alphafold-sovereign-mcp
uv sync --extra dev

# Run the full local quality bar
uv run nox -s lint type test cov

# Run the MCP server over stdio
uv run python -m alphafold_sovereign
```

The first `uv sync` pins all transitive dependencies to hashes in
`uv.lock`. Reproducible to the byte.

## How to Run the Test Pyramid

```bash
uv run nox -s lint          # ruff check + format check
uv run nox -s type          # mypy --strict
uv run nox -s test          # full pytest suite (all supported Pythons)
uv run nox -s cov           # pytest + coverage report (100% gate)
uv run nox -s security      # bandit + safety + pip-audit
uv run nox -s docs          # mkdocs build
uv run nox -s build         # sdist + wheel
uv run nox -s mutate        # mutmut on the shipped surface
uv run nox -s self_test     # alphafold-sovereign --self-test
```

CI runs `lint`, `type`, `test`, `cov`, and `docs` on every PR.

Coverage gate: **100% line and branch** on the shipped surface.

## Commit Message Convention

We use Conventional Commits. Examples:

```
feat(clients): add MONDO disease ontology client
fix(server): retry on upstream 503 with jitter
docs(architecture): describe sovereign-mesh threat model
chore(deps): bump httpx to 0.27.2 (CVE-2026-12345)
refactor(tools): extract feature computation to compute/
perf(topology): swap homegrown Vietoris-Rips for ripser.py (12× faster)
test(integration): add live alphafold round-trip with golden hash
ci(release): sign wheels with Sigstore keyless
security(screening): add HHS Annex IV reference list
```

The first line is ≤ 72 characters. The body explains *why*, not
*what*. Reference issues with `Closes #NNN` or `Refs #NNN`.

## Pull Request Checklist

A reviewer will not start until all of these are true:

- [ ] Branch is up to date with `main`.
- [ ] All commits are signed (`Signed-off-by:` trailer).
- [ ] `nox -s lint type test cov` passes locally.
- [ ] New code has tests at the right layer (see above).
- [ ] Public APIs have docstrings; tools have MCP annotations.
- [ ] If the change affects security, the threat-model section is
      updated.
- [ ] If the change touches biosecurity screening, a bioethics-aware
      reviewer is requested.
- [ ] If the change touches the audit trail (`tool_invocations`
      table, SHA-256 input/output hashing, etc.), the audit
      semantics are documented in the PR description.
- [ ] CHANGELOG.md has a Keep-a-Changelog entry under `## [Unreleased]`.
- [ ] No new tracked secrets, no new outbound endpoints without an
      allowlist entry.

## Review SLAs

| Action | SLA |
|---|---|
| First maintainer triage | 5 business days |
| First review on a non-trivial PR | 10 business days |
| Merge of a P0 security fix | 7 days from disclosure (see SECURITY.md) |
| Cut a release after merge | 30 days max, sooner if blocking |

If we miss an SLA, ping `@maintainers` in the PR — politely. We have
backlog and we appreciate the nudge.

## Style

- **Python**: 3.13+, `ruff` for lint+format, `mypy --strict` for
  types. We use the Google docstring convention.
- **Markdown**: line-wrap at 80 columns where possible.
- **Commits**: see above.
- **Branch names**: lowercase, hyphen-separated, prefix with
  `<user>/` or a recognized prefix like `claude/`, `fix/`, `feat/`,
  `chore/`, `docs/`, `ci/`.

## Becoming a Maintainer

Sustained, high-quality contribution (typically 6 months and ≥ 20
merged PRs, or a single foundational contribution like adding a new
data-source family) earns an invitation to the maintainers' team.
See [`GOVERNANCE.md`](https://github.com/smaniches/alphafold-sovereign-mcp/blob/main/GOVERNANCE.md) for the formal process.

## Asking for help

| Question | Where |
|---|---|
| "How do I do X?" | GitHub Discussions |
| "Is this a bug?" | GitHub Issues |
| "Is this a security issue?" | See [`SECURITY.md`](https://github.com/smaniches/alphafold-sovereign-mcp/blob/main/SECURITY.md) (use GitHub Security Advisories) |

---

Thank you for contributing. Every improvement to this project helps
researchers and engineers who depend on reliable biomedical data
access.
