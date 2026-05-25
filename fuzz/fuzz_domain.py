#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Atheris fuzz target for all domain types and their serialisation."""

from __future__ import annotations

import sys

import atheris

with atheris.instrument_imports():
    from alphafold_sovereign.domain.disease import (
        DiseaseRecord,
        OntologyTerm,
        PathogenicityClass,
        PhenotypeAssociation,
        PopulationFrequency,
        TargetEvidenceScore,
        VariantReport,
    )


def _fuzz_ontology_term(fdp: atheris.FuzzedDataProvider) -> OntologyTerm:
    term = OntologyTerm(
        id=fdp.ConsumeUnicodeNoSurrogates(64),
        label=fdp.ConsumeUnicodeNoSurrogates(128),
        description=fdp.ConsumeUnicodeNoSurrogates(256),
        synonyms=tuple(
            fdp.ConsumeUnicodeNoSurrogates(64) for _ in range(fdp.ConsumeIntInRange(0, 5))
        ),
        xrefs=tuple(
            fdp.ConsumeUnicodeNoSurrogates(32) for _ in range(fdp.ConsumeIntInRange(0, 5))
        ),
        namespace=fdp.ConsumeUnicodeNoSurrogates(16),
        obsolete=fdp.ConsumeBool(),
    )
    term.to_dict()
    return term


def _fuzz_disease_record(fdp: atheris.FuzzedDataProvider) -> DiseaseRecord:
    record = DiseaseRecord(
        mondo_id=fdp.ConsumeUnicodeNoSurrogates(32),
        name=fdp.ConsumeUnicodeNoSurrogates(128),
        definition=fdp.ConsumeUnicodeNoSurrogates(256),
        synonyms=tuple(
            fdp.ConsumeUnicodeNoSurrogates(64) for _ in range(fdp.ConsumeIntInRange(0, 3))
        ),
        icd10_codes=tuple(
            fdp.ConsumeUnicodeNoSurrogates(16) for _ in range(fdp.ConsumeIntInRange(0, 3))
        ),
        icd11_codes=tuple(
            fdp.ConsumeUnicodeNoSurrogates(16) for _ in range(fdp.ConsumeIntInRange(0, 3))
        ),
        omim_ids=tuple(
            fdp.ConsumeUnicodeNoSurrogates(16) for _ in range(fdp.ConsumeIntInRange(0, 2))
        ),
        orphanet_ids=tuple(
            fdp.ConsumeUnicodeNoSurrogates(16) for _ in range(fdp.ConsumeIntInRange(0, 2))
        ),
        mesh_ids=tuple(
            fdp.ConsumeUnicodeNoSurrogates(16) for _ in range(fdp.ConsumeIntInRange(0, 2))
        ),
        doid_ids=tuple(
            fdp.ConsumeUnicodeNoSurrogates(16) for _ in range(fdp.ConsumeIntInRange(0, 2))
        ),
        hpo_terms=tuple(
            fdp.ConsumeUnicodeNoSurrogates(16) for _ in range(fdp.ConsumeIntInRange(0, 3))
        ),
        parent_mondo_ids=tuple(
            fdp.ConsumeUnicodeNoSurrogates(16) for _ in range(fdp.ConsumeIntInRange(0, 2))
        ),
        child_mondo_ids=tuple(
            fdp.ConsumeUnicodeNoSurrogates(16) for _ in range(fdp.ConsumeIntInRange(0, 2))
        ),
        prevalence=fdp.ConsumeUnicodeNoSurrogates(64),
        inheritance=tuple(
            fdp.ConsumeUnicodeNoSurrogates(32) for _ in range(fdp.ConsumeIntInRange(0, 2))
        ),
    )
    record.to_dict()
    return record


def _fuzz_phenotype_association(fdp: atheris.FuzzedDataProvider) -> None:
    assoc = PhenotypeAssociation(
        hpo_id=fdp.ConsumeUnicodeNoSurrogates(16),
        hpo_label=fdp.ConsumeUnicodeNoSurrogates(64),
        mondo_id=fdp.ConsumeUnicodeNoSurrogates(16),
        disease_name=fdp.ConsumeUnicodeNoSurrogates(64),
        gene_symbol=fdp.ConsumeUnicodeNoSurrogates(16),
        uniprot_id=fdp.ConsumeUnicodeNoSurrogates(16),
        frequency=fdp.ConsumeUnicodeNoSurrogates(16),
        onset=fdp.ConsumeUnicodeNoSurrogates(32),
        evidence_codes=tuple(
            fdp.ConsumeUnicodeNoSurrogates(16) for _ in range(fdp.ConsumeIntInRange(0, 3))
        ),
        references=tuple(
            fdp.ConsumeUnicodeNoSurrogates(32) for _ in range(fdp.ConsumeIntInRange(0, 3))
        ),
    )
    assoc.to_dict()


