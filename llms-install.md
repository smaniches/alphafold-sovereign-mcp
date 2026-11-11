# Installing alphafold-sovereign-mcp

This is an MCP server distributed on PyPI as `alphafold-sovereign-mcp`. It runs
with [`uvx`](https://docs.astral.sh/uv/), which fetches and launches the server
in an isolated environment.

## One-line install and run

```
uvx alphafold-sovereign-mcp
```

## MCP client configuration

Add the following entry to your MCP client configuration (for example,
`mcpServers` in the client's JSON config):

```json
{
  "mcpServers": {
    "alphafold": {
      "command": "uvx",
      "args": ["alphafold-sovereign-mcp"]
    }
  }
}
```

## Environment variables

No environment variables are required; the configuration above launches the
server with sensible defaults. The following variables are optional:

- `ALPHAFOLD_OFFLINE` — set to `1`, `true`, or `yes` to refuse all outbound
  HTTP calls. The knowledge-graph tools still answer from the local SQLite
  store. Tools that query an upstream service have no local cache.
  Depending on the tool, the call fails with an error or returns a result
  that reports the affected lookups as failed or not assessed. Of the
  structure tools, `get_protein_structure`,
  `analyze_structural_confidence`, `compute_topology_fingerprint`,
  `score_binding_pocket_geometry` and `detect_intrinsically_disordered`
  report the blocked AlphaFold DB request as
  `retrieval_status: "request_failed"`, which is not a statement that no
  model exists. `compare_proteins_topologically` lists each accession
  under `proteins_failed` with the reason instead.
  `find_evolutionary_structural_shifts` queries Ensembl first and fails
  with an error when that request is blocked; with Ensembl allowlisted
  but not AlphaFold DB, it returns sequence identity only and does not
  say that the AlphaFold DB request was blocked.
- `ALPHAFOLD_ALLOW_HOSTS` — comma-separated allowlist of upstream hostnames the
  server may contact.

## Verifying the install

```
uvx alphafold-sovereign-mcp --self-test
```
