# AlphaFold Sovereign MCP

[![CI](https://github.com/smaniches/alphafold-sovereign-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/smaniches/alphafold-sovereign-mcp/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://github.com/smaniches/alphafold-sovereign-mcp/blob/main/LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://github.com/smaniches/alphafold-sovereign-mcp/blob/main/pyproject.toml)
[![MCP Spec 2025-06-18](https://img.shields.io/badge/MCP-2025--06--18-purple)](https://modelcontextprotocol.io)
[![Tests](https://img.shields.io/badge/tests-730%20passing-success)](https://github.com/smaniches/alphafold-sovereign-mcp/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen)](https://github.com/smaniches/alphafold-sovereign-mcp/actions/workflows/ci.yml)

> **v1.2.0** (Beta). Engineering-validated
> (730 tests, 100% line and branch coverage).
> Scientifically unvalidated by independent domain experts;
> not yet deployed in production. See
> [Status](status.md) and [Limitations](limitations.md).

A Model Context Protocol server that wraps **AlphaFold DB** and 8
other public biomedical data sources behind a set of MCP tool calls,
backed by a local SQLite knowledge graph with query and export tools.
Results can be persisted to the graph through its API; automatic
per-invocation persistence is not yet wired.

## What it does

- Wraps AlphaFold DB, MONDO, HPO, Open Targets, ClinVar, gnomAD,
  DisGeNET, ChEMBL, and Ensembl behind MCP tool calls.
- Composes upstreams into multi-source workflows — variant triage
  reports, disease–target landscape summaries, drug-repurposing
  candidates, cross-species structural divergence.
- Ships a local SQLite knowledge graph with query and export tools.
  Results can be persisted through its API; automatic per-invocation
  persistence is not yet wired, so the graph is populated only when a
  caller writes to it explicitly.

See [Tool reference](tools/index.md) for the full inventory.

## What it is **not**

- It is **not** a hosted service.
- It is **not** certified for any regulated use.
- The ACMG/AMP criteria emitted by the variant tools are a **draft
  surface** of upstream evidence — not a clinical interpretation.
- The druggability tier returned by the target-assessment tool is a
  **heuristic** — not a validated prediction.

See [Limitations](limitations.md) for the itemised gap list.

## Quick start

```bash
git clone https://github.com/smaniches/alphafold-sovereign-mcp
cd alphafold-sovereign-mcp
uv pip install -e .
alphafold-sovereign --self-test      # PASS on the offline BRCA1 fixture
```

Configure Claude Desktop and the tools become available in
conversations. Full instructions: [Installation](installation.md).

## Examples

- [Variant triage on BRCA1 c.5266dupC](examples/01-variant-triage.md)
- [Target characterisation on EGFR](examples/02-target-characterization.md)
- [Drug-discovery walk-through: Imatinib → BCR-ABL → CML](examples/03-drug-discovery.md)

## Cite

Machine-readable metadata in
[`CITATION.cff`](https://github.com/smaniches/alphafold-sovereign-mcp/blob/main/CITATION.cff).
GitHub renders a "Cite this repository" button in the sidebar of the
repo that consumes this file.
