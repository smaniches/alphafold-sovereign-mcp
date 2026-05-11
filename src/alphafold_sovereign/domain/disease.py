# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""Pure-Python domain types for disease, phenotype, variant, and evidence data.

No I/O, no network, no MCP SDK — only types, validation, and serialisation.
All downstream modules depend on these types; none depend on each other,
ensuring a dependency-free domain layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PathogenicityClass(str, Enum):
    """ClinVar / ACMG pathogenicity classification."""

    PATHOGENIC = "Pathogenic"
    LIKELY_PATHOGENIC = "Likely pathogenic"
    UNCERTAIN = "Uncertain significance"
    LIKELY_BENIGN = "Likely benign"
    BENIGN = "Benign"
    CONFLICTING = "Conflicting interpretations"
    NOT_PROVIDED = "Not provided"


class EvidenceType(str, Enum):
    """Open Targets evidence data types."""

    GENETIC_ASSOCIATION = "genetic_association"
    SOMATIC_MUTATION = "somatic_mutation"
    KNOWN_DRUG = "known_drug"
    AFFECTED_PATHWAY = "affected_pathway"
    LITERATURE = "literature"
    ANIMAL_MODEL = "animal_model"
    RNA_EXPRESSION = "rna_expression"
    REACTOME = "reactome"


@dataclass(frozen=True, slots=True)
class OntologyTerm:
    """A single term from any bio-ontology."""

    id: str
    """Compact URI, e.g. 'MONDO:0004995', 'HP:0001250', 'GO:0005515'."""

    label: str
    """Human-readable preferred label."""

    description: str = ""
    """Free-text definition."""

    synonyms: tuple[str, ...] = field(default_factory=tuple)
    """Exact / broad / narrow synonyms."""

    xrefs: tuple[str, ...] = field(default_factory=tuple)
    """Cross-references to other ontologies, e.g. ('ICD10:G40', 'OMIM:145000')."""

    namespace: str = ""
    """Ontology namespace, e.g. 'MONDO', 'HP', 'GO'."""

    obsolete: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "synonyms": list(self.synonyms),
            "xrefs": list(self.xrefs),
            "namespace": self.namespace,
            "obsolete": self.obsolete,
        }