def _fuzz_target_evidence(fdp: atheris.FuzzedDataProvider) -> TargetEvidenceScore:
    score = TargetEvidenceScore(
        target_ensembl_id=fdp.ConsumeUnicodeNoSurrogates(24),
        target_gene_symbol=fdp.ConsumeUnicodeNoSurrogates(16),
        uniprot_id=fdp.ConsumeUnicodeNoSurrogates(16),
        disease_mondo_id=fdp.ConsumeUnicodeNoSurrogates(16),
        disease_name=fdp.ConsumeUnicodeNoSurrogates(64),
        overall_score=fdp.ConsumeFloat(),
        genetic_association=fdp.ConsumeFloat(),
        somatic_mutation=fdp.ConsumeFloat(),
        known_drug=fdp.ConsumeFloat(),
        affected_pathway=fdp.ConsumeFloat(),
        literature=fdp.ConsumeFloat(),
        animal_model=fdp.ConsumeFloat(),
        rna_expression=fdp.ConsumeFloat(),
        drug_count=fdp.ConsumeIntInRange(0, 1000),
        tractable=fdp.ConsumeBool(),
    )
    score.to_dict()
    return score


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)

    try:
        _fuzz_ontology_term(fdp)
    except (ValueError, TypeError, OverflowError):
        pass

    try:
        _fuzz_disease_record(fdp)
    except (ValueError, TypeError, OverflowError):
        pass

    try:
        _fuzz_phenotype_association(fdp)
    except (ValueError, TypeError, OverflowError):
        pass

    try:
        evidence = _fuzz_target_evidence(fdp)
    except (ValueError, TypeError, OverflowError):
        evidence = None

    try:
        am_score_raw = fdp.ConsumeFloat()
        am_score = am_score_raw if fdp.ConsumeBool() else None
        classifications = list(PathogenicityClass)
        cls_idx = fdp.ConsumeIntInRange(0, len(classifications) - 1)

        pops = []
        for _ in range(fdp.ConsumeIntInRange(0, 3)):
            pops.append(
                PopulationFrequency(
                    population=fdp.ConsumeUnicodeNoSurrogates(8),
                    allele_count=fdp.ConsumeIntInRange(0, 1_000_000),
                    allele_number=fdp.ConsumeIntInRange(1, 1_000_000),
                    allele_frequency=fdp.ConsumeFloat(),
                    homozygote_count=fdp.ConsumeIntInRange(0, 10_000),
                )
            )

        diseases = []
        for _ in range(fdp.ConsumeIntInRange(0, 2)):
            diseases.append(
                DiseaseRecord(
                    mondo_id=fdp.ConsumeUnicodeNoSurrogates(16),
                    name=fdp.ConsumeUnicodeNoSurrogates(32),
                )
            )

        evidences = []
        if evidence is not None:
            evidences.append(evidence)

        report = VariantReport(
            hgvs=fdp.ConsumeUnicodeNoSurrogates(64),
            gene_symbol=fdp.ConsumeUnicodeNoSurrogates(16),
            uniprot_id=fdp.ConsumeUnicodeNoSurrogates(16),
            residue_position=fdp.ConsumeIntInRange(0, 100_000),
            reference_aa=fdp.ConsumeUnicodeNoSurrogates(3),
            alternate_aa=fdp.ConsumeUnicodeNoSurrogates(3),
            structure_available=fdp.ConsumeBool(),
            plddt_at_residue=fdp.ConsumeFloat() if fdp.ConsumeBool() else None,
            mean_pae_neighborhood=fdp.ConsumeFloat() if fdp.ConsumeBool() else None,
            predicted_functional_impact=fdp.ConsumeUnicodeNoSurrogates(64),
            alphamissense_score=am_score,
            alphamissense_class=fdp.ConsumeUnicodeNoSurrogates(16),
            clinvar_classification=classifications[cls_idx],
            clinvar_review_status=fdp.ConsumeUnicodeNoSurrogates(32),
            clinvar_variation_id=fdp.ConsumeUnicodeNoSurrogates(16),
            clinvar_conditions=tuple(
                fdp.ConsumeUnicodeNoSurrogates(32) for _ in range(fdp.ConsumeIntInRange(0, 3))
            ),
            gnomad_af_global=fdp.ConsumeFloat() if fdp.ConsumeBool() else None,
            gnomad_af_by_population=tuple(pops),
            gnomad_loeuf=fdp.ConsumeFloat() if fdp.ConsumeBool() else None,
            top_diseases=tuple(diseases),
            top_target_evidence=tuple(evidences),
            sources_queried=tuple(
                fdp.ConsumeUnicodeNoSurrogates(16) for _ in range(fdp.ConsumeIntInRange(0, 3))
            ),
            data_version=fdp.ConsumeUnicodeNoSurrogates(16),
        )
        report.pathogenicity_tier()
        report.to_dict()
    except (ValueError, TypeError, OverflowError):
        pass


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
