# Known Limitations

This document enumerates the specific, named limitations of the project
as maintained in the latest repository revision. It complements ``STATUS.md`` (which gives the
high-level posture) by listing concrete, addressable items.

If you find a limitation that is not listed here, please open an issue
labelled ``limitation``.

---

## L1 — ACMG criterion mapping is not independently validated

**Module:** ``src/alphafold_sovereign/tools/precision_medicine.py``
(``_vep_to_acmg``, ``_unassessed_evidence``, and related helpers).

**Description:** The mapping from VEP consequence terms onto candidate
ACMG criteria (PVS1, BP7) is implemented from a reading of Richards et
al. 2015 by the project author. No clinical geneticist has signed off on
it. gnomAD allele frequencies and predictor outputs (AlphaMissense, SIFT,
PolyPhen) are not mapped onto criteria: they are returned as
observations with BA1, BS1, PM2, PP3 and BP4 marked ``NOT_ASSESSED``,
because those criteria depend on disorder-specific frequency thresholds
and predictor-specific calibration that this project does not evaluate.
CADD is not retrieved: the server does not request it from Ensembl VEP,
and ``cadd_phred`` is always null with a ``NOT_RETRIEVED`` note.

**Impact:** Computational evidence could be mistaken for established
clinical criteria if source attribution or the unassessed state is lost.
The corrected ``classify_variant_acmg`` output no longer issues a
pathogenicity classification without disease-specific verification.
The multi-source clinical report remains a research aid, not a clinical call.

**Mitigation:** Preserve the separate source data and unreviewed candidate
signals. Determine disease mechanism and clinical criteria from primary
sources under qualified independent review.

**Planned resolution:** Roadmap step 2 (traceability matrix) and step 3
(external review). See ``STATUS.md``.

---

## L2 — Druggability tier thresholds are unvalidated heuristics

**Module:** ``src/alphafold_sovereign/domain/druggability.py``
(``score_target_druggability``), surfaced by
``src/alphafold_sovereign/tools/precision_medicine.py``
(``_druggability_tier``).

**Description:** The mapping from (``drug_count``, ``tractability``,
``LOEUF``, ``pLDDT``) to (HOT, WARM, COLD, NOT_DRUGGABLE) uses
integer score cut-offs (≥4, ≥2, ≥1, 0) chosen by the author. The
score itself is the sum of small literature-informed weights. No
calibration against a benchmark of approved-drug vs. failed-drug
targets has been performed. The weights and cut-offs are now named,
documented constants in the pure ``domain/druggability.py`` module so
they can be inspected and, in future, re-calibrated without touching
the tool orchestration.

**Impact:** A target classified as HOT here may not be druggable in
practice. A target classified as COLD here may have an approved drug.

**Mitigation:** Use the tier only as a triage signal alongside expert
review. To make the *strength* of each call legible, the
``scoring_breakdown`` now also reports data completeness
(``signals.available`` / ``signals.missing``), a ``confidence`` grade,
and a ``borderline`` flag — so a HOT that rests on two of four signals
and sits one point from WARM is no longer indistinguishable from a
fully-evidenced HOT. These fields describe the *evidence base*, not the
scientific validity of the cut-offs, which remain uncalibrated.

**Planned resolution:** Roadmap step 4 (benchmark calibration).

---

## L3 — Upstream API schemas are not pinned

**Modules:** all of ``src/alphafold_sovereign/clients/``.

**Description:** We call live APIs (Ensembl REST, Open Targets GraphQL,
ClinVar VCV JSON, gnomAD GraphQL, AlphaFold DB, MONDO, HPO, DisGeNET,
ChEMBL) at their current schema. If an upstream changes shape,
serialisation may break.

**Impact:** Reproducibility is limited. A run today may produce
different results from a run a year from now.

**Mitigation:** Client-level parsing, selected Pydantic input models,
and synthetic source-response regression tests limit some schema risks.
The former real-API replay fixtures are historical Git artifacts, not
active tests or independently validated scientific reference cases.
These measures are not a full schema contract for every upstream and
cannot rule out silent data drift. AlphaFold prediction-field renames are
handled explicitly; see `docs/afdb-compatibility.md`.

**Planned resolution:** Roadmap step 5 (schema pinning with refresh
policy).

