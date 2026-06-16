# Project Governance

## Philosophy

AlphaFold Sovereign MCP is a **BDFL-with-council** project. The
Benevolent Dictator for Life (BDFL) is the founding author; a small
Technical Steering Committee (TSC) shares decision-making for
significant changes. All decisions are made in the open.

## Roles

### Users

Everyone who uses the software. No formal membership required.
Users are encouraged to open issues, ask questions in Discussions,
and vote on roadmap items with thumbs-up reactions.

### Contributors

Anyone with a merged pull request; contributors appear in the project's
Git history and on the GitHub contributors page. Eligible for promotion
to Committer after sustained contribution.

### Committers

Committers have write access to non-protected branches and can merge
PRs that have been approved by at least one other Committer or TSC
member. Added by TSC vote (simple majority). Removed by TSC vote
(two-thirds majority) or by voluntary resignation.

Current committers are listed in `CODEOWNERS`.

### Technical Steering Committee (TSC)

| Name | Affiliation | Focus |
|---|---|---|
| Santiago Maniches | independent | Founding author |
| *(open seat)* | — | Seeking: structural-biology background |
| *(open seat)* | — | Seeking: clinical-genomics background |
| *(open seat)* | — | Seeking: community / governance |

TSC meets monthly (async via GitHub Discussions). Once the TSC is
active, minutes will be published under `docs/governance/`.

### BDFL

Santiago Maniches holds BDFL status and has tie-breaking authority.
This authority will transfer to TSC supermajority once the TSC reaches
5 members, anticipated at project maturity.

## Decision-Making

| Decision type | Process |
|---|---|
| Bug fix, docs, small feature | Committer approval + 48 h review window |
| Significant feature, new API surface | TSC lazy consensus (7-day window) |
| Breaking change, major architecture | TSC explicit vote (2/3 majority) |
| License change | BDFL + TSC unanimous vote + 30-day community notice |
| Security policy change | BDFL + security-aware TSC member |

**Lazy consensus**: a proposal is accepted if no TSC member objects
within the review window. An objection must include a concrete
counter-proposal.

## Conflict Resolution

1. Discuss in the relevant issue or PR.
2. Escalate to the TSC mailing list (`tsc@topologica.ai`).
3. TSC votes. BDFL breaks ties.
4. Decisions are final and, once the TSC is active, recorded under
   `docs/governance/decisions/`.

## Becoming a Committer

Criteria (any combination totaling ≥ 10 "points"):

- 1 point per merged non-trivial PR
- 3 points per merged PR that adds a new client, tool family, or
  compliance module
- 5 points for a foundational contribution (new transport, CI/CD
  overhaul, SBOM pipeline, etc.)
- Discretionary TSC nomination (max 5 points, for exceptional quality)

A Committer nomination is a GitHub Discussion in the `governance`
category, open for 7 days, then closed by TSC vote.

## Biosecurity Governance Annex

Sequence-of-concern screening is a roadmap item: no screening tooling
ships today, and the Biosecurity Advisory Board (BAB) is not yet
constituted. When screening is implemented, a **Biosecurity Advisory
Board (BAB)** of at least two subject-matter experts (biology, policy,
or ethics), external to TOPOLOGICA LLC, will review:

- Any change to the sequence-of-concern screening module
- Any change to the dual-use risk classification framework
- Any new biothreat-analysis tools

The BAB roster will be published under `docs/governance/` once the
board is constituted.

## Project Health Commitments

- Security patches released within SLA in `SECURITY.md`.
- No unaddressed P0 bugs older than 7 days.
- Quarterly roadmap review published in the Roadmap section of `STATUS.md`.
- Annual dependency and supply-chain audit published in `AUDIT.md`.
