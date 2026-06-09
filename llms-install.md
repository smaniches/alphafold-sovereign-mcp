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

- `ALPHAFOLD_OFFLINE` — set to `1`, `true`, or `yes` to serve only from the
  local cache and refuse all outbound HTTP calls.
- `ALPHAFOLD_ALLOW_HOSTS` — comma-separated allowlist of upstream hostnames the
  server may contact.

## Verifying the install

```
uvx alphafold-sovereign-mcp --self-test
```
