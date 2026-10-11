# Precision-medicine tools

!!! warning "ACMG mapping is not validated"
    Both `generate_variant_clinical_report` and `classify_variant_acmg`
    use an ACMG/AMP criterion mapping that has **not** been reviewed
    by an independent clinical geneticist. Treat the output as a
    research aid, never as clinical decision support. See
    [Limitations L1](../limitations.md).

!!! warning "Druggability tier is a heuristic"
    `assess_target_druggability` returns a `HOT/WARM/COLD/NOT_DRUGGABLE`
    tier from a 4-line scoring heuristic. The thresholds are not
    calibrated against a benchmark. See
    [Limitations L2](../limitations.md).

## Optional PDBe/IUCr residue annotations

Set `include_literature_evidence=True` on
`generate_variant_clinical_report`, with both
`literature_uniprot_id` (canonical UniProt accession) and
`literature_uniprot_residue` (positive one-based reference coordinate).
The default report makes no PDBe request. Missing coordinates produce an
explicit status rather than a guessed mapping; upstream failures are not
treated as biological absence.

The section includes PMID/PMC/DOI, sentence/exact extracted phrase,
PDB entry/chain/residue, UniProt coordinate, and the NER model score.
These are text-mined mentions with source-reported correspondence, not
experimental validation, automatic HGVS mapping, AlphaMissense evidence,
or ACMG assertions. See [AFDB API compatibility](../afdb-compatibility.md)
and [Limitations L9](../limitations.md).

::: alphafold_sovereign.tools.precision_medicine
    options:
      show_root_heading: true
      members_order: source
