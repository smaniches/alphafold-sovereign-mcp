# Example: Drug Discovery — Imatinib → BCR-ABL → CML

> **Status: Illustrative.** Same caveat as the other examples — the
> server returns this shape consistent with its unit-tested
> orchestration over Open Targets, ChEMBL, UniProt, ClinVar, and
> AlphaFold DB. Live-API validation is on the v1.2.0 roadmap; see
> [`STATUS.md`](../status.md). The JSON below is an abridged,
> illustrative view of the responses; field names are simplified for
> readability and do not reproduce the literal tool output verbatim.

## User prompt

> Imatinib is approved for chronic myeloid leukaemia. Walk me through
> the molecular story: what does it bind, why does that work for CML,
> and what's the structural context?

## What the model calls

A multi-turn flow where Claude chains three tool calls. The server's
drug paths are disease-keyed (there is no drug-name entry point), so the
walk-through starts from the disease and pivots to the target and its
structure.

```jsonc
// Turn 1: the disease's approved + pipeline drug landscape
//         (surfaces Imatinib and the later-generation TKIs)
{"tool": "map_disease_drug_landscape", "params": {"disease_mondo_id": "MONDO:0011996"}}

// Turn 2: characterise the primary target — ABL1 (the BCR-ABL fusion driver)
{"tool": "assess_target_druggability", "params": {"uniprot_id": "P00519", "include_clinical_stage": true}}

// Turn 3: structural context for ABL1 (kinase domain, T315 gatekeeper)
{"tool": "analyze_structural_confidence", "params": {"uniprot_id": "P00519"}}
```

## What the server returns (illustrative — field names abridged for readability)

```jsonc
{
  "map_disease_drug_landscape": {
    "disease_mondo_id": "MONDO:0011996",
    "disease_label": "chronic myelogenous leukemia",
    "approved_drugs": [
      {"chembl_id": "CHEMBL941", "name": "IMATINIB", "max_phase": 4, "generation": "1st-gen TKI"},
      {"chembl_id": "CHEMBL1201583", "name": "DASATINIB", "max_phase": 4, "generation": "2nd-gen TKI"},
      {"chembl_id": "CHEMBL255863", "name": "NILOTINIB", "max_phase": 4, "generation": "2nd-gen TKI"},
      {"chembl_id": "CHEMBL1873475", "name": "PONATINIB", "max_phase": 4, "generation": "3rd-gen TKI"}
    ],
    "top_targets": [
      {"gene_symbol": "ABL1", "uniprot_id": "P00519", "open_targets_association": 0.99}
    ],
    "chembl_phase_counts": {"approved": 6, "phase_3": 3, "phase_2": 11}
  },
  "assess_target_druggability": {
    "uniprot_id": "P00519",
    "druggability_tier": "HOT",
    "score": 6,
    "tractability": {"labels": ["Approved Drug", "Advanced Clinical"], "small_molecule": true},
    "rationale": "Approved-drug precedent, tractable small molecule, well-resolved kinase domain. HEURISTIC — see LIMITATIONS.md L2."
  },
  "analyze_structural_confidence": {
    "uniprot_id": "P00519",
    "model_url": "https://alphafold.ebi.ac.uk/files/AF-P00519-F1-model_v6.pdb",
    "plddt_mean": 71.8,
    "well_resolved_segments": [
      {"residues": [242, 493], "label": "kinase domain", "plddt_mean": 92.4}
    ],
    "gatekeeper_residue": {
      "position": 315,
      "residue": "THR",
      "plddt": 95.1,
      "note": "T315 is the gatekeeper. The T315I mutation sterically clashes with imatinib and is the canonical clinical resistance variant."
    }
  }
}
```

## What Claude says back (paraphrased)

> **Imatinib** (CHEMBL941, approved 2001 as Gleevec/Glivec) is the
> founding tyrosine-kinase inhibitor and one of the cleanest molecular-
> targeting success stories in oncology.
>
> **Mechanism:**
> - In chronic myeloid leukaemia, the Philadelphia chromosome creates
>   a `BCR-ABL` fusion — a constitutively active version of the
>   `ABL1` tyrosine kinase. Imatinib binds the ATP-binding pocket of
>   ABL1 in its inactive conformation and locks the kinase shut.
> - The disease→drug landscape surfaces `ABL1` as the top CML target
>   (Open Targets association 0.99), and the druggability heuristic
>   classifies ABL1 as HOT (kinase, approved drugs, high-confidence
>   structure).
>
> **Why it works for CML specifically:** CML is one of the few cancers
> driven by a single, defined molecular lesion. Inhibiting BCR-ABL
> reverses the proliferative phenotype directly. The landscape also
> shows the later-generation TKIs (dasatinib, nilotinib, ponatinib)
> developed to handle resistance.
>
> **Structural context (AlphaFold P00519):**
> - The kinase domain (residues 242–493) is well-resolved (pLDDT 92.4).
> - Residue **T315 is the gatekeeper** — pLDDT 95.1. Mutating it to
>   isoleucine (`T315I`) sterically clashes with imatinib and is the
>   canonical clinical resistance variant. Ponatinib was designed to
>   accommodate T315I.
>
> **Off-targets (background, not from these calls):** imatinib also
> inhibits c-KIT and PDGFRα, which is why it also treats GIST tumours —
> established pharmacology rather than output of the three tools above.
>
> **Disclaimers:** the druggability tier is a heuristic; clinical-phase
> and approval data come from ChEMBL / Open Targets and are not a
> substitute for a regulatory label.

## Reproducing this example for real

Same setup as Example 01.

## Files

- `transcript.jsonl` — full MCP exchange across the three tool calls.
