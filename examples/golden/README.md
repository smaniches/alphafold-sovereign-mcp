# Golden source-replay fixtures

The three fixtures test repeatability of multi-source variant evidence
retrieval. They are **not** clinical case reports or independent scientific
validation.

| Fixture | Input | MCP classification |
|---|---|---|
| [BRCA1](01-brca1-c5266dup/) | `BRCA1:c.5266dupC` | `NOT_ASSESSED` |
| [TP53](02-tp53-r175h/) | `TP53:p.Arg175His` | `NOT_ASSESSED` |
| [EGFR](03-egfr-l858r/) | `EGFR:p.Leu858Arg` | `NOT_ASSESSED` |

Each fixture contains:

- `cassette.json`: point-in-time upstream HTTP responses, with per-response
  hashes and source metadata.
- `expected.json`: the output that the recorded responses produce.
- `README.md`: a compact test contract, without an independent clinical
  mechanism or therapeutic interpretation.

`tests/golden/test_golden_examples.py` replays the cassettes locally and
compares the outputs. A passing test demonstrates behavioral reproducibility,
not the truth of upstream claims or clinical validity.

To update the recordings after independent review of external changes:
`uv run python scripts/record_golden_examples.py`. Do not blindly accept
upstream reclassifications or generated fixtures.
