# Pre-registered benchmark

This directory holds a **pre-registered** evaluation harness for
`alphafold-sovereign-mcp`. "Pre-registered" means the prompt set is
committed to disk and pinned by a SHA-256 in `MANIFEST.txt` **before**
any benchmark run is recorded. Changing the prompts requires a new
manifest entry and breaks the comparability of older runs to newer
ones.

## Why this exists

The scientific outputs of this server (ACMG draft, druggability
heuristic) are not validated by independent experts — see
[`../LIMITATIONS.md`](../LIMITATIONS.md) L1 and L2. The benchmark is
the substrate the validation work in v1.2.0 will use:

1. A domain expert audits the responses to these 10 prompts.
2. Disagreements between expert and server become regression issues.
3. Fixes go in with a unit test pinning the corrected behaviour.
4. The harness re-runs the prompt set; the delta tells us we
   improved without regressing the other 9.

## Files

| File | Purpose |
|---|---|
| `prompts.jsonl` | The 10 pre-registered prompts. One JSON object per line. |
| `MANIFEST.txt` | Pins the SHA-256 of `prompts.jsonl` and the registration metadata. |
| `run.py` | Runs prompts against the server; writes results to `results/<sha>/<ts>.jsonl`. |
| `verify.py` | Diffs two result files prompt-by-prompt; tolerates timestamp drift. |
| `results/` | One subdirectory per pinned prompt SHA, each with one JSONL per run. Gitignored except for a `.gitkeep`. |

## Usage

```bash
# List the prompt IDs
python benchmarks/run.py --list

# Run all 10 prompts in offline mode (no upstream calls)
python benchmarks/run.py --offline

# Run one specific prompt
python benchmarks/run.py --id B04

# Compare two runs
python benchmarks/verify.py \
    benchmarks/results/<sha>/20260511T150000Z.jsonl \
    benchmarks/results/<sha>/20260511T160000Z.jsonl
```

`run.py` will refuse to run if the on-disk `prompts.jsonl` does not
match the SHA pinned in `MANIFEST.txt`. This is the integrity check
that makes the "pre-registered" framing meaningful.

## Status

In v1.1.0-rc1 `run.py` resolves each prompt to a tool function and
records that the tool exists. **Full live invocation through the MCP
transport is on the v1.2.0 roadmap** (it requires a `mcp-inspector`
or equivalent harness — currently writing one is more work than
the rest of this sprint combined).

Until v1.2.0, this harness primarily serves to:

1. Document the prompt set publicly, so reviewers know what we plan
   to evaluate against.
2. Pin the prompts so future evaluations are comparable.
3. Verify that every prompt's `tool` name still resolves to a real
   function (a kind of API-stability test).