---

## L4 — No production deployment experience

**Description:** This server has never been run for real users in a
long-lived process. We do not know the actual memory footprint of the
SQLite knowledge graph after a month of use, the actual rate of
upstream 429 throttling, or the actual latency of the slowest tool.

**Impact:** Performance and reliability claims should be assumed to be
"works on a laptop" rather than "works at scale".

**Mitigation:** ``CircuitBreaker`` and ``UpstreamConfig`` provide
defensive primitives, but they have only been tested in unit tests
with mocked time.

**Planned resolution:** First real deployment will produce real
observations to publish back to this document.

---

## L5 — macOS Python 3.11 test flake

**Description:** On the GitHub Actions ``macos-latest`` runner with
Python 3.11, the test suite has intermittently failed even though
identical code passes on every other matrix entry. The failure is
non-deterministic; the root cause has not been isolated.

**Impact:** CI may be red on a benign push.

**Mitigation:** The CI test step retries the run once **only** on the
``macos-latest`` / Python 3.11 matrix entry; every other entry fails fast.
A one-off timing flake therefore clears automatically, while a genuine
consistent failure still reds the build (it is not masked).

**Planned resolution:** The matrix entry is now stabilised via the scoped
retry above. Isolating the specific timing-sensitive test for a deeper fix
remains a follow-up if the flake recurs.

---

## L6 — Single-maintainer bus factor

**Description:** This is currently a single-person project. There is
no co-maintainer, no governance body, and no funded continuity plan.

**Impact:** If the maintainer becomes unavailable, the project stalls.

**Mitigation:** The Apache 2.0 licence ensures any user can fork; the
code is small enough (3,145 statements as of v1.2.0, verified via
`pytest --cov`) to be picked up by a reasonably motivated successor.

**Planned resolution:** Recruit co-maintainers (see
``GOVERNANCE.md``).

---

## L7 — No telemetry on real-world correctness

**Description:** We do not collect any data on tool invocations,
arguments, or outputs from users. We therefore cannot say "in N
real-world variant reports, the ACMG call agreed with a geneticist M%
of the time."

**Impact:** Quality claims are based on unit tests, not field data.

**Mitigation:** None for this release. Intentional — we will not add
telemetry without explicit opt-in.

**Planned resolution:** An opt-in, locally-stored "quality journal"
that lets users mark each report as "matches expert / disagrees /
unsure", aggregated only with explicit upload consent.

---

## L8 — AlphaFold fragment selection and residue numbering

**Module:** `src/alphafold_sovereign/clients/alphafold.py` and
`src/alphafold_sovereign/tools/structure_intelligence.py`.

**Description:** AlphaFold DB may provide multiple predicted fragments for
very long sequences. The client selects the exact requested UniProt
accession over different isoforms, but where multiple fragments share that
accession it currently uses the first returned match. The tool does not
offer a fragment selector, a verified mapping from fragment indices to
full-length UniProt residues, or an experimental PDB/SIFTS mapping.

**Impact:** A model's reported sequence and confidence may cover only a
fragment, so users must not interpret the fragment's residue positions or
sequence length as an unambiguous full-length protein coordinate system.

**Mitigation:** Resolve a specific model/fragment through the upstream
AlphaFold DB record before interpreting residue positions; retain source
model identifiers in downstream research records. The server currently
does not project text-mined residue annotations onto model coordinates.

**Planned resolution:** Document and test the precise fragment-selection
and residue-coordinate contract against live AFDB examples before adding
a fragment-specific tool parameter or any literature-annotation join.

---

## L9 — PDBe/IUCr literature evidence is source-reported, not independently mapped

**Module:** `src/alphafold_sovereign/clients/pdbe_literature.py` and the optional
`generate_variant_clinical_report` literature section.

The client calls PDBe's documented UniProt residue API, checks the identity
reported with each annotation, and returns the upstream PDB chain/residue,
UniProt residue, article identifiers and AI-extracted sentence. It does not
recompute SIFTS, verify that caller-provided coordinates match the HGVS
variant's transcript/isoform, or retrieve experimental model-quality
metrics. Text-mined mentions can describe wild-type function, unrelated
substitutions, or false positives. Missing or inaccessible publications
may produce no annotations. API errors are marked unavailable, not absent.

