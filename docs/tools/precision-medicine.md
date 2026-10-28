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
    drug-precedent source provides an observed count in the requested
    development-stage scope. Otherwise the tool reports an
    evidence-availability error and no tier is assigned. A failed upstream
    request is not evidence of zero. The thresholds are author-defined,
    not calibrated against outcomes, and do not establish target safety
    or biological druggability. See [Limitations L2](../limitations.md).

## Drug-precedent count semantics

The two sources count different things and are **not interchangeable**;
both observed counts are always reported so the difference is auditable.

**ChEMBL** (`chembl_mechanism_molecule_count`): distinct molecules with a
mechanism-of-action record on the *single-protein* ChEMBL target that
carries the requested UniProt accession, at or above the requested
development stage (`drug_precedent_scope` is `approved_only` when
`include_clinical_stage=False`, otherwise `approved_and_clinical`). The
mechanism list is paginated and verified against ChEMBL's reported total;
a target with more than 200 distinct mechanism-linked molecules is refused
rather than truncated. ChEMBL often records a mechanism on a protein
complex or family rather than the single protein (live 2026-10-28, ChEMBL
37: GABRA1/P14867 has one single-subunit mechanism while the GABA-A
receptor complex target carries 66), so a ChEMBL zero does not establish
that no drug engages the protein, and a mechanism record does not by
itself establish direct target engagement for a given indication.

**Open Targets** (`open_targets_drug_candidate_count`):
`target.drugAndClinicalCandidates.count`. In the deployed release probed on
2026-10-28 (API 26.9.0, data 26.09) each row is one drug record with a
`maxClinicalStage`, and the count equalled the number of distinct drug
identifiers for every probed target (BRCA1 0, TP53 9, B3GAT1 0, PARP1 13,
GABRA1 76, EGFR 82). The count spans every stage, including withdrawn and
unknown-stage records, and is not stage-filtered by this tool.

The tools choose the count that backs the heuristic (`drug_count_source`)
as follows:

1. A positive ChEMBL count in the requested scope is used as the distinct
   molecule count.
2. Otherwise, when the requested scope includes clinical stages, a positive
   Open Targets count is credited as evidence of *presence* only:
   `drug_precedent_scoring_count` is 1, never three or more distinct drugs,
   because the record set is not stage- or mechanism-verified here.
3. Otherwise an observed ChEMBL zero stands for the requested scope; with
   `include_clinical_stage=False` an all-stage Open Targets count cannot
   override an approved-only ChEMBL zero.
4. An Open Targets zero bounds every scope and is accepted when ChEMBL has
   no record (live B3GAT1/Q9P2W7: no ChEMBL target, zero Open Targets
   records).
5. With no observed count in the requested scope (for example ChEMBL
   unavailable and only all-stage Open Targets records for an approved-only
   request) the tool raises instead of inventing a count.

`drug_count` preserves the chosen source's raw count. The ChEMBL-versus-
Open Targets difference is never treated as a contradiction: the sources
differ in target granularity and stage scope by construction.

A protein dossier also checks the supplied gene symbol against the
resolved UniProt-to-Ensembl target gene symbol when mapping evidence is
available. A mismatch prevents multi-gene evidence synthesis. Resolution
failures do not establish a matching biological identity and should be
evaluated separately.

## Recorded Open Targets identifier mapping

`resolve_target` uses the Open Targets `mapIds` GraphQL operation and
accepts only an exact approved-symbol or UniProt `proteinIds` match on the
returned `Target` object. `tests/fixtures/opentargets_mapids_20261028.json`
is a sanitised capture of the deployed API (release metadata and retrieval
date in its `meta` block) for P38398 (BRCA1), P04637 (TP53), B3GAT1 (an
approved gene symbol shaped like an accession) and two identifiers that do
not exist; `tests/test_client_opentargets.py` replays it through the
client. A later schema change must be re-recorded, not assumed.

## Disease-landscape counts

`map_disease_drug_landscape` reports counts only for the retrieved source
page. When the MONDO-keyed Open Targets lookup returns no targets and the
EFO-keyed retry fails, the target list is reported as `failed`, the
target-derived counts are `null` and the investability summary is
`NOT_ASSESSED`; an empty first page followed by a failed retry is never an
observed zero. A ChEMBL `drug_indication` response without the documented
list (for example an error envelope with HTTP 200) is `invalid_response`,
not an observed empty page. Indication rows are bucketed by ChEMBL's
reported `max_phase_for_ind` (live ChEMBL 37, 2026-10-28: `4`, `3`, `2`,
`1`, `0.5` for early phase 1, and `-1` for a clinical phase ChEMBL cannot
assign); `0.5` counts as early clinical pipeline. A retrieved row with
`-1` or a missing phase is reported in `unassigned_phase_entries`, and
`approved_count`, `pipeline_count` and investability are withheld because
the page's stage composition is not supported. Likewise, if any retrieved target row carries no
tractability assessment (`tractable: null`), `druggable_target_count` is
`null` and investability is `NOT_ASSESSED`, because an unknown
tractability is not an observed non-tractable target.

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
