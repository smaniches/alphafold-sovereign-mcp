# Examples

Three end-to-end illustrations of what an MCP session against
`alphafold-sovereign-mcp` looks like.

| Example | Tools exercised | What it shows |
|---|---|---|
| [`01-variant-triage/`](01-variant-triage/) | `generate_variant_clinical_report`, `classify_variant_acmg` | Pulling Ensembl VEP + ClinVar + gnomAD + AlphaMissense + AlphaFold structural context for **BRCA1 c.5266dupC**; draft ACMG/AMP evidence. |
| [`02-target-characterization/`](02-target-characterization/) | `assess_target_druggability`, `fetch_alphafold_structure` | Characterising **EGFR** as a drug target: Open Targets, ChEMBL, gnomAD constraint, AlphaFold pLDDT. |
| [`03-drug-discovery/`](03-drug-discovery/) | `drug_lookup`, `assess_target_druggability`, `explore_disease_target_landscape`, `fetch_alphafold_structure` | Multi-turn flow: **Imatinib → BCR-ABL → CML**. The molecular story behind a TKI, plus the T315I resistance gatekeeper. |

## ⚠ Status of these examples

These are **illustrative**. The transcripts (`transcript.jsonl`) and
the prose responses are consistent with what the server emits when
its upstream clients return data we have unit tests for — but the
specific numbers (gnomAD AFs, association scores, drug lists) have
not been verified against a live API call for this exact target.

Why we publish them anyway: they (1) document the **shape** of a
real session, (2) let a reviewer audit our tool contracts before
running anything, and (3) form the basis of regression tests under
[`benchmarks/`](../benchmarks/).

**End-to-end live-API validation** is on the v1.2.0 roadmap — see
[`STATUS.md`](../STATUS.md) §"Roadmap to v1.2.0", step 1 (golden
examples). When that lands, this directory becomes the set of
captured-and-replayed transcripts.

## Reproducing locally

```bash
# 1. Install from source
git clone https://github.com/smaniches/alphafold-sovereign-mcp
cd alphafold-sovereign-mcp
uv pip install -e .

# 2. Verify the install
alphafold-sovereign --version       # → 1.1.4
alphafold-sovereign --self-test     # → PASS on the deterministic BRCA1 fixture

# 3. Configure Claude Desktop
#    Add to claude_desktop_config.json:
#      "mcpServers": { "alphafold-sovereign": { "command": "alphafold-sovereign-mcp" } }
#    Restart Claude Desktop.

# 4. In a Claude Desktop conversation, paste the user prompt from any of
#    the three README.md files in this directory.
```
