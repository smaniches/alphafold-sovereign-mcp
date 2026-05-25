#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Atheris fuzz target for domain types — OntologyTerm, DiseaseRecord, VariantReport."""

from __future__ import annotations

import sys

import atheris

with atheris.instrument_imports():
    from alphafold_sovereign.domain.disease import (
        DiseaseRecord,
        OntologyTerm,
        PathogenicityClass,
        PopulationFrequency,
        VariantReport,
    )


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)

    try:
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
    except (ValueError, TypeError, OverflowError):
        pass

    try:
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
        )
        record.to_dict()
    except (ValueError, TypeError, OverflowError):
        pass

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

        report = VariantReport(
            hgvs=fdp.ConsumeUnicodeNoSurrogates(64),
            gene_symbol=fdp.ConsumeUnicodeNoSurrogates(16),
            uniprot_id=fdp.ConsumeUnicodeNoSurrogates(16),
            residue_position=fdp.ConsumeIntInRange(0, 100_000),
            reference_aa=fdp.ConsumeUnicodeNoSurrogates(3),
            alternate_aa=fdp.ConsumeUnicodeNoSurrogates(3),
            alphamissense_score=am_score,
            clinvar_classification=classifications[cls_idx],
            gnomad_af_global=fdp.ConsumeFloat() if fdp.ConsumeBool() else None,
            gnomad_af_by_population=tuple(pops),
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