**Mitigation:** Do not score or classify variants from this evidence. Verify
exact residue mapping, the original publication, experimental source
structures and variant context before scientific interpretation. The default
report remains unchanged unless the literature option is explicitly set.

---

## L10 — Positions of locally elevated PAE are not domain boundaries

**Module:** `src/alphafold_sovereign/tools/structure_intelligence.py`
(`_local_high_pae_onsets`, surfaced by `analyze_structural_confidence`).

**Description:** `analyze_structural_confidence` reports
`local_high_pae.positions`: zero-based model indices where the mean PAE of a
20×20 block on the diagonal of the PAE matrix exceeds the mean of the whole
matrix by more than 1.5 standard deviations of that statistic. The block lies
on the diagonal, so the statistic describes uncertainty among sequence
neighbours. Uncertainty between two confidently predicted regions lies off the
diagonal and is not measured. Releases up to 1.5.12 returned the same positions
as `domain_boundaries.candidate_positions` and derived `n_putative_domains`
from their number.

In an internal, AI-assisted audit of 18 AlphaFold DB models (November 2026; not
an independent validation) the statistic returned seven positions in total,
each within 15 residues of a chain terminus.
For the eight proteins with two or more UniProtKB Domain features (SRC, ABL1,
GRB2, CRK, PTPN11, CALM1, ALB, BRCA1) it marked no border between two annotated
domains: seven models returned no position, and ALB returned one, three
residues before its first domain. None of the nine models whose mean PAE was
11.9 Å or more returned a position: an index is flagged only where a diagonal
block exceeds the whole-matrix mean, and that mean rises with the overall PAE.

**Impact:** The earlier field names presented these positions as domain
boundaries and as a domain count. They are neither. An empty list does not
indicate a single-domain protein, and a listed position does not indicate a
domain border.

**Mitigation:** The positions are reported under `local_high_pae` together with
their definition. The legacy `domain_boundaries` block is kept so that existing
clients still find its keys, with `status: "NOT_ASSESSED"`, an empty
`candidate_positions` list and `n_putative_domains: null`. The last two are the
values the block already took in earlier releases when no PAE matrix was
available.
Use curated domain annotations, such as InterPro or the UniProtKB Domain
features, for domains.

**Planned resolution:** None scheduled. Segmenting a PAE matrix into domains
would be a new method that needs its own validation against curated
annotations.

---

## L11 — Core-residue clusters are not validated binding pockets

**Module:** `src/alphafold_sovereign/tools/structure_intelligence.py`
(`_cluster_core_residues`, `_geometry_score`, surfaced by
`score_binding_pocket_geometry`).

**Description:** `score_binding_pocket_geometry` takes the Cα atoms closer to
the model centroid than the 60th percentile of centroid distances, groups them
greedily into clusters of 8 Å radius, and scores each cluster from its residue
count, radius of gyration, mean pLDDT and distance from the model centroid. It
computes no cavity, solvent-accessible surface or ligand contact. Releases up
to 1.5.12 called the clusters putative pockets, called the score a
druggability index, and attached an `EXCELLENT`, `GOOD`, `MODERATE` or `POOR`
label to it.

In the same internal audit, on 19 AlphaFold DB models, all 189 reported
clusters were labelled `EXCELLENT` (133) or `GOOD` (56): every one scored 55
or more, the lower edge of `GOOD`, on the 0 to 100 scale. The reference
was the PDBe-KB ligand-site residues of each protein, for ligands of at least
10 atoms, contacted in at least 20% of the ligand records. The top-ranked
cluster was enriched for that site in 4 of the 18 proteins that had one (CDK2,
ADA, AKR1B1, HRAS; empirical p < 0.05 against 2,000 random residue sets of the
same size, not corrected for the number of proteins) and shared no residue with
it in 9. The clusters of a protein together covered 53 to 60% of its residues
and, on average, 85% of its reference-site residues, so they do not localise a
site.

**Impact:** The labels did not discriminate, and a top-ranked cluster is
usually not a known ligand site. Reading the output as pocket detection or as a
druggability assessment is not supported.

