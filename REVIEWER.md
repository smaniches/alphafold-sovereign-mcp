# Reviewer Guide

This document helps a cold reviewer verify the project's claims in
under 30 minutes. It assumes a Unix-like environment with Python 3.10+
and `uv` installed.

---

## 1. Clone and install

```bash
git clone https://github.com/smaniches/alphafold-sovereign-mcp
cd alphafold-sovereign-mcp
uv sync --extra dev
```

## 2. Run the self-test

```bash
uv run alphafold-sovereign --self-test
```

Boots the server in offline mode, exercises the deterministic ACMG
logic against a built-in BRCA1 fixture, and exits with code 0 on
PASS. No network calls.

## 3. Run the offline test suite

```bash
uv run pytest tests/ -q --tb=short
```

All tests use `respx` to mock HTTP upstreams. No network access
required. Verify the test count matches the claim in `README.md`.

## 4. Verify coverage

```bash
uv run nox -s cov
```

Runs pytest with `--cov-fail-under=100`. The session fails if any
shipped module drops below 100% line and branch coverage.

## 5. Run static analysis

```bash
uv run nox -s lint      # ruff check + format
uv run nox -s type      # mypy --strict
```

## 6. Run security scanning

```bash
uv run nox -s security  # bandit + safety + pip-audit
```

## 7. Inspect examples

The `examples/` directory contains three end-to-end transcripts:

- `01-variant-triage/` — BRCA1 c.5266dupC variant report
- `02-target-characterization/` — EGFR target dossier
- `03-drug-discovery/` — Imatinib drug-repurposing walk-through

Each includes a `transcript.jsonl` with the tool calls and responses
the model issued against the server. The transcripts are
documentation of what a session looks like, not automated tests.

## 8. Verify release provenance

For any tagged release, the GitHub Release page should contain:

- Wheel (`.whl`) and sdist (`.tar.gz`)
- SLSA L3 build provenance attestation (`.intoto.jsonl`)
- Sigstore signatures (`.sigstore` / `.sig` / `.crt`)
- CycloneDX and SPDX SBOMs

To verify the supply chain locally:

```bash
bash scripts/replicate.sh
```

This rebuilds the wheel from the tagged source and compares it to
the published artifact.

## 9. Check version consistency

All of the following should report the same version:

```bash
grep '^version' pyproject.toml
grep '__version__' src/alphafold_sovereign/__init__.py
grep '"version"' server.json
grep '"version"' .well-known/mcp.json
grep '^version:' smithery.yaml
grep '^version:' CITATION.cff
```

## 10. Understand what is NOT validated

Read these files in order:

1. [`STATUS.md`](STATUS.md) — validation matrix and project posture
2. [`LIMITATIONS.md`](LIMITATIONS.md) — itemised gap list (L1–L7)
3. [`AUDIT.md`](AUDIT.md) — what has and has not been externally audited

Key distinction: the test suite validates *engineering correctness*
(code does what the code says it does). It does not validate
*scientific correctness* (the ACMG mapping matches expert consensus)
or *clinical utility* (the outputs are useful in practice). Both
remain open.

---

Last updated: 2026-05-26.
