# Example: Target Characterisation — EGFR

> **Status: Illustrative.** Same caveat as
> [`examples/01-variant-triage/`](01-variant-triage.md): the
> numbers below are consistent with what the server emits when its
> upstream clients (Open Targets, ChEMBL, UniProt, AlphaFold DB,
> gnomAD) return data we have unit tests for. They have NOT been
> verified against live API responses for this exact target.
> End-to-end validation lands in v1.2.0; see
> [`STATUS.md`](../status.md).

## User prompt

> Characterise EGFR as a drug target for me. How tractable is it,
> what approved drugs hit it, what's the gnomAD constraint, and is
> there an AlphaFold structure I can look at?

## What the model calls

```jsonc
{
  "tool": "assess_target_druggability",
  "params": {
    "gene_symbol": "EGFR",
    "include_drugs": true,
    "include_alphafold": true,
    "include_constraint": true
  }
}
```

## What the server returns (schema-accurate; values illustrative)

```jsonc
{
  "input": {"gene_symbol": "EGFR"},
  "uniprot": {
    "uniprot_id": "P00533",
    "protein_name": "Epidermal growth factor receptor",
    "length": 1210,
    "subcellular_location": ["Cell membrane", "Endosome", "Nucleus"],
    "function_summary": "Receptor tyrosine kinase binding EGF family ligands. Activates ERK, AKT, JAK-STAT cascades."
  },
  "open_targets": {
    "target_id": "ENSG00000146648",
    "association_score": 0.92,
    "diseases_top": [
      {"id": "EFO_0003060", "label": "Non-small cell lung carcinoma", "association": 0.99},
      {"id": "EFO_0000305", "label": "Breast carcinoma", "association": 0.81},
      {"id": "MONDO_0008549", "label": "Glioblastoma multiforme", "association": 0.71}
    ],
    "tractability": {
      "labels": ["Approved Drug", "Advanced Clinical", "Discovery_small_molecule", "Antibody clinical"],
      "small_molecule": true,
      "antibody": true,
      "modality_score_sm": 4,
      "modality_score_ab": 4
    }
  },
  "chembl": {
    "chembl_id": "CHEMBL203",
    "approved_drugs_count": 14,
    "approved_drugs_top": [
      {"chembl_id": "CHEMBL554", "name": "GEFITINIB", "first_approval": 2003},
      {"chembl_id": "CHEMBL553", "name": "ERLOTINIB", "first_approval": 2004},
      {"chembl_id": "CHEMBL1173655", "name": "OSIMERTINIB", "first_approval": 2015},
      {"chembl_id": "CHEMBL1801", "name": "CETUXIMAB", "first_approval": 2004}
    ]
  },
  "gnomad_constraint": {
    "loeuf": 0.45,
    "mis_z": 3.21,
    "syn_z": 0.78,
    "constraint_note": "LOEUF 0.45 — moderately constrained; loss-of-function tolerance is limited but not absent."
  },
  "alphafold": {
    "uniprot_id": "P00533",
    "model_url": "https://alphafold.ebi.ac.uk/files/AF-P00533-F1-model_v4.pdb",
    "plddt_mean": 73.6,
    "plddt_note": "High mean confidence; kinase domain (residues 712-979) is well-resolved (pLDDT > 90).",
    "n_residues": 1210
  },
  "druggability_tier_draft": {
    "tier": "HOT",
    "score": 5,
    "score_components": {
      "approved_drugs_>=3": "+3",
      "tractability_small_mol": "+2",
      "alphafold_plddt_>=70": "+1",
      "loeuf_<0.35": "0 (LOEUF 0.45, no penalty)"
    },
    "rationale": "Strong drug precedent (14 approved drugs), tractable small-molecule and antibody modalities, well-resolved kinase domain. Tier is a HEURISTIC, not a validated prediction — see LIMITATIONS.md L2."
  },
  "sources_cited": ["UniProt P00533", "Open Targets ENSG00000146648", "ChEMBL CHEMBL203", "gnomAD v4.1.0 constraint table", "AlphaFold DB v4 (P00533)"],
  "report_generated_at": "2026-05-11T14:35:12Z"
}
```

## What Claude says back (paraphrased)

> **EGFR (P00533)** is a textbook "HOT" target by our heuristic:
>
> - **Indications**: Open Targets ranks it strongest for non-small cell
>   lung carcinoma (association 0.99), breast carcinoma, and
>   glioblastoma.
> - **Modalities**: both small-molecule (gefitinib, erlotinib,
>   osimertinib, …) and antibody (cetuximab) routes are clinically
>   validated — 14 approved drugs total in ChEMBL.
> - **Tractability**: Open Targets labels include `Approved Drug`,
>   `Advanced Clinical`, `Discovery_small_molecule`, and
>   `Antibody clinical`.
> - **Constraint**: LOEUF 0.45 — moderately constrained. Loss-of-
>   function tolerance is limited but not absent, so toxicity from
>   on-target inhibition is plausible but the drug record shows it's
>   manageable.
> - **Structure**: AlphaFold pLDDT mean 73.6; the kinase domain
>   (712–979) is well-resolved (pLDDT > 90), which is what you want
>   for pocket-finding.
> - **Caveat**: The "HOT" tier is a 4-line heuristic, not a
>   calibrated prediction. Treat as a triage signal alongside
>   medicinal-chemistry review.

## Reproducing this example for real

Same setup as Example 01.

## Files

- `transcript.jsonl` — MCP exchange.
- `expected_output_schema.json` — JSON Schema for the report shape.
