# Example: Drug Discovery — Imatinib → BCR-ABL → CML

> **Status: Captured live.** The responses below were captured from a
> real run against the live Open Targets, ChEMBL, UniProt, gnomAD, and
> AlphaFold DB APIs on **2026-06-08** (long arrays abridged for
> readability; full payloads in [`transcript.jsonl`](transcript.jsonl)).
> See [`STATUS.md`](../../STATUS.md) for what "verified" covers.

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

// Turn 3: structural context for ABL1 (kinase domain + PAE-derived boundaries)
{"tool": "analyze_structural_confidence", "params": {"uniprot_id": "P00519"}}
```

## What the server returns (captured live; arrays abridged)

```jsonc
{
  "map_disease_drug_landscape": {
    "disease": {"mondo_id": "MONDO:0011996", "name": "chronic myeloid leukemia"},
    "drug_landscape": {
      "approved_drugs": [   // 9 total (max_phase 4 for this indication)
        {"molecule_chembl_id": "CHEMBL1642", "pref_name": "IMATINIB MESYLATE", "max_phase_for_indication": "4.0"},
        {"molecule_chembl_id": "CHEMBL1421", "pref_name": "DASATINIB ANHYDROUS", "max_phase_for_indication": "4.0"},
        {"molecule_chembl_id": "CHEMBL1201740", "pref_name": "NILOTINIB HYDROCHLORIDE MONOHYDRATE", "max_phase_for_indication": "4.0"},
        {"molecule_chembl_id": "CHEMBL2105708", "pref_name": "PONATINIB HYDROCHLORIDE", "max_phase_for_indication": "4.0"},
        {"molecule_chembl_id": "CHEMBL288441", "pref_name": "BOSUTINIB", "max_phase_for_indication": "4.0"},
        {"molecule_chembl_id": "CHEMBL4297220", "pref_name": "ASCIMINIB HYDROCHLORIDE", "max_phase_for_indication": "4.0"}
        // … also HYDROXYUREA, BUSULFAN, INTERFERON ALFA-2B
      ],
      "phase_3_drugs": [   // 10 total
        {"molecule_chembl_id": "CHEMBL255863", "pref_name": "NILOTINIB", "max_phase_for_indication": "3.0"},
        {"molecule_chembl_id": "CHEMBL1873475", "pref_name": "PONATINIB", "max_phase_for_indication": "3.0"}
        // … CYCLOPHOSPHAMIDE, FLUDARABINE, CYCLOSPORINE, INTERFERON ALFA, …
      ],
      "phase_1_2_drugs": [],
      "total_indication_entries": 20
    },
    "target_landscape": {
      "top_targets": [   // 10 total, ranked by Open Targets overall association
        {"uniprot_id": "P00519", "target_gene_symbol": "ABL1", "overall_score": 0.832, "tractable": true},
        {"uniprot_id": "P11274", "target_gene_symbol": "BCR", "overall_score": 0.829, "tractable": true},
        {"uniprot_id": "P10721", "target_gene_symbol": "KIT", "overall_score": 0.709, "tractable": true},
        {"uniprot_id": "Q9Y6X0", "target_gene_symbol": "SETBP1", "overall_score": 0.678, "tractable": true},
        {"uniprot_id": "P09619", "target_gene_symbol": "PDGFRB", "overall_score": 0.648, "tractable": true}
        // … TET2, …
      ],
      "total_associated_targets": 20
    },
    "competitive_intelligence": {"approved_count": 9, "pipeline_count": 11, "druggable_target_count": 10, "investability": "HIGH — well-validated therapeutic area with multiple approved agents and druggable targets."},
    "data_sources": {"mondo": "https://www.ebi.ac.uk/ols4/ontologies/mondo", "open_targets": "https://platform.opentargets.org", "chembl": "https://www.ebi.ac.uk/chembl/"},
    "provenance": "AlphaFold Sovereign MCP v1.1.10 · 2026-06-08 · open_targets=24.06 | chembl=v36"
  },
  "assess_target_druggability": {
    "uniprot_id": "P00519",
    "druggability_tier": "WARM",
    "tier_rationale": "Some drug precedent or tractability; further profiling recommended.",
    "scoring_breakdown": {
      "total_score": 2,
      "thresholds": {"HOT": ">=4", "WARM": ">=2", "COLD": ">=1", "NOT_DRUGGABLE": "<1"},
      "components": {
        "drug_precedent": {"contribution": 3, "input": "drug_count=18, >=3"},
        "tractability": {"contribution": 0, "input": "no small_molecule label"},
        "plddt": {"contribution": 0, "input": "plddt_mean=63.4, <70"},
        "loeuf_safety": {"contribution": -1, "input": "loeuf=0.192, <0.35 — safety concern"}
      }
    },
    "evidence": {
      "drug_count": 18,
      "tractability_labels": ["Approved Drug", "Structure with Ligand", "High-Quality Pocket", "Druggable Family", "Small Molecule Binder"],
      "plddt_mean": 63.38,
      "gene_constraint": {"loeuf": 0.192, "pLI": 1.0, "interpretation": "Highly constrained (LOEUF=0.192): strong intolerance to loss-of-function — likely haploinsufficient."}
    },
    "approved_drugs": [{"molecule_chembl_id": "CHEMBL288441", "pref_name": "BOSUTINIB", "max_phase": 4, "max_phase_label": "Approved", "mechanism": "Tyrosine-protein kinase ABL inhibitor", "oral": true, "first_approval": 2012}],
    "tractability_assessment": {"small_molecule": false, "antibody": false, "protac": false},
    "actionability": "Target is WARM: limited clinical precedent (18 drugs). Recommend structural analysis + FBDD.",
    "provenance": "AlphaFold Sovereign MCP v1.1.10 · 2026-06-08 · chembl=v36 | open_targets=24.06 | gnomad=v4 | alphafold_db=v6"
  },
  "analyze_structural_confidence": {
    "uniprot_id": "P00519",
    "mean_plddt": 63.38,
    "confidence_tier": "LOW",
    "confidence_tier_explanation": "pLDDT 50–70: may represent IDP region or novel fold. Verify with experimental structure.",
    "sequence_length": 1130,
    "pae_summary": {"mean_pae_angstrom": 24.59, "max_pae_angstrom": 31.0, "high_uncertainty_pairs": [{"residue_a": 1, "residue_b": 91, "pae": 31.0}]},
    "domain_boundaries": {"candidate_positions": [], "n_putative_domains": 1, "note": "Boundary positions are zero-indexed residue numbers where PAE rises sharply. Validate with InterPro or UniProt feature annotations."},
    "druggability_pre_screen": {"ordered_fraction": 0.268, "structural_suitability": "CAUTION: low confidence may indicate IDP or novel fold"},
    "model_url": "https://alphafold.ebi.ac.uk/files/AF-P00519-F1-model_v6.pdb",
    "provenance": "AlphaFold Sovereign MCP v1.1.10 · 2026-06-08 · alphafold_db=v6 | plddt_version=v6"
  }
}
```

## What Claude says back (paraphrased)

> **Imatinib** (Gleevec/Glivec) is the founding tyrosine-kinase inhibitor
> and one of the cleanest molecular-targeting success stories in oncology.
>
> **Mechanism:**
> - In chronic myeloid leukaemia, the Philadelphia chromosome creates
>   a `BCR-ABL` fusion — a constitutively active version of the
>   `ABL1` tyrosine kinase. Imatinib binds the ATP-binding pocket of
>   ABL1 in its inactive conformation and locks the kinase shut.
> - The disease→drug landscape returns the full BCR-ABL TKI franchise as
>   approved for CML — imatinib, dasatinib, nilotinib, ponatinib,
>   bosutinib, and the newer allosteric inhibitor asciminib — plus 11
>   pipeline agents, and ranks `ABL1` (0.83) and its fusion partner `BCR`
>   (0.83) as the top targets. Investability: HIGH.
>
> **A transparent caveat (this is the interesting part):** the
> druggability heuristic scores `ABL1` as **WARM (score 2), not HOT** —
> for a target with six approved drugs. The breakdown shows why, and it's
> instructive: it is run on the **full-length 1130-residue chain**, whose
> mean pLDDT is only 63 (the kinase domain is crisp, but the chain has
> large low-confidence/disordered regions), so the structure term scores
> 0; the Open Targets tractability labels don't trip the heuristic's
> small-molecule check; and gnomAD flags `ABL1` as highly constrained
> (LOEUF 0.19), subtracting a point for loss-of-function safety. The
> heuristic *under-rates* a clinically-validated target — a reminder to
> read the breakdown, and to assess the kinase **domain** rather than the
> whole-chain average.
>
> **Structural context (AlphaFold P00519):** consistent with the above,
> the full chain returns "LOW" confidence (mean pLDDT 63) and the
> structural pre-screen flags CAUTION — the druggable, well-folded part
> is the kinase domain, not the whole protein.
>
> **Background (not output of these calls):** the gatekeeper residue
> **T315** — its `T315I` mutation sterically clashes with imatinib and is
> the canonical clinical resistance variant; ponatinib and asciminib were
> developed to handle it.
>
> **Disclaimers:** the druggability tier is a heuristic (see its
> `scoring_breakdown`); clinical-phase and approval data come from
> ChEMBL / Open Targets and are not a substitute for a regulatory label.

## Reproducing this example for real

Same setup as Example 01.

## Files

- `transcript.jsonl` — full MCP exchange across the three tool calls.
