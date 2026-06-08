# Example: Drug Discovery — Imatinib → BCR-ABL → CML

> **Status: Illustrative.** Same caveat as the other examples — the
> server returns this shape consistent with its unit-tested
> orchestration over Open Targets, ChEMBL, UniProt, ClinVar, and
> AlphaFold DB. Live-API validation is on the v1.2.0 roadmap; see
> [`STATUS.md`](../status.md).

> **Outdated tool names.** This walk-through was authored against the
> `v1.1.0-rc1` tool surface and references tools — `drug_lookup`,
> `explore_disease_target_landscape`, `fetch_alphafold_structure` —
> that are **not present in the current release**. The drug-name entry
> point in particular has no equivalent in the current 29-tool surface
> (all drug paths are disease-keyed). The trace below is therefore not
> runnable as written against this release and has not yet been
> re-authored. For the current tool inventory see the
> [tool reference](../tools/index.md).

## User prompt

> Imatinib is approved for chronic myeloid leukaemia. Walk me through
> the molecular story: what does it bind, why does that work for CML,
> and what's the structural context?

## What the model calls

This is a multi-turn flow where Claude chains tool calls. The
illustrative trace below shows the four tool calls in the order Claude
typically issues them.

```jsonc
// Turn 1: look up the drug
{"tool": "drug_lookup", "params": {"name": "Imatinib"}}

// Turn 2: characterise the primary target
{"tool": "assess_target_druggability", "params": {"gene_symbol": "ABL1"}}

// Turn 3: pull the disease-target link
{"tool": "explore_disease_target_landscape", "params": {"disease_id": "MONDO_0011996", "target_gene": "ABL1"}}

// Turn 4: look at the structural context
{"tool": "fetch_alphafold_structure", "params": {"uniprot_id": "P00519"}}
```

## What the server returns (composite; values illustrative)

```jsonc
{
  "drug_lookup": {
    "chembl_id": "CHEMBL941",
    "name": "IMATINIB",
    "first_approval": 2001,
    "max_phase": 4,
    "indications": [
      {"mesh": "D015464", "name": "Leukaemia, myeloid, chronic-phase"},
      {"mesh": "D018263", "name": "Gastrointestinal stromal tumors"},
      {"mesh": "D015451", "name": "Leukaemia, lymphocytic, acute"}
    ],
    "mechanism_of_action": "ABL1/BCR-ABL tyrosine kinase inhibitor",
    "targets": [
      {"chembl_id": "CHEMBL1862", "uniprot_id": "P00519", "name": "Tyrosine-protein kinase ABL1", "primary": true},
      {"chembl_id": "CHEMBL1936", "uniprot_id": "P10721", "name": "Mast/stem cell growth factor receptor Kit"},
      {"chembl_id": "CHEMBL2007", "uniprot_id": "P16234", "name": "Platelet-derived growth factor receptor alpha"}
    ]
  },
  "target_ABL1": {
    "uniprot_id": "P00519",
    "function_summary": "Non-receptor tyrosine kinase regulating proliferation, differentiation, adhesion, stress response. The BCR-ABL fusion is the oncogenic driver of CML.",
    "open_targets_association_cml": 0.99,
    "tractability": {"labels": ["Approved Drug", "Advanced Clinical"], "small_molecule": true},
    "druggability_tier_draft": {"tier": "HOT", "score": 6}
  },
  "disease_landscape_cml": {
    "disease_id": "MONDO_0011996",
    "disease_label": "Chronic myelogenous leukaemia",
    "target_gene": "ABL1",
    "association_score": 0.99,
    "key_drugs_for_disease_target": [
      {"chembl_id": "CHEMBL941", "name": "IMATINIB", "generation": "1st-gen TKI"},
      {"chembl_id": "CHEMBL1201583", "name": "DASATINIB", "generation": "2nd-gen TKI"},
      {"chembl_id": "CHEMBL255863", "name": "NILOTINIB", "generation": "2nd-gen TKI"},
      {"chembl_id": "CHEMBL1873475", "name": "PONATINIB", "generation": "3rd-gen TKI"}
    ],
    "known_resistance_mutations": [
      {"variant": "T315I", "effect": "Disrupts imatinib binding; sensitive to ponatinib"},
      {"variant": "Y253H", "effect": "Reduces imatinib affinity"},
      {"variant": "E255K", "effect": "Reduces imatinib affinity"}
    ]
  },
  "structure_ABL1": {
    "uniprot_id": "P00519",
    "model_url": "https://alphafold.ebi.ac.uk/files/AF-P00519-F1-model_v6.pdb",
    "n_residues": 1130,
    "plddt_mean": 71.8,
    "kinase_domain_residues": [242, 493],
    "kinase_domain_plddt_mean": 92.4,
    "key_residue_t315": {
      "position": 315,
      "plddt": 95.1,
      "note": "T315 is the gatekeeper residue. Mutation to isoleucine (T315I) sterically clashes with imatinib and is the canonical clinical resistance variant."
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
> - Open Targets scores `ABL1` ↔ CML at 0.99 (essentially axiomatic),
>   and the druggability heuristic classifies ABL1 as HOT
>   (kinase, approved drugs, high-confidence structure).
>
> **Why it works for CML specifically:** CML is one of the few cancers
> driven by a single, defined molecular lesion. Inhibiting BCR-ABL
> reverses the proliferative phenotype directly.
>
> **Structural context (AlphaFold P00519):**
> - The kinase domain (residues 242–493) is well-resolved (pLDDT 92.4).
> - Residue **T315 is the gatekeeper** — pLDDT 95.1. Mutating it to
>   isoleucine (`T315I`) sterically clashes with imatinib and is the
>   canonical clinical resistance variant. Ponatinib was designed to
>   accommodate T315I.
>
> **Off-targets:** imatinib also inhibits c-KIT (P10721) and PDGFRα
> (P16234), which is why it works in GIST tumours (KIT-driven) as well.
>
> **Disclaimers**: druggability tier is a heuristic; the resistance-
> mutation list comes from ChEMBL and the literature but is not
> exhaustive.

## Reproducing this example for real

Same setup as Example 01.

## Files

- `transcript.jsonl` — full MCP exchange across the four tool calls.
