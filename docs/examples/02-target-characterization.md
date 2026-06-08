# Example: Target Characterisation — EGFR Druggability

> **Status: Captured live.** The response below was captured from a real
> run of `assess_target_druggability` against the live ChEMBL, Open
> Targets, gnomAD, and AlphaFold DB APIs on **2026-06-08** (arrays
> abridged; full payload in
> [`transcript.jsonl`](https://github.com/smaniches/alphafold-sovereign-mcp/blob/main/examples/02-target-characterization/transcript.jsonl)).
> See [`STATUS.md`](../status.md) for what "verified" covers.

## User prompt

> How druggable is EGFR (UniProt P00533), and what is the evidence?

## What the model calls

```jsonc
{"tool": "assess_target_druggability", "params": {"uniprot_id": "P00533", "include_clinical_stage": true}}
```

## What the server returns (captured live; abridged)

```jsonc
{
  "uniprot_id": "P00533",
  "druggability_tier": "HOT",
  "tier_rationale": "Strong drug precedent and tractability evidence.",
  "scoring_breakdown": {
    "total_score": 4,
    "thresholds": {"HOT": ">=4", "WARM": ">=2", "COLD": ">=1", "NOT_DRUGGABLE": "<1"},
    "components": {
      "drug_precedent": {"contribution": 3, "input": "drug_count=50, >=3"},
      "tractability": {"contribution": 0, "input": "no small_molecule label"},
      "plddt": {"contribution": 1, "input": "plddt_mean=75.9, >=70"},
      "loeuf_safety": {"contribution": 0, "input": "loeuf=0.505, >=0.35"}
    }
  },
  "evidence": {
    "drug_count": 50,
    "tractability_labels": ["Approved Drug", "Structure with Ligand", "High-Quality Ligand", "High-Quality Pocket", "Druggable Family", "Small Molecule Binder", "Advanced Clinical"],
    "plddt_mean": 75.94,
    "gene_constraint": {"loeuf": 0.505, "pLI": 0.389, "interpretation": "Moderately constrained (LOEUF=0.505): partial intolerance to loss-of-function."}
  },
  "approved_drugs": [   // 10 total
    {"molecule_chembl_id": "CHEMBL1201179", "pref_name": "LAPATINIB DITOSYLATE", "max_phase": 4, "max_phase_label": "Approved", "mechanism": "Epidermal growth factor receptor erbB1 inhibitor", "oral": true, "first_approval": 2007}
    // … also OSIMERTINIB, AFATINIB, NERATINIB, MOBOCERTINIB, AMIVANTAMAB, NECITUMUMAB, LAZERTINIB
  ],
  "tractability_assessment": {"small_molecule": false, "antibody": false, "protac": false},
  "actionability": "Target is HOT: 50 known drug(s) + tractability confirmed. Prioritise for lead optimisation or repurposing screen.",
  "provenance": "AlphaFold Sovereign MCP v1.2.0 · 2026-06-08 · chembl=v37 | open_targets=26.03 | gnomad=v4 | alphafold_db=v6"
}
```

## What Claude says back (paraphrased)

> **EGFR (P00533)** is **HOT** — one of the most thoroughly drugged targets
> in oncology.
>
> - **Drug precedent (+3):** 50 known drugs, including approved EGFR TKIs
>   (osimertinib, afatinib, lapatinib, mobocertinib, lazertinib) and
>   antibodies (amivantamab, necitumumab).
> - **Structure (+1):** full-length AlphaFold mean pLDDT 75.9 (the kinase
>   domain is well-resolved); EGFR also has abundant experimental
>   ligand-bound structures.
> - **Safety (0):** gnomAD LOEUF 0.505 — moderately constrained, no penalty.
> - **Total 4 → HOT.**
>
> **A transparent note:** `tractability_assessment.small_molecule` reads
> `false` even though EGFR has dozens of approved small-molecule TKIs —
> the heuristic's label check doesn't trip on Open Targets' exact label
> set here, so that component contributes 0. The tier is still HOT on drug
> precedent and structure; it's a reminder to read the `scoring_breakdown`
> rather than the single tractability flag.
>
> **Disclaimers:** the druggability tier is a heuristic (see
> `scoring_breakdown`); clinical-phase and approval data come from ChEMBL /
> Open Targets and are not a substitute for a regulatory label.

## Reproducing this example for real

Point an MCP client (Claude Desktop, etc.) at the server and issue the tool
call above; see the repository README for setup.

## Files

- `transcript.jsonl` — full MCP exchange for the tool call.
