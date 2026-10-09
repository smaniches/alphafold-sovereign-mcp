# AlphaFold DB API compatibility

This document describes **implemented behavior in the source tree** and
distinguishes it from unshipped upstream annotations. The published release
may lag behind the source; check the PyPI version and changelog before relying
on a specific fix.

## Prediction API field migration

EMBL-EBI announced the retirement of legacy AlphaFold DB prediction-response
fields effective 25 June 2026. The local adapter reads the new fields first
and accepts the old names in previously recorded responses.

| Older field | Current field | Handling |
| --- | --- | --- |
| `entryId` | `modelEntityId` | Prefer current model ID; fallback to old |
| `uniprotSequence` | `sequence` | Prefer current amino-acid sequence; fallback to old |
| `uniprotStart` | `sequenceStart` | Not consumed for coordinate mapping |
| `uniprotEnd` | `sequenceEnd` | Not consumed for coordinate mapping |
| `isReviewed` | `isUniProtReviewed` | Not consumed |
| `isReferenceProteome` | `isUniProtReferenceProteome` | Not consumed |
| `paeImageUrl` | *(removed)* | Existing MCP `file_urls.pae_image` is empty when absent |

The separate `paeDocUrl` JSON matrix remains a supported input when
advertised by upstream. We do **not** infer an image URL from a PAE JSON URL.

Source: [EMBL-EBI / PDBe announcement](https://www.ebi.ac.uk/pdbe/news/breaking-changes-afdb-predictions-api).
For live schemas use the [AlphaFold DB API reference](https://alphafold.ebi.ac.uk/api-doc).

## UniProt isoforms and long-protein fragments

The `/prediction/<accession>` response can contain multiple entries.

- If the entries have UniProt accession labels, the client selects the entry
  with `uniprotAccession` exactly equal to the requested identifier (including
  any isoform suffix). It does not silently substitute a different isoform.
- If labelled entries exist but none matches, the client returns no prediction.
- For historical responses without any accession labels, the client retains
  the first-entry fallback needed by recorded regression fixtures.
- When multiple **fragments** share the same UniProt accession, the current
  client still takes the first matching record. That is *not* verified
  full-length fragment selection. See `LIMITATIONS.md` L8.

The existing `get_protein_structure` output keys (`entry_id`, `sequence`,
`sequence_length`, `file_urls`) are preserved for MCP clients.

**Do not** equate PDB/fragment-local residue numbers with full-length UniProt
positions without an explicit mapping. `pLDDT` measures prediction confidence,
not experimental validation.

## What was tested, and what was not

Regression tests cover modern-only metadata, mixed modern/legacy metadata,
legacy fallback, exact-isoform selection, mismatched labels, and structure
tool responses. The standard CI suite uses recorded/mocked upstream payloads.

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
