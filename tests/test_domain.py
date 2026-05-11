# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Unit tests for domain types — pure Python, no I/O."""
from __future__ import annotations

import pytest

from alphafold_sovereign.domain.disease import (
    DiseaseRecord,
    EvidenceType,
    OntologyTerm,
    PathogenicityClass,
    PhenotypeAssociation,
    PopulationFrequency,
    TargetEvidenceScore,
    VariantReport,
)


@pytest.mark.unit
def test_pathogenicity_class_values() -> None:
    assert PathogenicityClass.PATHOGENIC == "Pathogenic"
    assert PathogenicityClass.BENIGN == "Benign"
    assert isinstance(PathogenicityClass.UNCERTAIN, str)


@pytest.mark.unit
def test_evidence_type_values() -> None:
    assert EvidenceType.GENETIC_ASSOCIATION == "genetic_association"
    assert EvidenceType.KNOWN_DRUG == "known_drug"


@pytest.mark.unit
def test_ontology_term_construction() -> None:
    term = OntologyTerm(
        id="MONDO:0007254",
        label="breast carcinoma",
        description="A malignant tumor of the breast.",
        synonyms=("breast cancer", "mammary carcinoma"),
        xrefs=("ICD10:C50", "OMIM:114480"),
        namespace="MONDO",
    )
    assert term.id == "MONDO:0007254"
    assert term.label == "breast carcinoma"
    assert "breast cancer" in term.synonyms
    assert "ICD10:C50" in term.xrefs


@pytest.mark.unit
def test_ontology_term_frozen() -> None:
    """OntologyTerm is immutable (frozen dataclass)."""
    term = OntologyTerm(id="HP:0001250", label="Seizure")
    with pytest.raises((AttributeError, TypeError)):
        term.label = "Modified"  # type: ignore[misc]


@pytest.mark.unit
def test_ontology_term_defaults() -> None:
    term = OntologyTerm(id="GO:0005515", label="protein binding")
    assert term.description == ""
    assert term.synonyms == ()
    assert term.xrefs == ()
    assert term.namespace == ""


# ── to_dict serialisation ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_ontology_term_to_dict() -> None:
    """OntologyTerm.to_dict() must surface every field."""
    term = OntologyTerm(
        id="MONDO:0007254",
        label="breast carcinoma",
        description="A malignant tumor of the breast.",
        synonyms=("breast cancer", "mammary carcinoma"),
        xrefs=("ICD10:C50", "OMIM:114480"),
        namespace="MONDO",
        obsolete=False,
    )
    d = term.to_dict()
    assert d == {
        "id": "MONDO:0007254",
        "label": "breast carcinoma",
        "description": "A malignant tumor of the breast.",
        "synonyms": ["breast cancer", "mammary carcinoma"],
        "xrefs": ["ICD10:C50", "OMIM:114480"],
        "namespace": "MONDO",
        "obsolete": False,
    }


@pytest.mark.unit
def test_disease_record_to_dict() -> None:
    rec = DiseaseRecord(
        mondo_id="MONDO:0004995",
        name="coronary artery disease",
        synonyms=("CAD",),
        definition="Narrowing of coronary arteries.",
        icd10_codes=("I25.10",),
        icd11_codes=("BA80",),
        omim_ids=("608901",),
        orphanet_ids=("ORPHA:1000",),
        mesh_ids=("D003324",),
        doid_ids=("DOID:3393",),
        hpo_terms=("HP:0001658",),
        parent_mondo_ids=("MONDO:0005267",),
        child_mondo_ids=("MONDO:0005010",),
        prevalence="Common",
        inheritance=("Multifactorial",),
    )
    d = rec.to_dict()
    # All declared keys present
    assert d["mondo_id"] == "MONDO:0004995"
    assert d["name"] == "coronary artery disease"
    assert d["synonyms"] == ["CAD"]
    assert d["definition"] == "Narrowing of coronary arteries."
    assert d["icd10_codes"] == ["I25.10"]
    assert d["icd11_codes"] == ["BA80"]
    assert d["omim_ids"] == ["608901"]
    assert d["orphanet_ids"] == ["ORPHA:1000"]
    assert d["mesh_ids"] == ["D003324"]
    assert d["doid_ids"] == ["DOID:3393"]
    assert d["hpo_terms"] == ["HP:0001658"]
    assert d["parent_mondo_ids"] == ["MONDO:0005267"]
    assert d["child_mondo_ids"] == ["MONDO:0005010"]
    assert d["prevalence"] == "Common"
    assert d["inheritance"] == ["Multifactorial"]


