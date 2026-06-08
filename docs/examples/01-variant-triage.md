# Example: Variant Triage — BRCA1 c.5266dupC

> **Status: Illustrative.** This transcript shows the shape of a real
> Claude Desktop session against `alphafold-sovereign-mcp` for a
> well-characterised pathogenic BRCA1 variant. Output fields are
> consistent with what the server's `generate_variant_clinical_report`
> tool emits when its upstream clients (Ensembl VEP, AlphaMissense,
> ClinVar, gnomAD, Open Targets, UniProt) return data we have unit
> tests for. End-to-end validation against the live upstreams is on
> the v1.2.0 roadmap (see [`STATUS.md`](../status.md)) — until then,
> treat the numbers below as schematic, not as a clinical reference.

## Setup

```jsonc
// claude_desktop_config.json
{
  "mcpServers": {
    "alphafold-sovereign": {
      "command": "alphafold-sovereign-mcp",
      "args": []
    }
  }
}
```

After installing from source (see top-level README) and restarting
Claude Desktop, the server's tools become available in the conversation.

## User prompt

> Triage the BRCA1 c.5266dupC variant for me. Tell me whether it's
> pathogenic, what the gnomAD frequency is, the AlphaMissense score,
> the ClinVar status, and the predicted protein consequence.

## What the model calls

```jsonc
// MCP tool call
{
  "tool": "generate_variant_clinical_report",
  "params": {
    "hgvs": "BRCA1:c.5266dupC",
    "include_population_breakdown": true,
    "include_drug_context": true
  }
}
```

## What the server returns (illustrative — field names abridged for readability)

```jsonc
{
  "input": {
    "hgvs": "BRCA1:c.5266dupC",
    "transcript": "NM_007294.4"
  },
  "ensembl_vep": {
    "predicted_consequence": "frameshift_variant",
    "impact": "HIGH",
    "canonical_transcript": "ENST00000357654",
    "protein_consequence": "p.Gln1756ProfsTer74",
    "exon": "20/23"
  },
  "alphamissense": {
    "score": null,
    "note": "AlphaMissense scores apply to missense variants only; this is a frameshift."
  },
  "clinvar": {
    "variation_id": "17661",
    "clinical_significance": "Pathogenic",
    "review_status": "criteria provided, multiple submitters, no conflicts",
    "last_evaluated": "2024-08-21",
    "n_submissions": 31,
    "conditions": [
      {"name": "Hereditary breast and ovarian cancer syndrome", "id": "MONDO:0019303"},
      {"name": "Familial cancer of breast", "id": "MONDO:0017180"}
    ]
  },
  "gnomad": {
    "allele_frequency": 0.0000142,
    "allele_count": 4,
    "allele_number": 281618,
    "homozygotes": 0,
    "filter": "PASS",
    "popmax_population": "nfe",
    "popmax_af": 0.0000301
  },
  "alphafold": {
    "uniprot_id": "P38398",
    "model_url": "https://alphafold.ebi.ac.uk/files/AF-P38398-F1-model_v6.pdb",
    "residue": 1756,
    "plddt_at_residue": 38.4,
    "plddt_note": "Low pLDDT (<50) — residue lies in a disordered region; structural inference unreliable.",
    "pae_neighbourhood_p95_residues_within_8A": [1750, 1751, 1752, 1755, 1757, 1758, 1761]
  },
  "acmg_criteria_draft": {
    "PVS1": "applied",
    "PS1": "not applied",
    "PM2_supporting": "applied (gnomAD AF < 0.0001)",
    "PP5": "not applied (deprecated)",
    "draft_classification": "Pathogenic",
    "draft_classification_note": "Auto-derived ACMG/AMP criteria draft. NOT independently validated by a clinical geneticist. See LIMITATIONS.md L1."
  },
  "sources_cited": [
    "Ensembl VEP REST",
    "ClinVar VCV00017661",
    "gnomAD v4.1.0",
    "AlphaFold DB v6 (P38398)"
  ],
  "report_generated_at": "2026-05-11T14:23:47Z"
}
```

## What Claude says back (paraphrased)

> **BRCA1 c.5266dupC** is a well-known pathogenic frameshift variant.
> Here is the triage summary:
>
> - **Predicted effect**: frameshift at codon 1756 (`p.Gln1756ProfsTer74`),
>   high-impact.
> - **ClinVar**: classified `Pathogenic` (Variation ID 17661), with 31
>   submissions and no conflicts (last reviewed August 2024).
> - **gnomAD v4.1.0**: extremely rare (allele frequency 1.42×10⁻⁵
>   globally; popmax 3.0×10⁻⁵ in non-Finnish European). No homozygotes.
> - **AlphaMissense**: not applicable — the variant is a frameshift, not
>   a missense.
> - **AlphaFold structural context**: residue 1756 of BRCA1 (P38398)
>   sits in a low-confidence region (pLDDT 38.4 of 100). Structural
>   inference there is unreliable, which is expected — the C-terminal
>   region is partly disordered. The variant truncates the BRCT domain.
> - **Auto-derived ACMG**: `PVS1 + PM2_supporting → Pathogenic` —
>   consistent with the ClinVar consensus.
> - **Disclaimer**: The ACMG draft surfaced by this server has not
>   been validated by an independent clinical geneticist. For clinical
>   reporting, re-derive each criterion from the cited primary sources.

## What the same call looks like in `--self-test` mode

`alphafold-sovereign --self-test` runs an offline, deterministic
subset of this flow against a built-in `BRCA1:c.5266dupC` fixture
that does not require live network access. It exercises only the
pure functions of the server (HGVS parsing, ACMG criterion mapping,
report assembly), and prints `PASS` if the report shape and the
deterministic ACMG draft match the golden file.

## Reproducing this example for real

1. Install: see top-level [`README.md`](../installation.md).
2. Configure Claude Desktop as shown above.
3. Restart Claude Desktop.
4. Paste the user prompt at the top of this document.

## Files

- `transcript.jsonl` — machine-readable MCP exchange (one line per
  request / response / tool call / tool result).
- `expected_output_schema.json` — JSON Schema for the report shape so
  regressions are catchable in CI.
