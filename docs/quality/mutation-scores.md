# Mutation testing

[Mutation testing](https://en.wikipedia.org/wiki/Mutation_testing) is a
complement to line/branch coverage. Line/branch coverage tells you
**which** lines and branches your tests touched. Mutation testing
tells you whether your tests would have **caught** a bug introduced
into those lines.

A mutation that the test suite catches is "killed". A mutation that
survives the test suite is a soft spot — either the line is dead, or
the test only exercises it without asserting on its behaviour.

## Tooling

[`mutmut`](https://github.com/boxed/mutmut) is configured at
[`mutmut_config.py`](https://github.com/smaniches/alphafold-sovereign-mcp/blob/main/mutmut_config.py).
Targets `src/alphafold_sovereign/` excluding `__init__.py`, `__main__.py`,
the archived monolith, and SPDX/copyright header lines.

Run:

```bash
nox -s mutate -- --runs 50      # bounded
nox -s mutate                   # full
```

## Status

In v1.1.0-rc1 we publish the **infrastructure** (config + nox session +
this page) but **not** a measured score. A full mutmut run against
~3,000 statements with 613 tests on a single laptop takes ~30 minutes
and we have not yet integrated those runs into CI on a schedule
(mutation testing is not cheap enough to run on every PR).

The plan is:

1. **v1.2.0**: first published score from a single full run. We will
   record per-module scores in a table on this page.
2. **v1.2.0+**: weekly mutation run in CI; published score badge.

## Per-module scores

| Module | Mutants | Killed | Survived | Score | Last run |
|---|---|---|---|---|---|
| `clients/` | — | — | — | — | — |
| `domain/` | — | — | — | — | — |
| `tools/` | — | — | — | — | — |
| `storage/` | — | — | — | — | — |
| `server/` | — | — | — | — | — |
| **Total** | — | — | — | — | — |

This table will be filled in v1.2.0 with the first measured run.

## How to interpret a low score

A module with line/branch coverage at 100% but a mutation score below
~80% has tests that **execute** every line but don't **assert** on
the behaviour. For this codebase, the highest-risk areas are:

- The ACMG criterion mapping helpers in `tools/precision_medicine.py`
  (the helpers are simple lookups but the cut-offs are the
  scientifically meaningful part — see
  [`LIMITATIONS.md`](../limitations.md) L1).
- The druggability tier scoring in
  `tools/precision_medicine.py::_druggability_tier`
  (see [`LIMITATIONS.md`](../limitations.md) L2).

A mutation that survives in these helpers is a flag to add an assertion
on the boundary, not just on the happy path.
