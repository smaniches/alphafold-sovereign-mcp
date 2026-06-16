# Example: Variant Triage — BRCA1 c.181T>G (p.Cys61Gly)

> **Status: Captured live.** The response below was captured from a real
> run against the live Ensembl VEP, ClinVar, gnomAD, AlphaMissense, Open
> Targets, and AlphaFold DB APIs on **2026-06-08** (arrays abridged for
> readability; full payload in
> [`transcript.jsonl`](https://github.com/smaniches/alphafold-sovereign-mcp/blob/main/examples/01-variant-triage/transcript.jsonl)).
> See [`STATUS.md`](../status.md) for what "verified" covers.

## User prompt

> I have a BRCA1 variant, c.181T>G. Is it clinically significant, and what
> is the supporting evidence?

## What the model calls

```jsonc
{"tool": "generate_variant_clinical_report", "params": {"hgvs": "BRCA1:c.181T>G"}}
```

## What the server returns (captured live; abridged)

```jsonc
{
  "hgvs": "BRCA1:c.181T>G",
  "gene_symbol": "BRCA1",
  "clinical_tier": "HIGH",
  "clinical_tier_explanation": "Strong evidence of clinical pathogenicity from a ClinVar pathogenic classification (see review_status for the supporting review level) and/or multiple concordant computational predictors.",
  "functional_consequence": {
    "consequence_terms": ["missense_variant"], "impact": "MODERATE",
    "amino_acids": "C/G", "sift_prediction": "deleterious", "sift_score": 0.0,
    "polyphen_prediction": "benign", "polyphen_score": 0.027
  },
  "clinvar": {"found": true, "classification": "Pathogenic", "acmg_code": "P", "review_status": "reviewed by expert panel", "variation_id": "17661"},
  "population_genetics": {"global_af": null, "alphamissense_score": 0.9904, "populations": []},
  "gene_constraint": {"pLI": 0.0, "loeuf": 0.928, "mis_z": 1.73, "interpretation": "Tolerant to loss-of-function (LOEUF=0.928): LoF variants are tolerated in the population."},
  "acmg_criteria_draft": {
    "criteria": {
      "PP3": "AlphaMissense=0.990 — likely pathogenic (≥0.564)",
      "PP5": "ClinVar: Pathogenic (reviewed by expert panel). Reputable source with strong concordance."
    },
    "note": "Draft ACMG/AMP criteria based on computational and population evidence. Professional review by a clinical geneticist is required before clinical reporting."
  },
  "disease_associations": {"open_targets_top_diseases": [
    {"disease_mondo_id": "MONDO:0007254", "disease_name": "breast cancer", "overall_score": 0.839},
    {"disease_mondo_id": "Orphanet:145", "disease_name": "Hereditary breast and ovarian cancer syndrome", "overall_score": 0.828},
    {"disease_mondo_id": "MONDO:0054748", "disease_name": "Fanconi anemia, complementation group S", "overall_score": 0.821}
  ]},
  "data_sources_status": {"ensembl_vep": "ok", "clinvar": "ok", "gnomad": "skipped", "disgenet": "ok", "open_targets": "ok", "chembl": "no_data", "alphamissense": "ok"},
  "provenance": "AlphaFold Sovereign MCP v1.2.0 · 2026-06-08 · ensembl_vep=GRCh38 | clinvar=current | gnomad=v4 | alphamissense=2023"
}
```

## What Claude says back (paraphrased)

> **BRCA1 c.181T>G** (p.Cys61Gly, "C61G") triages **HIGH** — clinically
> significant.
>
> - **ClinVar:** classified **Pathogenic**, *reviewed by expert panel*
>   (variation 17661) — the strongest review tier short of a practice
>   guideline.
> - **Computational:** AlphaMissense 0.99 (likely pathogenic) and SIFT
>   "deleterious". PolyPhen disagrees ("benign", 0.03) — a genuine
>   predictor conflict the report surfaces rather than hides.
> - **ACMG draft:** PP3 (computational) + PP5 (reputable-source pathogenic).
>   This is a *draft* — a clinical geneticist must review before reporting.
> - **Mechanism (background):** C61G sits in the BRCA1 RING domain and
>   disrupts the BARD1 heterodimer / E3 ubiquitin-ligase activity —
>   consistent with the expert-panel pathogenic call.
> - **Disease context:** Open Targets links BRCA1 to breast cancer (0.84)
>   and hereditary breast-and-ovarian-cancer syndrome (0.83).
>
> **Caveats:** the gnomAD population lookup was skipped for this variant
> (absent from the common-variant index — consistent with a rare
> pathogenic allele), and the ACMG assignment is a heuristic draft, not a
> clinical determination.

## Reproducing this example for real

Point an MCP client (Claude Desktop, etc.) at the server and issue the tool
call above; see the repository README for setup.

## Files

- `transcript.jsonl` — full MCP exchange for the tool call.
