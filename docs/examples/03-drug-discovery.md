# Example: Drug Discovery — Imatinib → BCR-ABL → CML

> **Status: Illustrative.** Same caveat as the other examples — the
> server returns this shape consistent with its unit-tested
> orchestration over Open Targets, ChEMBL, UniProt, ClinVar, and
> AlphaFold DB. Live-API validation is on the v1.2.0 roadmap; see
> [`STATUS.md`](../status.md). The responses below use the tools' real
> top-level response keys; the **values** are illustrative.

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

## What the server returns (real response keys; values illustrative)

```jsonc
{
  "map_disease_drug_landscape": {
    "disease": {"mondo_id": "MONDO:0011996", "name": "chronic myelogenous leukemia"},
    "drug_landscape": {
      "approved_drugs": [
        {"molecule_chembl_id": "CHEMBL941", "pref_name": "IMATINIB", "max_phase": 4},
        {"molecule_chembl_id": "CHEMBL1201583", "pref_name": "DASATINIB", "max_phase": 4},
        {"molecule_chembl_id": "CHEMBL255863", "pref_name": "NILOTINIB", "max_phase": 4},
        {"molecule_chembl_id": "CHEMBL1873475", "pref_name": "PONATINIB", "max_phase": 4}
      ],
      "phase_3_drugs": [],
      "phase_1_2_drugs": [],
      "total_indication_entries": 20
    },
    "target_landscape": {
      "top_targets": [{"uniprot_id": "P00519", "approved_symbol": "ABL1", "association_score": 0.99, "tractable": true}],
      "druggable_targets": [{"uniprot_id": "P00519", "approved_symbol": "ABL1"}],
      "total_associated_targets": 18
    },
    "competitive_intelligence": {"approved_count": 6, "pipeline_count": 14, "druggable_target_count": 5, "investability": "Crowded — multiple approved therapies"},
    "data_sources": {"mondo": "https://www.ebi.ac.uk/ols4/ontologies/mondo", "open_targets": "https://platform.opentargets.org", "chembl": "https://www.ebi.ac.uk/chembl/"},
    "provenance": "AlphaFold Sovereign MCP v1.1.10 · 2026-05-11 · open_targets=24.06 | chembl=v36"
  },
  "assess_target_druggability": {
    "uniprot_id": "P00519",
    "druggability_tier": "HOT",
    "tier_rationale": "Approved-drug precedent + tractable small molecule + high-confidence kinase domain. HEURISTIC — see LIMITATIONS.md L2.",
    "scoring_breakdown": {"drug_precedent": 2, "tractability": 2, "structure_confidence": 1, "constraint": 1, "total": 6},
    "evidence": {"drug_count": 6, "tractability_labels": ["Approved Drug", "Advanced Clinical"], "plddt_mean": 71.8, "gene_constraint": {"loeuf": 0.41, "pLI": 0.86, "interpretation": "moderately constrained"}},
    "approved_drugs": [{"molecule_chembl_id": "CHEMBL941", "pref_name": "IMATINIB", "max_phase": 4, "max_phase_label": "Approved", "mechanism": "BCR-ABL tyrosine kinase inhibitor", "oral": true, "first_approval": 2001}],
    "tractability_assessment": {"small_molecule": true, "antibody": false, "protac": false, "labels_raw": ["Approved Drug", "Advanced Clinical"]},
    "actionability": "High — approved small-molecule inhibitors exist; strong structure-based design support.",
    "data_sources": {"chembl": "https://www.ebi.ac.uk/chembl/", "open_targets": "https://platform.opentargets.org", "gnomad": "https://gnomad.broadinstitute.org", "alphafold_db": "https://alphafold.ebi.ac.uk"},
    "provenance": "AlphaFold Sovereign MCP v1.1.10 · 2026-05-11 · chembl=v36 | open_targets=24.06 | gnomad=v4 | alphafold_db=v6"
  },
  "analyze_structural_confidence": {
    "uniprot_id": "P00519",
    "mean_plddt": 71.8,
    "confidence_tier": "High",
    "confidence_tier_explanation": "Backbone largely correct; some sidechain uncertainty.",
    "sequence_length": 1130,
    "pae_summary": {"mean_pae_angstrom": 9.4, "max_pae_angstrom": 31.2, "high_uncertainty_pairs": []},
    "domain_boundaries": {"candidate_positions": [241, 493], "n_putative_domains": 2, "note": "Boundary positions are zero-indexed residue numbers where PAE rises sharply. Validate with InterPro or UniProt feature annotations."},
    "druggability_pre_screen": {"ordered_fraction": 0.62, "structural_suitability": "SUITABLE for structure-based drug design"},
    "model_url": "https://alphafold.ebi.ac.uk/files/AF-P00519-F1-model_v6.pdb",
    "provenance": "AlphaFold Sovereign MCP v1.1.10 · 2026-05-11 · alphafold_db=v6 | plddt_version=v6"
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
>   classifies ABL1 as HOT (score 6: approved drugs, tractable small
>   molecule, high-confidence structure).
>
> **Why it works for CML specifically:** CML is one of the few cancers
> driven by a single, defined molecular lesion. Inhibiting BCR-ABL
> reverses the proliferative phenotype directly. The landscape also
> shows the later-generation TKIs (dasatinib, nilotinib, ponatinib)
> developed to handle resistance.
>
> **Structural context (AlphaFold P00519):**
> - Mean pLDDT 71.8 places the model in the "High" confidence tier, the
>   PAE-derived domain boundary (~residues 241–493) brackets the kinase
>   domain, and the structural pre-screen returns SUITABLE for
>   structure-based drug design.
> - **Background (not a per-residue field this tool returns):** the
>   gatekeeper residue **T315** — its `T315I` mutation sterically clashes
>   with imatinib and is the canonical clinical resistance variant;
>   ponatinib was designed to accommodate it.
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
