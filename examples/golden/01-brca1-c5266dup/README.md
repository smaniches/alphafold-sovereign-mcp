# Golden example 01 — BRCA1 c.5266dupC

A germline **loss-of-function founder allele**: the pipeline's clinical call
rests on the ClinVar expert-panel classification plus PVS1 null-variant logic.

## Canonical identity

| Field | Value | Source |
|-------|-------|--------|
| Gene | BRCA1 (17q21.31, minus strand) | — |
| Protein (UniProt) | P38398 | — |
| RefSeq transcript | NM_007294.4 (MANE Select); protein NP_009225.1 | ClinVar VCV000017677; dbSNP |
| cDNA HGVS | **NM_007294.4:c.5266dup** (canonical) | ClinVar |
| Legacy synonyms | c.5266dupC; genomic name **5382insC** | Ewald 2011 [3] |
| Protein HGVS | NP_009225.1:p.Gln1756ProfsTer74 (aggregate short form p.Gln1756fs) | ClinVar |
| Genomic (GRCh38) | NC_000017.11:g.43057065dup | dbSNP rs80357906 |
| Genomic (GRCh37) | NC_000017.10:g.41209082dup | dbSNP rs80357906 |
| dbSNP | rs80357906 | dbSNP |
| ClinVar | **VCV000017677** (Variation ID 17677) | ClinVar |

The input to the pipeline is the legacy spelling `BRCA1:c.5266dupC` — the form a
clinician is most likely to type, since this allele was known for years as
5382insC.

## Established significance (ground truth)

BRCA1 c.5266dupC is **Pathogenic** and is one of the most firmly established
pathogenic variants in clinical genetics. ClinVar aggregates it as Pathogenic
at the **reviewed-by-expert-panel** tier (3 gold stars), the expert-panel
assertion coming from the ENIGMA BRCA1/2 consortium. It is one of the three
classic Ashkenazi Jewish founder mutations — alongside BRCA1 185delAG
(c.68_69delAG) and BRCA2 6174delT — and recurs in many non-Ashkenazi
populations [1, 2, 3, 4]. It causes autosomal-dominant Hereditary Breast and
Ovarian Cancer (HBOC); biallelic loss causes Fanconi anemia complementation
group S.

**Mechanism.** Duplication of one C shifts the reading frame at codon 1756
(Gln→Pro) and introduces a premature termination codon 74 residues downstream.
The transcript carries a PTC far upstream of the natural stop (BRCA1 is
1863 aa), so it is a nonsense-mediated-decay substrate; any escaping protein
loses the C-terminal tandem BRCT domains that mediate the homologous-
recombination DNA-damage response — i.e. BRCA1 loss of function. Under the
ACMG/AMP 2015 framework [5] this is the textbook basis for **PVS1** (a null
variant in a gene where LoF is an established disease mechanism, upstream of the
last exon so NMD is predicted).

**Actionability.** Germline BRCA1 LoF creates homologous-recombination
deficiency and synthetic lethality with PARP inhibition; olaparib is approved
for germline *BRCA*-mutated HER2-negative metastatic breast cancer (OlympiAD,
HR 0.58 for PFS) [6].

## What the pipeline reported

From [`expected.json`](expected.json), captured through the live pipeline on the
recorded fixtures:

| Field | Value |
|-------|-------|
| `clinical_tier` | **HIGH** |
| `clinvar` | found, **Pathogenic**, variation_id **17677**, *reviewed by expert panel* |
| `functional_consequence` | `frameshift_variant`, impact **HIGH** |
| `acmg_criteria_draft` | **PVS1** (null variant, LoF mechanism) · **PP5** (ClinVar reputable source) |
| `population_genetics.alphamissense_score` | `null` (`alphamissense: no_data`) |
| `disease_associations` (Open Targets) | breast cancer (MONDO:0007254); HBOC (Orphanet:145); Fanconi anemia group S (MONDO:0054748) |
| `data_sources_status` | ensembl_vep ok · clinvar ok · open_targets ok · disgenet ok · gnomad **skipped** · chembl no_data · alphamissense **no_data** |

