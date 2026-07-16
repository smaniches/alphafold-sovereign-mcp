# Examples

Three end-to-end illustrations of what an MCP session against
`alphafold-sovereign-mcp` looks like.

| Example | Tools exercised | What it shows |
|---|---|---|
| [`01-variant-triage/`](01-variant-triage/) | `generate_variant_clinical_report`, `classify_variant_acmg` | Pulling Ensembl VEP + ClinVar + gnomAD + AlphaMissense + AlphaFold structural context for **BRCA1 c.181T>G**; draft ACMG/AMP evidence. |
| [`02-target-characterization/`](02-target-characterization/) | `assess_target_druggability` | Characterising **EGFR** as a drug target: Open Targets, ChEMBL, gnomAD constraint, AlphaFold pLDDT (fetched automatically as the structural-confidence component of the druggability score). |
| [`03-drug-discovery/`](03-drug-discovery/) | `map_disease_drug_landscape`, `assess_target_druggability`, `analyze_structural_confidence` | Multi-turn flow: **Imatinib → BCR-ABL → CML**. The molecular story behind a TKI, plus the T315I resistance gatekeeper. |

## Status of these examples

These transcripts were **captured live** against the upstream APIs on
2026-06-08; each example's `README.md` records the exact run and the
full payload is in its `transcript.jsonl`. The READMEs abridge long
arrays for readability, so cross-check a specific number against the
corresponding `transcript.jsonl` line rather than the prose.

The transcripts here are point-in-time captures, not regression-gated
fixtures. The **CI-diffed golden examples** live separately under
[`golden/`](golden/): the full variant clinical-report pipeline run
against three canonical variants (BRCA1 c.5266dupC, TP53 R175H, EGFR
L858R) on real upstream responses recorded once with SHA-256 provenance,
replayed offline and asserted against a pinned `expected.json` in CI.
Each carries a scientific concordance analysis against the cited
literature. See [`golden/README.md`](golden/README.md).

## Reproducing locally

```bash
# 1. Install from source
git clone https://github.com/smaniches/alphafold-sovereign-mcp
cd alphafold-sovereign-mcp
uv pip install -e .

# 2. Verify the install
alphafold-sovereign --version       # → 1.2.2
alphafold-sovereign --self-test     # → PASS on the deterministic BRCA1 fixture

# 3. Configure Claude Desktop
#    Add to claude_desktop_config.json:
#      "mcpServers": { "alphafold-sovereign": { "command": "alphafold-sovereign-mcp" } }
#    Restart Claude Desktop.

# 4. In a Claude Desktop conversation, paste the user prompt from any of
#    the three README.md files in this directory.
```
