# AlphaFold DB API compatibility

This document describes **implemented behavior in the source tree** and
distinguishes it from unshipped upstream annotations. The published release
may lag behind the source; check the PyPI version and changelog before relying
on a specific fix.

## Prediction API field migration

EMBL-EBI announced a **planned** 25 June 2026 sunset for legacy AlphaFold DB
prediction-response fields. However, an observed response from
[`/api/prediction/P04637`](https://alphafold.ebi.ac.uk/api/prediction/P04637)
on **9 October 2026** still contained both modern and legacy aliases,
including `paeImageUrl`. The announced cutoff is therefore not evidence
that old fields have disappeared from every live response. The local
adapter prefers the new fields and also accepts the old fields.

| Older field | Current field | Handling |
| --- | --- | --- |
| `entryId` | `modelEntityId` | Prefer current model ID; fallback to old |
| `uniprotSequence` | `sequence` | Prefer current amino-acid sequence; fallback to old |
| `uniprotStart` | `sequenceStart` | Not consumed for coordinate mapping |
| `uniprotEnd` | `sequenceEnd` | Not consumed for coordinate mapping |
| `isReviewed` | `isUniProtReviewed` | Not consumed |
| `isReferenceProteome` | `isUniProtReferenceProteome` | Not consumed |
| `paeImageUrl` | *(no announced replacement)* | Legacy image URL is passed through when present; existing MCP `file_urls.pae_image` is empty when absent |

The separate `paeDocUrl` JSON matrix remains a supported input when
advertised by upstream. We do **not** infer an image URL from a PAE JSON URL.

Source: [EMBL-EBI / PDBe announcement](https://www.ebi.ac.uk/pdbe/news/breaking-changes-afdb-predictions-api).
For live schemas use the [AlphaFold DB API reference](https://alphafold.ebi.ac.uk/api-doc).

## UniProt isoforms and long-protein fragments

The `/prediction/<accession>` response can contain multiple entries.
For numbered UniProt isoforms the client queries the canonical accession,
then selects the exact requested isoform from the returned records; it does
not assume the server accepts an isoform-specific API route.
Structural tools accept six/ten-character UniProtKB accessions with optional
numbered isoforms. Fragment identifiers such as `Q8WZ42-F2` are not
UniProt accession suffixes, and the multi-source precision-medicine tools
remain canonical-accession-only until isoform joins are independently verified.

- An entry with `uniprotAccession` exactly equal to the requested
  accession or isoform is selected without an additional UniProtKB request.
- If an explicit isoform is not listed, the client may reuse a
  **single** canonical-labelled model only if UniProtKB identifies the requested
  isoform as its curated `Displayed` sequence and the entire AlphaFold model
  sequence equals UniProtKB's canonical sequence. The returned metadata includes
  `_sovereign_verified_isoform`; this proves sequence identity, **not**
  independent prediction or experimental validation of that isoform.
- Do not assume `-1` is universally canonical. A different numbered
  isoform can be `Displayed`. For this fallback, UniProtKB access is required;
  HTTP errors, upstream timeouts, and malformed identity metadata are
  reported as verification errors, never biological absence.
- If multiple canonical-labelled records exist, their identity is ambiguous;
  no isoform alias is inferred.
- Historical unlabelled prediction responses can retain the first-entry
  fallback for **bare accessions only**, not unverified numbered isoforms.
- When multiple **fragments** share the same UniProt accession, the current
  client still takes the first matching record. That is *not* verified
  full-length fragment selection. See `LIMITATIONS.md` L8.

The existing `get_protein_structure` output keys (`entry_id`, `sequence`,
`sequence_length`, `file_urls`) are preserved for MCP clients. Structure
retrieval, confidence, and IDR summaries also carry
`model_uniprot_accession` and `verified_displayed_isoform`: the latter
is populated only after curated UniProtKB identity and complete sequence
agreement. The verifier is owned by the shared AlphaFold client, so
concurrent tool calls use the same rate limiter and circuit breaker.

**Do not** equate PDB/fragment-local residue numbers with full-length UniProt
positions without an explicit mapping. `pLDDT` measures prediction confidence,
not experimental validation.

## What was tested, and what was not

Regression tests cover modern-only metadata, mixed modern/legacy metadata,
legacy fallback, exact-isoform selection, mismatched labels, and structure
tool responses. Explicit isoform fallback tests additionally verify UniProtKB
`Displayed` metadata, full-sequence equality, ambiguous responses, malformed
upstream metadata and upstream failure propagation. The standard CI suite uses recorded/mocked upstream payloads.

A successful offline test **does not prove** that the live API will retain
the same schema, that every fragment is handled, or that a clinical
interpretation is scientifically valid. This repository has no continuously
executed live AlphaFold DB compatibility suite; see `STATUS.md`.

## Model version reported in provenance

Provenance footers name the AlphaFold DB model version of the record a
result was computed from, read from that record's `latestVersion` field
(for example `alphafold_db=v6`, or `v4/v6` when a comparison used models
of both versions). `version-unreported` means a record carried no such
field, and `not-retrieved` means no record was retrieved. The version is
not assumed.

## Scientific interpretation boundary

AlphaFold DB serves **predicted** structure models. Their atomic coordinates
are model outputs, not experimental measurements. pLDDT and PAE describe
specific aspects of prediction uncertainty; neither is an experimental
accuracy certificate or the probability of a fixed in-vivo conformation.
Alternative states, molecular partners, solvent/environment and disordered
regions can change the physical structural ensemble.

PDBe/PDB experimental structure records, SIFTS residue correspondences,
and literature-derived annotations have different provenance and semantics.
A residue correspondence can be checked against independently fetched
sequence, SIFTS and PDB identifiers without claiming to revalidate the
underlying structural experiment or an AlphaFold prediction. Even a consistent
mapping does not demonstrate binding, mechanism, pathogenicity, experimental
replication or correctness of an AI-mined sentence. Conversely, a failed
coordinate join may indicate an identifier/numbering or source-contract
problem, not a false structural prediction.

The optional literature connector remains deliberately restricted to
**upstream-reported annotations**. No structure-to-HGVS attribution,
mechanism, clinical classification or source-specific scientific confidence
is silently inferred. See issue #244 and its separate read-only audit PR for
a narrow, reproducible source-consistency test. The auditor's `PASS` means
agreement among the *queried records under the tested coordinate contract*,
not that AlphaFold's prediction was biologically proven or that a publication
is valid for the user's variant. Research users must distinguish a prediction,
an experimentally derived structural model, a text-mined claim and direct
variant-specific experimental evidence.

## AI-derived residue annotations (October 2026)

EMBL-EBI's current AlphaFold DB website integrates residue- and mutation-level
literature annotations derived using a transformer model and transferred from
experimentally studied PDB structures through SIFTS. These annotations originate upstream, not from this server's inference.
The server's `generate_variant_clinical_report` now has an **opt-in**
PDBe/IUCr literature evidence section using a caller-supplied *canonical*
UniProt accession and one-based reference residue. It calls the published
`/api/v2/uniprot/llm_annotations/summary/{accession}/{residue}` API,
retaining DOI/PMID/PMC, sentence, exact mention, AI score, PDB entity/chain,
PDB and author residue numbers, and source-reported UniProt correspondence.

This is **not automatic HGVS-to-UniProt or predicted-model residue mapping**.
The server checks returned accession/residue identity, rejects conflicting
records, and marks the PDBe/SIFTS correspondence as source-reported rather
than independently verified. Upstream errors remain distinct from biological
absence. Text-mined mentions neither increase an ACMG score nor independently
establish pathogenicity; scores reflect AI extraction, not clinical validity.
The PDBe payload does not supply experimental validation metrics in this
endpoint, so those remain explicitly unavailable.

The recorded API schema is documented in the upstream
[IUCr-annotation-pipeline notebook](https://github.com/PDBeurope/IUCr-annotation-pipeline/blob/main/pipeline/jupyter_notebooks/PDBe_API_for_text_mined_annotations.ipynb).
Remaining work for a stronger scientific join includes independent SIFTS
mapping validation, cross-isoform verification, fragment offsets, experimental
structure-quality metrics, and manually reviewed clinical interpretation.

Upstream background:
[AlphaFold DB](https://alphafold.ebi.ac.uk/) and
[PDBe's AI text-annotation documentation](https://www.ebi.ac.uk/training/online/courses/exploring-pdb-entry/pdb-entry-overview/text-annotations-ai/).

The relevant upstream datasets have their own attribution requirements;
this server is independent of EMBL-EBI and Google DeepMind.

## PAE and residue interpretation safeguards

The implementation accepts a PAE matrix only when it is a finite,
nonnegative square numeric array. Where a selected model advertises a
sequence, PAE dimensions must match its **model-local sequence length**.
Invalid or missing PAE is reported with an explicit status rather than
a fabricated mean error of zero. PAE positions, including the
`local_high_pae.positions` indices, are local to the predicted model, not
automatically UniProt or experimental PDB residue coordinates. Those
indices mark where near-diagonal PAE is locally elevated. They are not
domain boundaries: the tool does not assess domains and reports its
legacy `domain_boundaries` block as `NOT_ASSESSED` (`LIMITATIONS.md` L10).
Mean pLDDT is likewise not a biophysical disorder measurement, and the
ordered fraction is reported as not assessed.

An empty AFDB REST API response must not be interpreted as definitive
absence of a predicted model: the >2700-aa human-protein fragments are
provided by the FTP proteome archive, not the usual web API.

When no model is retrieved, the structure tools that take one accession
return `structure_available: false` and say why in `retrieval_status`.
`no_prediction_returned` means the prediction endpoint answered without a
model for the accession (HTTP 404 from that endpoint, or no matching
record). `request_failed` means a request was blocked by offline mode or
failed, for example on a timeout or a server error; that is not evidence
that no prediction exists. It also covers a failed request for the
coordinate file that a returned record advertises, HTTP 404 included:
the record exists, so that 404 is not an answer about the prediction.
`compare_proteins_topologically` makes the same distinction for each
accession in `proteins_failed`.

With `include_coordinates`, `get_protein_structure` embeds the file that
the reported record advertises (`file_urls.pdb`) and makes no second
prediction request. `coordinates_status` is `retrieved`,
`no_coordinates_returned` or `request_failed`. `coordinates_pdb` is empty
unless the status is `retrieved`; when it is empty, `coordinates_error`
gives the reason.

## Modeled residues and intrinsic-disorder segments

IDR outputs report legacy segment `start` and `end` in **1-based
modeled C-alpha ordinal order**, not canonical UniProt numbering.
The tool also exposes the corresponding PDB chain, author residue
identifiers and insertion codes, and segments must never bridge PDB
numbering gaps or chains. PDB author residue numbering is not a SIFTS
mapping, and an N-/C-terminal label refers to the modeled fragment,
not necessarily a full-length canonical protein terminus. Empty or
invalid C-alpha records do not justify a claim of an ordered protein.

Likewise the `get_protein_structure` metadata surfaces the upstream
`sequenceStart` / `sequenceEnd` interval when supplied. It does not
claim that those offsets independently validate a residue-to-PDB mapping.
