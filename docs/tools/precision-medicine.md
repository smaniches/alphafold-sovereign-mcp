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

## AlphaMissense evidence status

The variant report and draft ACMG tool preserve the AlphaMissense numerical
score only when a VEP-mapped substitution has a well-formed score in [0, 1].
The `data_sources_status.alphamissense` field distinguishes `ok`,
`no_data`, `failed`, `invalid_response`, and explicit `skipped_*` states.
In particular, missing VEP evidence (`skipped_no_vep_data`) does not mean
AlphaMissense is biologically inapplicable; an upstream error
(`skipped_upstream_failed` or `skipped_upstream_invalid`) is not absence.
A failed lookup is never treated as negative or benign biological evidence.

## gnomAD and gene identity

A gnomAD response flagged `found: false` or `constraint_available: false`
is `no_data`, even if it includes other metadata. Absence must not be
presented as available population or gene-constraint evidence.

For versioned RefSeq HGVS input, the report and ACMG research tool may
recover gene context from the parenthetical input gene, an exact ClinVar
transcript-text match, or an Ensembl VEP consequence explicitly linked to the queried versioned
transcript, including a matching versioned `xref_refseq` identifier.
VEP RefSeq cross-references describe aligned transcript mappings: Ensembl
warns aligned transcripts may differ in sequence, exon structure and protein.
These mappings support *gene-level context only*, never allelic equivalence,
a clinical classification or a validated transcript sequence identity.
Versionless, mismatched-version, overlapping-gene and unrelated-transcript
cross-references are excluded. Conflicting evidence for the queried transcript
still causes abstention; candidate-only ClinVar hits never establish identity.

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
