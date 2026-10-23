# SPDX-License-Identifier: Apache-2.0
"""Scientific identity regression checks for public disease-retrieval examples.

These checks intentionally parse source without contacting a live ontology or
claiming that this subset constitutes a complete MONDO catalog validation.
Cross-references must also be rechecked against pinned ontology snapshots.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/alphafold_sovereign/tools/disease.py"


def _catalog() -> dict[str, dict[str, str]]:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "COMMON_DISEASE_ROOTS":
                return ast.literal_eval(node.value)
    raise AssertionError("COMMON_DISEASE_ROOTS missing")


def test_known_mondo_identity_regressions() -> None:
    """Previously misidentified diseases must not regress.

    Human reviewers must check label, current ontology status, and scope:
    https://mondo.monarchinitiative.org/
    https://github.com/monarch-initiative/mondo/releases/tag/v2026-10-06
    """
    c = _catalog()
    assert c["cardiovascular"]["peripheral_arterial_disease"] == "MONDO:0005386"
    assert c["oncology"]["exocrine_pancreatic_carcinoma"] == "MONDO:0005192"
    assert c["infectious"]["hepatitis_b"] == "MONDO:0005344"
    assert c["psychiatric"]["anxiety_disorder"] == "MONDO:0005618"
    assert c["rare"]["gaucher_disease"] == "MONDO:0018150"


def test_uncertain_legacy_disease_mapping_is_not_served() -> None:
    assert "nonalcoholic_fatty_liver" not in _catalog()["metabolic"]


def test_orphanet_example_not_misidentified() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "79318' (Gaucher disease)" not in source
    assert "returns the Gaucher disease atlas" not in source
    assert "79318' (PMM2-CDG)" in source


def test_open_targets_version_is_not_falsely_asserted() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "OT-24.06" not in source
    assert "OT-platform-24.06" not in source


def test_full_curated_catalog_regressions() -> None:
    c = _catalog()
    expected = {
        "coronary_artery_disease": "MONDO:0005010",
        "heart_failure": "MONDO:0005252",
        "essential_hypertension": "MONDO:0001134",
    }
    assert all(c["cardiovascular"][name] == value for name, value in expected.items())
    assert c["oncology"]["breast_carcinoma"] == "MONDO:0004989"
    assert c["oncology"]["lung_carcinoma"] == "MONDO:0005138"
    assert c["oncology"]["colorectal_carcinoma"] == "MONDO:0024331"
    assert c["oncology"]["prostate_carcinoma"] == "MONDO:0005159"
    assert c["oncology"]["ovarian_carcinoma"] == "MONDO:0005140"
    assert c["oncology"]["lymphoma"] == "MONDO:0005062"
    assert c["autoimmune"]["systemic_lupus_erythematosus"] == "MONDO:0007915"
    assert c["respiratory"]["idiopathic_pulmonary_fibrosis"] == "MONDO:0800504"
    assert c["psychiatric"]["major_depressive_disorder"] == "MONDO:0002009"


def test_unvalidated_catalog_examples_are_withheld() -> None:
    c = _catalog()
    assert "metabolic_syndrome" not in c["metabolic"]
    assert "hepatitis_c" not in c["infectious"]
    assert "hypertension" not in c["cardiovascular"]
    assert "pancreatic_carcinoma" not in c["oncology"]
    assert "peripheral_artery_disease" not in c["cardiovascular"]
    assert sum(len(group) for group in c.values()) == 47