@pytest.mark.unit
def test_phenotype_association_to_dict() -> None:
    assoc = PhenotypeAssociation(
        hpo_id="HP:0001250",
        hpo_label="Seizure",
        mondo_id="MONDO:0005027",
        disease_name="epilepsy",
        gene_symbol="SCN1A",
        uniprot_id="P35498",
        frequency="HP:0040281",
        onset="Childhood onset",
        evidence_codes=("IEA",),
        references=("PMID:12345",),
    )
    d = assoc.to_dict()
    assert d == {
        "hpo_id": "HP:0001250",
        "hpo_label": "Seizure",
        "mondo_id": "MONDO:0005027",
        "disease_name": "epilepsy",
        "gene_symbol": "SCN1A",
        "uniprot_id": "P35498",
        "frequency": "HP:0040281",
        "onset": "Childhood onset",
        "evidence_codes": ["IEA"],
        "references": ["PMID:12345"],
    }


@pytest.mark.unit
def test_target_evidence_score_to_dict() -> None:
    score = TargetEvidenceScore(
        target_ensembl_id="ENSG00000141510",
        target_gene_symbol="TP53",
        uniprot_id="P04637",
        disease_mondo_id="MONDO:0007254",
        disease_name="breast carcinoma",
        overall_score=0.823456,
        genetic_association=0.91,
        somatic_mutation=0.55,
        known_drug=0.10,
        affected_pathway=0.20,
        literature=0.40,
        animal_model=0.30,
        rna_expression=0.15,
        drug_count=4,
        tractable=True,
    )
    d = score.to_dict()
    assert d["target_ensembl_id"] == "ENSG00000141510"
    assert d["target_gene_symbol"] == "TP53"
    assert d["uniprot_id"] == "P04637"
    assert d["disease_mondo_id"] == "MONDO:0007254"
    assert d["disease_name"] == "breast carcinoma"
    # round(0.823456, 4) -> 0.8235
    assert d["overall_score"] == round(0.823456, 4)
    assert d["evidence_scores"] == {
        "genetic_association": round(0.91, 4),
        "somatic_mutation": round(0.55, 4),
        "known_drug": round(0.10, 4),
        "affected_pathway": round(0.20, 4),
        "literature": round(0.40, 4),
        "animal_model": round(0.30, 4),
        "rna_expression": round(0.15, 4),
    }
    assert d["drug_count"] == 4
    assert d["tractable"] is True


@pytest.mark.unit
def test_population_frequency_to_dict() -> None:
    pf = PopulationFrequency(
        population="nfe",
        allele_count=12,
        allele_number=140000,
        allele_frequency=8.57e-5,
        homozygote_count=0,
    )
    d = pf.to_dict()
    assert d == {
        "population": "nfe",
        "allele_count": 12,
        "allele_number": 140000,
        "allele_frequency": 8.57e-5,
        "homozygote_count": 0,
    }


@pytest.mark.unit
def test_variant_report_to_dict_full() -> None:
    """to_dict() must include every nested block and call children's to_dict()."""
    pf = PopulationFrequency(
        population="nfe",
        allele_count=1,
        allele_number=100000,
        allele_frequency=1e-5,
    )
    disease = DiseaseRecord(mondo_id="MONDO:0007254", name="breast carcinoma")
    target = TargetEvidenceScore(
        target_ensembl_id="ENSG00000012048",
        target_gene_symbol="BRCA1",
        uniprot_id="P38398",
        disease_mondo_id="MONDO:0007254",
        disease_name="breast carcinoma",
        overall_score=0.9,
    )
    report = VariantReport(
        hgvs="BRCA1:c.181T>G",
        gene_symbol="BRCA1",
        uniprot_id="P38398",
        residue_position=61,
        reference_aa="C",
        alternate_aa="G",
        structure_available=True,
        plddt_at_residue=85.0,
        mean_pae_neighborhood=4.2,
        predicted_functional_impact="Disrupts zinc-binding RING domain",
        alphamissense_score=0.85,
        alphamissense_class="likely_pathogenic",
        clinvar_classification=PathogenicityClass.PATHOGENIC,
        clinvar_review_status="reviewed by expert panel",
        clinvar_variation_id="55480",
        clinvar_conditions=("Breast-ovarian cancer, familial 1",),
        gnomad_af_global=1e-5,
        gnomad_af_by_population=(pf,),
        gnomad_loeuf=0.5,
        top_diseases=(disease,),
        top_target_evidence=(target,),
        sources_queried=("clinvar", "gnomad"),
        data_version="2026-01",
    )
    d = report.to_dict()
    # Top-level scalar fields
    assert d["hgvs"] == "BRCA1:c.181T>G"
    assert d["gene_symbol"] == "BRCA1"
    assert d["uniprot_id"] == "P38398"
    assert d["residue_position"] == 61
    assert d["reference_aa"] == "C"
    assert d["alternate_aa"] == "G"
    # Aggregate tier — Pathogenic clinvar should be HIGH
    assert d["pathogenicity_tier"] == "HIGH"
    # Nested structure block
    assert d["structure"] == {
        "available": True,
        "plddt_at_residue": 85.0,
        "mean_pae_neighborhood": 4.2,
        "predicted_functional_impact": "Disrupts zinc-binding RING domain",
    }
    # Nested pathogenicity block
    assert d["pathogenicity"]["alphamissense_score"] == 0.85
    assert d["pathogenicity"]["alphamissense_class"] == "likely_pathogenic"
    assert d["pathogenicity"]["clinvar_classification"] == "Pathogenic"
    assert d["pathogenicity"]["clinvar_review_status"] == "reviewed by expert panel"
    assert d["pathogenicity"]["clinvar_variation_id"] == "55480"
    assert d["pathogenicity"]["clinvar_conditions"] == [
        "Breast-ovarian cancer, familial 1"
    ]
    # Nested population_genetics block
    assert d["population_genetics"]["gnomad_af_global"] == 1e-5
    assert d["population_genetics"]["gnomad_loeuf"] == 0.5
    assert d["population_genetics"]["gnomad_af_by_population"] == [pf.to_dict()]
    # Disease + target lists run children's to_dict()
    assert d["top_diseases"] == [disease.to_dict()]
    assert d["top_target_evidence"] == [target.to_dict()]
    # Provenance
    assert d["provenance"] == {
        "sources_queried": ["clinvar", "gnomad"],
        "data_version": "2026-01",
    }


