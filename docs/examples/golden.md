# Golden examples (CI-diffed)

Three end-to-end runs of the variant clinical-report pipeline
(`generate_variant_clinical_report`) against canonical variants, pinned as
regression fixtures and diffed in CI. Unlike the illustrative transcripts, these
are **executed and asserted** on every run.

| # | Variant | Interpretive class | Pipeline tier | ClinVar |
|---|---------|--------------------|---------------|---------|
| 01 | **BRCA1** c.5266dupC (`p.Gln1756fs`) | germline loss-of-function founder allele | `HIGH` | Pathogenic (expert panel) |
| 02 | **TP53** p.Arg175His (`c.524G>A`) | somatic structural hotspot | `HIGH` | Pathogenic (expert panel) |
| 03 | **EGFR** p.Leu858Arg (`c.2573T>G`) | somatic activating driver | `MEDIUM` | Not provided (germline) |

Full write-ups — canonical identifiers, established classification with cited
primary literature, and a point-by-point concordance analysis of pipeline output
vs. ground truth — live with each example under
[`examples/golden/`](https://github.com/smaniches/alphafold-sovereign-mcp/tree/main/examples/golden).

## How they work

`scripts/record_golden_examples.py` runs each variant through the live public
APIs once and records the traffic at the client's `_request` boundary (past the
retry loop, so one clean request/response per call), each response tagged with a
SHA-256 of its body. The golden test (`tests/golden/test_golden_examples.py`)
replays those recorded responses through `respx`, entirely offline, and asserts
the pipeline reproduces the committed `expected.json`. The only redacted fields
are the provenance version and timestamp; every scientific field must match
exactly or CI fails. The test is deterministic across Python hash seeds.

## What they establish — and what they do not

They pin pipeline behaviour on canonical inputs and give worked, source-traceable
examples; a future drift in any scientific field is caught in CI. They are a
**regression and traceability artifact, not independent scientific validation**
of the druggability or ACMG heuristics — that remains
[roadmap](../status.md) items 3–4 (external review; benchmark calibration). Each
example keeps a strict line between *what the pipeline computes* (over public
data) and *the established literature*, and flags any divergence.

The three span the interpretive space deliberately. Example 03 (EGFR L858R) is
the sharpest: ClinVar carries no germline *pathogenicity* assertion for it (its
significance is somatic/therapeutic — Tier I, TKI-sensitizing), so the pipeline
correctly declines a germline-pathogenic call and lands at `MEDIUM` on
computational evidence alone. Example 01 (BRCA1) is also what surfaced and
motivated the ClinVar exact-record resolution fix.
