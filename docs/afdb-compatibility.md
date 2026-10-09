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

## AI-derived residue annotations (October 2026)

EMBL-EBI's current AlphaFold DB website integrates residue- and mutation-level
literature annotations derived using a transformer model and transferred from
experimentally studied PDB structures through SIFTS. These annotations are
**upstream functionality, not an existing tool in this MCP server**.

Before exposing them here, an implementation must establish:
1. A stable, documented annotation retrieval API and its use conditions.
2. UniProt accession and isoform identity, PDB structure and chain identity,
   SIFTS residue correspondences, and model/fragment offsets.
3. Distinct evidence states: text-mined mention, experimentally supported
   source structure, transferred annotation, and predicted-model confidence.
4. Primary-publication provenance, missing-data behavior, conflicting
   mappings, reproducible fixtures, and no unsupported clinical claims.

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
a fabricated mean error of zero. PAE positions and domain-candidate
indices are local to the predicted model, not automatically UniProt or
experimental PDB residue coordinates. The domain-boundary heuristic and
the mean-pLDDT-based ordered-fraction proxy are not independently
validated domain annotations or biophysical disorder measurements.

An empty AFDB REST API response must not be interpreted as definitive
absence of a predicted model: the >2700-aa human-protein fragments are
provided by the FTP proteome archive, not the usual web API.

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
