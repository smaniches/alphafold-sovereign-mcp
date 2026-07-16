# Golden examples

Three end-to-end runs of the variant clinical-report pipeline
(`generate_variant_clinical_report`) against canonical, well-characterised
variants, pinned as regression fixtures and diffed in CI.

| # | Variant | Interpretive class | Pipeline tier | ClinVar |
|---|---------|--------------------|---------------|---------|
| [01](01-brca1-c5266dup/) | **BRCA1** c.5266dupC (`p.Gln1756fs`) | germline loss-of-function founder allele | `HIGH` | Pathogenic (expert panel) |
| [02](02-tp53-r175h/) | **TP53** p.Arg175His (`c.524G>A`) | somatic structural hotspot | `HIGH` | Pathogenic (expert panel) |
| [03](03-egfr-l858r/) | **EGFR** p.Leu858Arg (`c.2573T>G`) | somatic activating driver | `MEDIUM` | Not provided (germline) |

The three span the interpretive space on purpose: a germline null allele whose
call rests on ClinVar plus PVS1 logic; a somatic missense hotspot where ClinVar
and the AlphaMissense predictor agree; and a somatic driver that carries **no
germline pathogenicity assertion at all**, so the pipeline must — and does —
decline to call it germline-pathogenic and fall back to computational evidence.

## What each example contains

```
NN-<variant>/
├── README.md        the scientific write-up: canonical identifiers, the
│                    established classification with cited literature, and a
│                    concordance analysis of pipeline output vs. ground truth
├── cassette.json    every real upstream request/response captured live, each
│                    tagged with its source, method, URL, and a SHA-256 of the
│                    response body
└── expected.json    the pipeline's output, pinned; the only redaction is the
                     provenance version/timestamp (see below)
```

## How the fixtures are made — and why they are trustworthy

The examples are **real, not hand-authored**. `scripts/record_golden_examples.py`
runs each variant through the live public APIs once and records the traffic at
the `BaseAsyncClient._request` boundary — the point *past* the client's retry
loop, so each cassette holds one clean request/response per upstream call, free
of transient `429`/`503` noise. Every recorded response carries a SHA-256 of its
body for provenance.

The golden test (`tests/golden/test_golden_examples.py`) replays those recorded
responses through `respx` at the same transport layer, entirely offline, and
asserts the pipeline reproduces `expected.json` byte-for-byte. Nothing about the
answer is written by hand: the inputs are real upstream payloads, and the
expected output is whatever the real pipeline computes from them. The test is
deterministic across Python hash seeds and needs no network.

Only two fields are volatile and are redacted before the diff: the package
**version** and the UTC **timestamp** embedded in the provenance footer. Every
scientific field — the ClinVar classification, the AlphaMissense score, the
tier, the ACMG criteria, the disease associations — must match exactly, or CI
fails.

To regenerate (intentionally, with network access):

```bash
uv run python scripts/record_golden_examples.py
```

A diff in `expected.json` after re-recording is a **fact to review** — an
upstream reclassification, a new AlphaFold model version, a pipeline change —
never something to rubber-stamp.

## What these examples do and do not establish

This matters, so it is stated plainly.

**They do** establish that the pipeline runs end-to-end across all its
upstreams on canonical inputs; that its output on those inputs is fixed and any
future drift is caught in CI; and that a reader can see exactly what the tool
concludes on three textbook variants, with the reasoning traceable to real
source data.

**They do not** constitute independent scientific validation of the pipeline's
heuristics. The druggability tier and the ACMG criterion mapping remain
un-benchmarked and un-reviewed by domain experts (see
[`STATUS.md`](../../STATUS.md) and [`LIMITATIONS.md`](../../LIMITATIONS.md)).
A golden example pins *what the tool says*; the per-example concordance analysis
compares that against the *established literature* and flags any divergence. The
two are kept strictly separate: the pipeline's output is a computation over
public data, and the ground truth is the peer-reviewed record — never conflated.

### One divergence, surfaced and fixed

Building these examples exercised the pipeline on BRCA1 c.5266dupC and exposed a
real defect: the ClinVar resolver ranked candidate records by a substring match
that a legacy HGVS spelling (`c.5266dupC` vs. ClinVar's canonical `c.5266dup`)
defeated, so it returned an unrelated single-submitter VUS and labelled a
canonical pathogenic founder allele "Uncertain significance." That is exactly
the kind of error a golden example is meant to catch. It was fixed
(`fix(clinvar): resolve the exact variant record, not an arbitrary search hit`)
before these fixtures were recorded, which is why example 01 correctly resolves
to the expert-panel Pathogenic record.