## Concordance analysis

| Dimension | Ground truth | Pipeline | Verdict |
|-----------|--------------|----------|---------|
| Clinical significance | Pathogenic (ENIGMA expert panel) | Pathogenic, VCV000017677, expert panel | ✅ **Concordant** |
| Molecular consequence | frameshift → NMD / LoF | `frameshift_variant`, HIGH impact | ✅ Concordant |
| ACMG null-variant logic | PVS1 applies [5] | PVS1 emitted | ✅ Concordant |
| Disease | HBOC (breast/ovarian), Fanconi S | breast cancer, HBOC, Fanconi group S | ✅ Concordant |
| Overall tier | Pathogenic | HIGH | ✅ Concordant |

**Faithful absences, not errors.** AlphaMissense reports `no_data` because it
scores missense substitutions only — a frameshift is out of its domain, so the
honest output is no score, not a fabricated one. gnomAD is **skipped**: the
pipeline could not construct a gnomAD variant ID from the frameshift VEP record,
so no population frequency is shown even though this founder allele does carry a
low gnomAD frequency — a known pipeline limitation (recorded here, not hidden),
not a scientific misstatement. DisGeNET returns HTTP 401 in the fixture because
the public endpoint requires an API key; a keyless default deployment sees
exactly this, and the report proceeds without DisGeNET associations.

**This example also demonstrates a fix.** Before
`fix(clinvar): resolve the exact variant record, not an arbitrary search hit`,
the ClinVar resolver ranked candidates by a raw substring match that the legacy
`c.5266dupC` spelling (vs. ClinVar's canonical `c.5266dup`) defeated, returning
an unrelated single-submitter VUS and reporting this allele as "Uncertain
significance / UNKNOWN." Exercising this canonical variant is what surfaced the
defect; the fixture here was recorded after the fix, which is why it resolves
correctly to the expert-panel Pathogenic record.

## Provenance & reproduction

`cassette.json` holds every upstream request/response captured live from the
public APIs, each with a SHA-256 of its body. The golden test replays them
offline and asserts this exact output. To regenerate intentionally:
`uv run python scripts/record_golden_examples.py`.

The pipeline output is a computation over public data. It is **not** a clinical
determination: `generate_variant_clinical_report` is a research aid, and its
ACMG draft explicitly requires review by a clinical geneticist before any
clinical use.

## References

1. Struewing JP et al. *The risk of cancer associated with specific mutations of BRCA1 and BRCA2 among Ashkenazi Jews.* N Engl J Med 1997. PMID 9145676; doi:10.1056/NEJM199705153362001.
2. Lavie O et al. *Double heterozygosity in the BRCA1 and BRCA2 genes in the Jewish population.* Ann Oncol 2010. PMID 20924075; doi:10.1093/annonc/mdq460.
3. Ewald IP et al. *Prevalence of the BRCA1 founder mutation c.5266dup in Brazilian individuals at-risk for the hereditary breast and ovarian cancer syndrome.* Hered Cancer Clin Pract 2011. PMID 22185575; doi:10.1186/1897-4287-9-12.
4. Manchanda R et al. *Randomised trial of population-based BRCA testing in Ashkenazi Jews: long-term outcomes.* BJOG 2019. PMID 31507061; doi:10.1111/1471-0528.15905.
5. Richards S et al. *Standards and guidelines for the interpretation of sequence variants: a joint consensus recommendation of the ACMG and AMP.* Genet Med 2015. PMID 25741868; doi:10.1038/gim.2015.30.
6. Robson M et al. *Olaparib for Metastatic Breast Cancer in Patients with a Germline BRCA Mutation (OlympiAD).* N Engl J Med 2017. PMID 28578601; doi:10.1056/NEJMoa1706450.
