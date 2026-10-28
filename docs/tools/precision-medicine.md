# Precision-medicine tools

!!! warning "ACMG mapping is not validated"
    Both `generate_variant_clinical_report` and `classify_variant_acmg`
    use an ACMG/AMP criterion mapping that has **not** been reviewed
    by an independent clinical geneticist. Treat the output as a
    research aid, never as clinical decision support. See
    [Limitations L1](../limitations.md).

!!! warning "Druggability tiers are unvalidated research heuristics"
    `assess_target_druggability` and `synthesize_protein_dossier` report
    `HOT`, `WARM`, `COLD`, or `NOT_DRUGGABLE` only when at least one
    drug-precedent source provides an observed count. If neither ChEMBL nor
    Open Targets supplies a count, the tool reports an evidence-availability error and the
    score is unavailable. A failed upstream request is not evidence of zero.
    ChEMBL mechanism-linked molecule counts and Open Targets clinical-
    candidate counts have different source scopes; fallback is not a
    harmonized or deduplicated total. The thresholds are author-defined,
    not calibrated against outcomes, and do not establish target safety
    or biological druggability. See [Limitations L2](../limitations.md).

## Drug-precedent count semantics

ChEMBL's complete, verified mechanism results are counted as distinct
mechanism-linked molecule identifiers. Open Targets
`drugAndClinicalCandidates.count` instead counts target-disease-drug
clinical rows and may repeat one molecule across different indications.
The two counts are **not interchangeable**.

The tools report the source-specific `drug_count_source`,
`chembl_mechanism_molecule_count`, and
`open_targets_clinical_row_count`. Their `drug_count` preserves the
chosen source's raw count; `drug_precedent_scoring_count` is the
conservative input to the unvalidated heuristic. If only Open Targets
clinical rows are available, any positive row count contributes evidence
of *at least one* clinical association, never evidence of three distinct
drugs. When both sources give incompatible observed zero-versus-positive
results, the tools abstain rather than produce a druggability tier.

A protein dossier also checks the supplied gene symbol against the
resolved UniProt-to-Ensembl target gene symbol when mapping evidence is
available. A mismatch prevents multi-gene evidence synthesis. Resolution
failures do not establish a matching biological identity and should be
evaluated separately.

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
