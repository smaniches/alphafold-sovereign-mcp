# Golden example 03 — EGFR p.Leu858Arg (L858R)

A **somatic activating driver** — and the most epistemically interesting case.
ClinVar carries *no germline pathogenicity assertion* for L858R, so the pipeline
correctly declines to call it germline-pathogenic and falls back to
computational evidence, landing at `MEDIUM`. The variant's real importance is
somatic and therapeutic, which lies outside the germline axis this report
scores.

## Canonical identity

| Field | Value | Source |
|-------|-------|--------|
| Gene | EGFR (7p11.2, plus strand) | — |
| Protein (UniProt) | P00533 | — |
| RefSeq transcript | NM_005228.5 (MANE Select ≡ ENST00000275493); protein NP_005219.2 (1210 aa) | ClinVar VCV000016609; Ensembl |
| cDNA HGVS | **NM_005228.5:c.2573T>G** (exon 21) | ClinVar |
| Protein HGVS | NP_005219.2:p.Leu858Arg (L858R) | ClinVar |
| Genomic (GRCh38) | chr7:55,191,822 T>G (NC_000007.14:g.55191822T>G) | ClinVar VCV000016609.20 |
| dbSNP | rs121434568 | ClinVar |
| ClinVar | **VCV000016609** (Variation ID 16609) | ClinVar |

## Established significance (ground truth)

L858R is a **well-established, clinically actionable somatic driver** — one of
the two canonical EGFR-TKI-sensitizing alterations in non-small-cell lung cancer
(the other being exon-19 deletions), together accounting for the large majority
of EGFR-mutant NSCLC (L858R ≈ 40%) [7]. It was identified in the two landmark
2004 papers that linked somatic EGFR kinase-domain mutations to gefitinib
sensitivity [1, 2].

**Mechanism.** A T>G substitution replaces leucine with a bulky, positively
charged arginine at codon 858, in the **activation loop of the tyrosine-kinase
domain** (exon 21). This destabilises the inactive conformation and constitutively
activates the kinase — an oncogene-addiction driver [3].

**Actionability.** L858R is a positive predictive biomarker of sensitivity to
EGFR tyrosine-kinase inhibitors: first-generation gefitinib/erlotinib,
second-generation afatinib/dacomitinib, and third-generation osimertinib, with
first-line osimertinib established by the phase III FLAURA trial [4]. It is a
guideline-mandated molecular test in advanced lung adenocarcinoma [5].

**How ClinVar classifies it — the crux.** ClinVar does **not** give L858R a
germline *pathogenicity* classification. Its germline aggregate assertion is
**"drug response"** (EGFR-TKI response), while its clinical importance is carried
by the **somatic** classifications: somatic oncogenicity **Oncogenic**, somatic
clinical impact **Tier I (Strong)** for NSCLC. In the NCBI E-utilities summary
the germline-classification field therefore reads *not provided*.

## What the pipeline reported

From [`expected.json`](expected.json):

| Field | Value |
|-------|-------|
| `clinical_tier` | **MEDIUM** |
| `clinvar` | found, **Not provided**, variation_id **16609**, *reviewed by expert panel* |
| `functional_consequence` | `missense_variant`, MODERATE; PolyPhen `probably_damaging` (0.997); SIFT `deleterious_low_confidence` (0) |
| `population_genetics.alphamissense_score` | **0.9968** |
| `acmg_criteria_draft` | **PP3** (SIFT + PolyPhen concordant) |
| `disease_associations` (Open Targets) | non-small cell lung carcinoma (MONDO:0005233, affected-pathway evidence 0.82); lung adenocarcinoma; cancer |
| `data_sources_status` | ensembl_vep ok · clinvar ok · alphamissense ok · open_targets ok · disgenet ok · gnomad **skipped** · chembl no_data |

## Concordance analysis

