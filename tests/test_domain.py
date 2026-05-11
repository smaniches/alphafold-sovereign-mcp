# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Unit tests for domain types — pure Python, no I/O."""
from __future__ import annotations

import pytest

from alphafold_sovereign.domain.disease import (
    EvidenceType,
    OntologyTerm,
    PathogenicityClass,
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
