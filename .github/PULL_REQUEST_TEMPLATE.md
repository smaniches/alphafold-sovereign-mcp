<!--
Thanks for contributing. Keep the title in Conventional Commits form
(e.g. "fix(server): ..."), since release-please generates the changelog
and the next version from PR titles. See CONTRIBUTING.md.
-->

## Summary

<!-- What does this PR change, and why? -->

Closes #

## Type of change

- [ ] `fix` / `feat` / `perf` — changes runtime behaviour
- [ ] `docs` / `refactor` / `test` / `chore` / `ci` — no behaviour change

## Checklist

- [ ] Branch is up to date with `main`.
- [ ] Commits are signed off (`git commit -s`; DCO — see `CONTRIBUTING.md`).
- [ ] PR title follows Conventional Commits (the changelog is generated, not hand-edited).
- [ ] `uv run nox -s lint type test cov` passes locally (ruff + mypy --strict + pytest + 100% coverage).
- [ ] New code has tests at the right layer; the 100% line+branch coverage gate still holds.
- [ ] Public APIs have docstrings; new tools have MCP annotations.
- [ ] No new tracked secrets and no new outbound endpoints without an allowlist entry.
- [ ] If the change touches security or the audit trail, the relevant docs are updated.
- [ ] If the change touches biosecurity or dual-use risk (a roadmap area), a bioethics-aware reviewer is requested.
