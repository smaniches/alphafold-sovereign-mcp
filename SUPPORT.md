# Getting Support

## Channels

| Channel | Purpose |
|---|---|
| [GitHub Discussions](https://github.com/smaniches/alphafold-sovereign-mcp/discussions) | Questions, ideas, show-and-tell |
| [GitHub Issues](https://github.com/smaniches/alphafold-sovereign-mcp/issues) | Confirmed bugs, feature requests |

Response time is best-effort.

**Do not use GitHub Issues for security vulnerabilities.** See
[`SECURITY.md`](./SECURITY.md) for the coordinated-disclosure process.

## How to file a good bug report

The faster the project can reproduce a bug, the faster it gets fixed.
Ideal reports include:

1. AlphaFold Sovereign MCP version
   (`python -m alphafold_sovereign --version`).
2. Python version, OS, deployment mode (stdio / HTTP).
3. Minimal configuration (env vars and CLI flags, redacted of
   credentials).
4. The exact tool call that failed (MCP JSON or `mcp-inspector` dump).
5. Full stderr / structured log output.
6. What you expected vs. what happened.
7. Whether it is reproducible, and how often.

Issues without a reproduction take significantly longer to fix and
may be closed as `needs-info` after 14 days of inactivity.