| Dimension | Ground truth | Pipeline | Verdict |
|-----------|--------------|----------|---------|
| ClinVar germline **pathogenicity** | none asserted (germline field = "drug response" / not provided) | `Not provided`, VCV000016609 | ✅ **Faithful** |
| Molecular consequence | activating missense, kinase A-loop | `missense_variant`, MODERATE | ✅ Concordant |
| In-silico pathogenicity | damaging | PP3 from SIFT (deleterious) + PolyPhen (probably damaging, 0.997); AlphaMissense (0.997) independently concurs | ✅ Concordant |
| Disease | NSCLC / lung adenocarcinoma | NSCLC, lung adenocarcinoma | ✅ Concordant |
| Germline tier | no germline pathogenic basis | MEDIUM (computational only) | ✅ **Coherent** |

**Why `MEDIUM` is the correct answer here — not an under-call.** This tool
produces a *germline variant clinical report*, and its `clinical_tier` scores
germline pathogenicity evidence. For L858R that evidence is: no ClinVar germline
pathogenic classification (so no PP5), but strong, concordant in-silico
predictions — the pipeline's PP3 rests on SIFT (deleterious) and PolyPhen
(probably damaging, 0.997), with AlphaMissense (0.997) independently agreeing.
The honest result of that evidence is `MEDIUM` — "computational evidence suggests pathogenicity;
lacks expert ClinVar curation." The pipeline neither fabricates a germline
pathogenic call that ClinVar does not support, nor discards a variant that every
predictor flags as damaging. That is the coherent behaviour.

L858R's overwhelming clinical importance is **somatic and therapeutic** — Tier I
actionability, TKI sensitivity — which lives on a different axis than germline
pathogenicity and is not what this report ranks. The example is included
precisely to make that boundary explicit.

**Documented boundary.** The pipeline reads ClinVar's germline classification
and does not currently surface the somatic *oncogenicity* or *drug-response*
classifications where L858R's significance is recorded; exposing those is a
sensible future enhancement. Recorded here, not hidden. gnomAD is `skipped`
(a somatic driver, absent from population-frequency data).

## Provenance & reproduction

`cassette.json` holds every upstream request/response captured live, each with a
SHA-256 of its body; the golden test replays them offline and asserts this exact
output. Regenerate with `uv run python scripts/record_golden_examples.py`. This
is a research computation over public data, not a clinical determination.

## References

1. Lynch TJ et al. *Activating mutations in the epidermal growth factor receptor underlying responsiveness of non-small-cell lung cancer to gefitinib.* N Engl J Med 2004. PMID 15118073; doi:10.1056/NEJMoa040938.
2. Paez JG et al. *EGFR mutations in lung cancer: correlation with clinical response to gefitinib therapy.* Science 2004. PMID 15118125; doi:10.1126/science.1099314.
3. Sharma SV et al. *Epidermal growth factor receptor mutations in lung cancer.* Nat Rev Cancer 2007. PMID 17318210; doi:10.1038/nrc2088.
4. Soria JC et al. *Osimertinib in Untreated EGFR-Mutated Advanced Non-Small-Cell Lung Cancer (FLAURA).* N Engl J Med 2018. PMID 29151359; doi:10.1056/NEJMoa1713137.
5. Lindeman NI et al. *Updated Molecular Testing Guideline for the Selection of Lung Cancer Patients for Treatment With Targeted Tyrosine Kinase Inhibitors (CAP/IASLC/AMP).* J Thorac Oncol 2018. PMID 29396253; doi:10.1016/j.jtho.2017.12.001.
6. Richards S et al. *Standards and guidelines for the interpretation of sequence variants: a joint consensus recommendation of the ACMG and AMP.* Genet Med 2015. PMID 25741868; doi:10.1038/gim.2015.30.
7. Liu JY et al. *Patients with non-small cell lung cancer with the exon 21 L858R mutation: From distinct mechanisms to epidermal growth factor receptor tyrosine kinase inhibitors.* Oncol Lett 2024. PMID 39776649; doi:10.3892/ol.2024.14855.
