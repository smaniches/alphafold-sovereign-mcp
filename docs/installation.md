# Installation

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

```bash
alphafold-sovereign --version       # → 1.1.10
alphafold-sovereign --self-test     # → SELF-TEST PASS
```

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

Set `ALPHAFOLD_OFFLINE=1` to refuse all outbound HTTP and serve only
from the local SQLite cache:

```bash
ALPHAFOLD_OFFLINE=1 alphafold-sovereign-mcp
```
