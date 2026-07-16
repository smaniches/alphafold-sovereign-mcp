# Golden example 02 — TP53 p.Arg175His (R175H)

A **somatic structural hotspot**: ClinVar and the AlphaMissense predictor agree,
and the pipeline reaches `HIGH` — a case where a single-predictor view (SIFT
alone) would have under-called it.

## Canonical identity

| Field | Value | Source |
|-------|-------|--------|
| Gene | TP53 (17p13.1, minus strand) | — |
| Protein (UniProt) | P04637 | — |
| RefSeq transcript | NM_000546.6 (MANE Select); protein NP_000537.3 | ClinVar VCV000012374; dbSNP |
| cDNA HGVS | **NM_000546.6:c.524G>A** (codon 175 CGC>CAC) | ClinVar |
| Protein HGVS | NP_000537.3:p.Arg175His (legacy R175H) | ClinVar |
| Genomic (GRCh38) | NC_000017.11:g.7675088C>T (minus strand: coding G>A = genomic C>T) | dbSNP rs28934578 |
| dbSNP | rs28934578 (site is multiallelic; the C>T allele encodes p.Arg175His) | dbSNP |
| ClinVar | **VCV000012374** (Variation ID 12374) | ClinVar |

## Established significance (ground truth)

TP53 R175H is **Pathogenic**, classified at the **reviewed-by-expert-panel**
tier (3 gold stars) by the ClinGen TP53 Variant Curation Expert Panel (last
evaluated 2024-09-06). It is the single most frequent TP53 missense hotspot
across human cancers and occurs both somatically and as a germline Li-Fraumeni
allele [6, 7].

**Mechanism — a structural, not a DNA-contact, mutant.** The p53 core
(DNA-binding) domain is a β-sandwich scaffold whose loops L2/L3 are held by a
tetrahedrally coordinated zinc [1]. R175H does **not** sit at a DNA contact;
instead it destabilises the domain fold — measured at ~3.0 kcal/mol, the most
destabilising of the classic hotspots R175H/C242S/R248Q/R249S/R273H [2] — so
the protein misfolds and loses sequence-specific DNA binding. This places it in
a different mechanistic class from the DNA-contact mutants R248 and R273 [3].
Because inactivation is by destabilisation rather than loss of a catalytic
contact, R175H is a candidate for pharmacological refolding/reactivation [3].
A knock-in mouse (murine R172H ≡ human R175H) shows metastatic gain-of-function
tumours in vivo [4].

## What the pipeline reported

From [`expected.json`](expected.json):

| Field | Value |
|-------|-------|
| `clinical_tier` | **HIGH** |
| `clinvar` | found, **Pathogenic**, variation_id **12374**, *reviewed by expert panel* |
| `functional_consequence` | `missense_variant`, impact MODERATE; SIFT `tolerated` (0.08); PolyPhen not returned |
| `population_genetics.alphamissense_score` | **0.9857** |
| `acmg_criteria_draft` | **PP3** (AlphaMissense 0.986 ≥ 0.564) · **PP5** (ClinVar reputable source) |
| `disease_associations` (Open Targets) | Li-Fraumeni syndrome (MONDO:0018875); hepatocellular carcinoma; head & neck squamous cell carcinoma |
| `data_sources_status` | ensembl_vep ok · clinvar ok · alphamissense ok · open_targets ok · disgenet ok · gnomad **skipped** · chembl no_data |

## Concordance analysis

| Dimension | Ground truth | Pipeline | Verdict |
|-----------|--------------|----------|---------|
| Clinical significance | Pathogenic (ClinGen TP53 VCEP) | Pathogenic, VCV000012374, expert panel | ✅ **Concordant** |
| Molecular consequence | missense, destabilising DBD | `missense_variant`, MODERATE | ✅ Concordant |
| In-silico pathogenicity | damaging | AlphaMissense 0.986 → PP3 | ✅ Concordant |
| Disease | Li-Fraumeni; broad somatic spectrum | Li-Fraumeni, HCC, HNSCC | ✅ Concordant |
| Overall tier | Pathogenic | HIGH | ✅ Concordant |

**A single predictor would have missed it.** The VEP record carries
`SIFT=tolerated (0.08)` — SIFT under-calls R175H, a known weakness for structural
(destabilising) mutants that do not perturb an obvious conserved contact. The
pipeline reports SIFT faithfully but does **not** rely on it: the `HIGH` tier
and the PP3 criterion rest on AlphaMissense (0.986) and the ClinVar expert-panel
classification, both of which correctly identify pathogenicity. This is the
value of combining predictors rather than trusting one.

**Faithful absence.** gnomAD is `skipped` — consistent with a variant that is
overwhelmingly somatic and essentially absent from population-frequency
databases; the pipeline shows no population data rather than inventing a
frequency.

## Provenance & reproduction

`cassette.json` holds every upstream request/response captured live, each with a
SHA-256 of its body; the golden test replays them offline and asserts this exact
output. Regenerate with `uv run python scripts/record_golden_examples.py`. This
is a research computation over public data, not a clinical determination.

## References

1. Cho Y et al. *Crystal structure of a p53 tumor suppressor–DNA complex: understanding tumorigenic mutations.* Science 1994. PMID 8023157; doi:10.1126/science.8023157.
2. Bullock AN et al. *Thermodynamic stability of wild-type and mutant p53 core domain.* PNAS 1997. PMID 9405613; doi:10.1073/pnas.94.26.14338.
3. Joerger AC, Fersht AR. *Structural basis for understanding oncogenic p53 mutations and designing rescue drugs.* PNAS 2006. PMID 17015838; doi:10.1073/pnas.0607286103.
4. Lang GA et al. *Gain of function of a p53 hot spot mutation in a mouse model of Li-Fraumeni syndrome.* Cell 2004. PMID 15607981; doi:10.1016/j.cell.2004.11.006.
5. Richards S et al. *Standards and guidelines for the interpretation of sequence variants: a joint consensus recommendation of the ACMG and AMP.* Genet Med 2015. PMID 25741868; doi:10.1038/gim.2015.30.
6. Bouaoun L et al. *TP53 Variations in Human Cancers: New Lessons from the IARC TP53 Database and Genomics Data.* Hum Mutat 2016. PMID 27328919; doi:10.1002/humu.23035.
7. Chiang YT et al. *The Function of the Mutant p53-R175H in Cancer.* Cancers 2021. PMID 34439241; doi:10.3390/cancers13164088.