**Mitigation:** The output names the clusters `core_residue_clusters` and the
score `geometry_score`, and carries `assessment_status`, `methodology` and
`note` fields that state what is computed. The earlier keys remain as
deprecated aliases so that existing clients keep working: `putative_pockets`
lists the same clusters in the earlier entry shape (`pocket_id`,
`druggability_index`, `druggability_components`) with the same numbers, and
`n_pockets_found` repeats the cluster count. In those entries
`druggability_label` is `NOT_ASSESSED`. `deprecated_aliases` maps each earlier
key to its current name. The numbers themselves are unchanged. To locate
binding sites, use a dedicated pocket-detection method and experimental
evidence.

**Planned resolution:** None scheduled. A validated pocket detector would be
new work. Removing the deprecated aliases is a decision for a future major
version.

---

## L12 — The Cα topology vector holds at most 16 statistics and is not a validated similarity measure

**Module:** `src/alphafold_sovereign/tools/structure_intelligence.py`
(`_compute_tda_fingerprint`, `_fallback_tda_fingerprint`,
`_fingerprint_distance`, surfaced by `compute_topology_fingerprint`,
`compare_proteins_topologically` and `find_evolutionary_structural_shifts`).

**Description:** With the optional `[tda]` extra, the 64-slot vector holds
eight statistics of the finite H₀ bar lifetimes and eight of the finite H₁ bar
lifetimes of a Vietoris-Rips complex on the Cα atoms, truncated at 15 Å. The
other 48 slots are always zero: H₂ is not computed, and slots 24 to 63 are
padding. Without GUDHI the vector holds eight distance and contact statistics
and no persistent homology. A model with more than 500 Cα atoms is reduced to
500 evenly spaced ones before the complex is built, so its values describe that
subsample. The distance the tools report is the L2 distance between
length-normalised vectors.

In the same internal audit (GUDHI 3.13) the Betti numbers and bar lengths were
correct on analytic point clouds and unchanged by a rigid motion.
On 23 AlphaFold DB models every vector had 16 non-zero slots, and at least
99.94% of its squared norm lay in the two total-persistence slots, so the
distance follows the difference in one ratio, total H₁ over total H₀
persistence (Spearman 0.94). Same-family pairs were closer than cross-family
pairs on average (AUC 0.98 over 22 and 231 pairs), but on that ratio 25 of the
231 cross-family pairs were closer than the median same-family pair, for
example carbonic anhydrase 1 and FABP4. All 23 models had Betti numbers
β₀ = 1 and β₁ = 0; none was longer than 500 residues. For three further
models that are, the β₁ of the subsample differed from that of the full chain:
9 against 7 for EGFR, 11 against 12 for ABL1, and 53 against 63 for BRCA1.

One precondition applies to the GUDHI path. GUDHI does not compute homology in
the highest dimension present in the complex, so if the 15-Å complex contains
no triangle, β₁ is reported as 0 whatever its true value (a square with 14-Å
sides has one loop and is reported with none), and if it contains no edge, β₀
is reported as 0. Any three consecutive residues form a triangle at this scale,
so a model of up to 500 residues is not affected. A longer, subsampled model
would be affected only if no three of its sampled Cα atoms lay within 15 Å of
one another.

**Impact:** "64 components" overstated the information in the vector. The
distance is not a measure of fold similarity, homology or function, and values
for models longer than 500 residues are not comparable with full-chain values.
The earlier description of `compare_proteins_topologically` listed possible
uses (drug-repurposing triage, off-target screening, cross-species comparison)
that no evidence supports.

**Mitigation:** The tool descriptions and outputs state the slot layout
(`fingerprint_layout`), the subsampling (`subsampled`, `n_residues_total`,
`n_residues_used`) and the method that actually ran, and the list of uses is
removed. Treat the distance as an exploratory descriptor, and confirm any
similarity with a structural alignment.

**Planned resolution:** None scheduled. Whether the persistence ratio is useful
for any task is a research question.

---

## How to add a new entry

When you find a new limitation:

1. Open a GitHub issue with the ``limitation`` label.
2. Add a new ``L<N>`` section here in the next PR. Include: module,
   description, impact, mitigation, planned resolution.
3. If the limitation rises to the level of a safety concern, also
   add a clear note in the relevant tool's docstring.

---

Last updated: 2026-11-11.
