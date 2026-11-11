# Installation

**Supported runtime:** Python 3.11 or newer (CI-verified on 3.11–3.13).
Python 3.10 reached upstream end of life on 1 October 2026 and is no longer
supported. The distribution requires the patched DNS dependency
`dnspython>=2.9.0`. The optional docs extra requires `pillow>=13.0.0`.

## Quick install (PyPI)

`alphafold-sovereign-mcp` is published on PyPI:

```bash
pip install alphafold-sovereign-mcp
```

Or run without installing using `uvx`:

```bash
uvx alphafold-sovereign-mcp
```

A signed wheel and sdist are attached to every GitHub Release with
SLSA L3 build provenance and Sigstore (`cosign`) signatures.  Verify
the supply chain with `scripts/replicate.sh`.

## Install from source

```bash
git clone https://github.com/smaniches/alphafold-sovereign-mcp
cd alphafold-sovereign-mcp
uv pip install -e .
```

With persistent-homology TDA (requires `gudhi`):

```bash
uv pip install -e ".[tda]"
```

## Verify the install

<!-- x-release-please-start-version -->
```bash
alphafold-sovereign --version       # → 1.5.12
alphafold-sovereign --self-test     # → SELF-TEST PASS
```
<!-- x-release-please-end-version -->

`--self-test` boots the server in offline mode and exercises the
deterministic logic of the ACMG helpers against a built-in BRCA1
c.5266dupC fixture. It does **not** make any network calls. Returns
exit code 0 on PASS, non-zero on FAIL.

## Configure Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "alphafold-sovereign": {
      "command": "alphafold-sovereign-mcp",
      "args": []
    }
  }
}
```

Restart Claude Desktop and the tools become available in
conversations. See [Examples](examples/index.md) for what a session
looks like.

## Offline / air-gap mode

Set `ALPHAFOLD_OFFLINE=1` to refuse all outbound HTTP. The
knowledge-graph tools still answer from the local SQLite store. Tools
that query an upstream service have no local cache. Depending on the
tool, the call fails with an error or returns a result that reports the
affected lookups as failed or not assessed.

The structure tools do not all report a blocked AlphaFold DB request the
same way:

- `get_protein_structure`, `analyze_structural_confidence`,
  `compute_topology_fingerprint`, `score_binding_pocket_geometry` and
  `detect_intrinsically_disordered` return
  `retrieval_status: "request_failed"`, which is not a statement that no
  model exists.
- `compare_proteins_topologically` returns no `retrieval_status`. It
  lists each accession under `proteins_failed`, with the reason the
  request failed.
- `find_evolutionary_structural_shifts` queries Ensembl first, and the
  call fails with an error when that request is blocked. If Ensembl is
  allowlisted in `ALPHAFOLD_ALLOW_HOSTS` and AlphaFold DB is not, it
  returns sequence identity only and does not say that the AlphaFold DB
  request was blocked.

```bash
ALPHAFOLD_OFFLINE=1 alphafold-sovereign-mcp
```