# ── pathogenicity_tier branch coverage ────────────────────────────────────────


def _mk_variant(
    *,
    clinvar: PathogenicityClass = PathogenicityClass.NOT_PROVIDED,
    am: float | None = None,
) -> VariantReport:
    """Build a minimal VariantReport for tier-classification tests."""
    return VariantReport(
        hgvs="X:c.1A>G",
        gene_symbol="X",
        uniprot_id="P00000",
        residue_position=1,
        reference_aa="M",
        alternate_aa="V",
        clinvar_classification=clinvar,
        alphamissense_score=am,
    )


@pytest.mark.unit
def test_pathogenicity_tier_high_from_clinvar_pathogenic() -> None:
    v = _mk_variant(clinvar=PathogenicityClass.PATHOGENIC)
    assert v.pathogenicity_tier() == "HIGH"


@pytest.mark.unit
def test_pathogenicity_tier_high_from_clinvar_likely_pathogenic() -> None:
    v = _mk_variant(clinvar=PathogenicityClass.LIKELY_PATHOGENIC)
    assert v.pathogenicity_tier() == "HIGH"


@pytest.mark.unit
def test_pathogenicity_tier_high_from_alphamissense() -> None:
    """AlphaMissense >= 0.564 yields HIGH when ClinVar is not pathogenic."""
    v = _mk_variant(clinvar=PathogenicityClass.NOT_PROVIDED, am=0.6)
    assert v.pathogenicity_tier() == "HIGH"


@pytest.mark.unit
def test_pathogenicity_tier_high_from_alphamissense_boundary() -> None:
    """The 0.564 boundary itself should be HIGH (>= is inclusive)."""
    v = _mk_variant(clinvar=PathogenicityClass.NOT_PROVIDED, am=0.564)
    assert v.pathogenicity_tier() == "HIGH"


@pytest.mark.unit
def test_pathogenicity_tier_low_from_clinvar_benign() -> None:
    v = _mk_variant(clinvar=PathogenicityClass.BENIGN)
    assert v.pathogenicity_tier() == "LOW"


@pytest.mark.unit
def test_pathogenicity_tier_low_from_alphamissense() -> None:
    """AlphaMissense <= 0.34 yields LOW when no benign ClinVar."""
    v = _mk_variant(clinvar=PathogenicityClass.NOT_PROVIDED, am=0.2)
    assert v.pathogenicity_tier() == "LOW"


@pytest.mark.unit
def test_pathogenicity_tier_low_from_alphamissense_boundary() -> None:
    """The 0.34 boundary should be LOW (<= is inclusive)."""
    v = _mk_variant(clinvar=PathogenicityClass.NOT_PROVIDED, am=0.34)
    assert v.pathogenicity_tier() == "LOW"


@pytest.mark.unit
def test_pathogenicity_tier_medium_from_clinvar_uncertain() -> None:
    v = _mk_variant(clinvar=PathogenicityClass.UNCERTAIN)
    assert v.pathogenicity_tier() == "MEDIUM"


@pytest.mark.unit
def test_pathogenicity_tier_unknown_fallthrough() -> None:
    """No ClinVar signal, AlphaMissense in grey zone -> UNKNOWN."""
    v = _mk_variant(clinvar=PathogenicityClass.NOT_PROVIDED, am=0.45)
    assert v.pathogenicity_tier() == "UNKNOWN"


@pytest.mark.unit
def test_pathogenicity_tier_unknown_no_data() -> None:
    """All defaults — no ClinVar, no AlphaMissense — falls through to UNKNOWN."""
    v = _mk_variant()
    assert v.pathogenicity_tier() == "UNKNOWN"