@dataclass(frozen=True, slots=True)
class DiseaseRecord:
    """A disease entry from MONDO, enriched with cross-ontology metadata."""

    mondo_id: str
    """Canonical MONDO identifier, e.g. 'MONDO:0004995' (coronary artery disease)."""

    name: str
    synonyms: tuple[str, ...] = field(default_factory=tuple)
    definition: str = ""
    icd10_codes: tuple[str, ...] = field(default_factory=tuple)
    icd11_codes: tuple[str, ...] = field(default_factory=tuple)
    omim_ids: tuple[str, ...] = field(default_factory=tuple)
    orphanet_ids: tuple[str, ...] = field(default_factory=tuple)
    mesh_ids: tuple[str, ...] = field(default_factory=tuple)
    doid_ids: tuple[str, ...] = field(default_factory=tuple)
    hpo_terms: tuple[str, ...] = field(default_factory=tuple)
    """Associated HPO phenotype IDs."""
    parent_mondo_ids: tuple[str, ...] = field(default_factory=tuple)
    child_mondo_ids: tuple[str, ...] = field(default_factory=tuple)

    prevalence: str = ""
    """Free-text prevalence description from Orphanet if available."""

    inheritance: tuple[str, ...] = field(default_factory=tuple)
    """Inheritance mode terms, e.g. ('Autosomal dominant',)."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "mondo_id": self.mondo_id,
            "name": self.name,
            "synonyms": list(self.synonyms),
            "definition": self.definition,
            "icd10_codes": list(self.icd10_codes),
            "icd11_codes": list(self.icd11_codes),
            "omim_ids": list(self.omim_ids),
            "orphanet_ids": list(self.orphanet_ids),
            "mesh_ids": list(self.mesh_ids),
            "doid_ids": list(self.doid_ids),
            "hpo_terms": list(self.hpo_terms),
            "parent_mondo_ids": list(self.parent_mondo_ids),
            "child_mondo_ids": list(self.child_mondo_ids),
            "prevalence": self.prevalence,
            "inheritance": list(self.inheritance),
        }


@dataclass(frozen=True, slots=True)
class PhenotypeAssociation:
    """Association between an HPO phenotype term and a disease / gene."""

    hpo_id: str
    hpo_label: str
    mondo_id: str = ""
    disease_name: str = ""
    gene_symbol: str = ""
    uniprot_id: str = ""
    frequency: str = ""
    """Frequency modifier, e.g. 'HP:0040281' (Very frequent 80-99%)."""
    onset: str = ""
    evidence_codes: tuple[str, ...] = field(default_factory=tuple)
    references: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hpo_id": self.hpo_id,
            "hpo_label": self.hpo_label,
            "mondo_id": self.mondo_id,
            "disease_name": self.disease_name,
            "gene_symbol": self.gene_symbol,
            "uniprot_id": self.uniprot_id,
            "frequency": self.frequency,
            "onset": self.onset,
            "evidence_codes": list(self.evidence_codes),
            "references": list(self.references),
        }


@dataclass(frozen=True, slots=True)
class TargetEvidenceScore:
    """Open Targets association score between a target and a disease."""

    target_ensembl_id: str
    target_gene_symbol: str
    uniprot_id: str
    disease_mondo_id: str
    disease_name: str
    overall_score: float
    """0.0–1.0 composite score."""
    genetic_association: float = 0.0
    somatic_mutation: float = 0.0
    known_drug: float = 0.0
    affected_pathway: float = 0.0
    literature: float = 0.0
    animal_model: float = 0.0
    rna_expression: float = 0.0
    drug_count: int = 0
    tractable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_ensembl_id": self.target_ensembl_id,
            "target_gene_symbol": self.target_gene_symbol,
            "uniprot_id": self.uniprot_id,
            "disease_mondo_id": self.disease_mondo_id,
            "disease_name": self.disease_name,
            "overall_score": round(self.overall_score, 4),
            "evidence_scores": {
                "genetic_association": round(self.genetic_association, 4),
                "somatic_mutation": round(self.somatic_mutation, 4),
                "known_drug": round(self.known_drug, 4),
                "affected_pathway": round(self.affected_pathway, 4),
                "literature": round(self.literature, 4),
                "animal_model": round(self.animal_model, 4),
                "rna_expression": round(self.rna_expression, 4),
            },
            "drug_count": self.drug_count,
            "tractable": self.tractable,
        }


@dataclass(frozen=True, slots=True)
class PopulationFrequency:
    """gnomAD allele frequency in a population cohort."""

    population: str
    """e.g. 'nfe' (Non-Finnish European), 'afr', 'eas', 'sas', 'amr', 'fin', 'asj'."""
    allele_count: int
    allele_number: int
    allele_frequency: float
    homozygote_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "population": self.population,
            "allele_count": self.allele_count,
            "allele_number": self.allele_number,
            "allele_frequency": self.allele_frequency,
            "homozygote_count": self.homozygote_count,
        }


@dataclass(frozen=True, slots=True)
class VariantReport:
    """
    Comprehensive 3-D variant triage report.

    Fuses HGVS notation with structural context (AlphaFold),
    pathogenicity (AlphaMissense + ClinVar), population genetics
    (gnomAD), and disease evidence (Open Targets + MONDO).
    """

    hgvs: str
    """Input HGVS expression, e.g. 'BRCA1:c.181T>G'."""

    gene_symbol: str
    uniprot_id: str
    residue_position: int
    reference_aa: str
    alternate_aa: str

    # Structural context
    structure_available: bool = False
    plddt_at_residue: float | None = None
    mean_pae_neighborhood: float | None = None
    """Mean PAE of residues within 8 Å — measures local confidence of neighbourhood."""
    predicted_functional_impact: str = ""
    """High-level structural impact description."""

    # Pathogenicity
    alphamissense_score: float | None = None
    """0.0–1.0; > 0.564 likely pathogenic per AM calibration."""
    alphamissense_class: str = ""
    clinvar_classification: PathogenicityClass = PathogenicityClass.NOT_PROVIDED
    clinvar_review_status: str = ""
    clinvar_variation_id: str = ""
    clinvar_conditions: tuple[str, ...] = field(default_factory=tuple)

    # Population genetics
    gnomad_af_global: float | None = None
    gnomad_af_by_population: tuple[PopulationFrequency, ...] = field(default_factory=tuple)
    gnomad_loeuf: float | None = None
    """LOEUF constraint score for the gene (lower = more constrained)."""

    # Disease associations
    top_diseases: tuple[DiseaseRecord, ...] = field(default_factory=tuple)
    top_target_evidence: tuple[TargetEvidenceScore, ...] = field(default_factory=tuple)

    # Provenance
    sources_queried: tuple[str, ...] = field(default_factory=tuple)
    """Which upstream APIs contributed to this report."""
    data_version: str = ""

    def pathogenicity_tier(self) -> str:
        """Aggregate tier: HIGH / MEDIUM / LOW / UNKNOWN."""
        if self.clinvar_classification in (
            PathogenicityClass.PATHOGENIC,
            PathogenicityClass.LIKELY_PATHOGENIC,
        ):
            return "HIGH"
        if self.alphamissense_score is not None and self.alphamissense_score >= 0.564:
            return "HIGH"
        if self.clinvar_classification == PathogenicityClass.BENIGN:
            return "LOW"
        if self.alphamissense_score is not None and self.alphamissense_score <= 0.34:
            return "LOW"
        if self.clinvar_classification == PathogenicityClass.UNCERTAIN:
            return "MEDIUM"
        return "UNKNOWN"

    def to_dict(self) -> dict[str, Any]:
        return {
            "hgvs": self.hgvs,
            "gene_symbol": self.gene_symbol,
            "uniprot_id": self.uniprot_id,
            "residue_position": self.residue_position,
            "reference_aa": self.reference_aa,
            "alternate_aa": self.alternate_aa,
            "pathogenicity_tier": self.pathogenicity_tier(),
            "structure": {
                "available": self.structure_available,
                "plddt_at_residue": self.plddt_at_residue,
                "mean_pae_neighborhood": self.mean_pae_neighborhood,
                "predicted_functional_impact": self.predicted_functional_impact,
            },
            "pathogenicity": {
                "alphamissense_score": self.alphamissense_score,
                "alphamissense_class": self.alphamissense_class,
                "clinvar_classification": self.clinvar_classification.value,
                "clinvar_review_status": self.clinvar_review_status,
                "clinvar_variation_id": self.clinvar_variation_id,
                "clinvar_conditions": list(self.clinvar_conditions),
            },
            "population_genetics": {
                "gnomad_af_global": self.gnomad_af_global,
                "gnomad_af_by_population": [p.to_dict() for p in self.gnomad_af_by_population],
                "gnomad_loeuf": self.gnomad_loeuf,
            },
            "top_diseases": [d.to_dict() for d in self.top_diseases],
            "top_target_evidence": [e.to_dict() for e in self.top_target_evidence],
            "provenance": {
                "sources_queried": list(self.sources_queried),
                "data_version": self.data_version,
            },
        }
