# SPDX-License-Identifier: Apache-2.0
"""Synthetic reproducibility checks for the hash-pinned MONDO identity audit."""

from __future__ import annotations

from pathlib import Path

from scripts.audit_mondo_catalog import catalog, inspect, ontology


def test_catalog_read_does_not_execute_source(tmp_path: Path) -> None:
    source = tmp_path / "disease.py"
    source.write_text(
        'raise RuntimeError("must not execute")\n'
        'COMMON_DISEASE_ROOTS: dict[str, dict[str, str]] = '
        '{"rare": {"gaucher_disease": "MONDO:0010159"}}\n'
    )
    assert catalog(source)["rare"]["gaucher_disease"] == "MONDO:0010159"


def test_wrong_disease_identity_is_reported(tmp_path: Path) -> None:
    source = tmp_path / "disease.py"
    source.write_text(
        'COMMON_DISEASE_ROOTS: dict[str, dict[str, str]] = '
        '{"rare": {"gaucher_disease": "MONDO:0010159"}}\n'
    )
    obo = tmp_path / "mondo.obo"
    obo.write_text(
        "\n[Term]\nid: MONDO:0010159\nname: mismatch repair cancer syndrome 1\n"
        "\n[Term]\nid: MONDO:0009265\nname: Gaucher disease type 1\n"
        'synonym: "GD1" EXACT []\n'
        "\n[Term]\nid: MONDO:0000000\nname: obsolete disease\nis_obsolete: true\n"
    )
    report = inspect(source, obo)
    assert report["records_checked"] == 1
    assert report["requires_review"] == 1
    assert report["entries"][0]["status"] == "REVIEW_IDENTITY_OR_SCOPE"
    assert ontology(obo)["MONDO:0000000"]["obsolete"] is True


def test_lexical_match_not_claimed_as_biological_validation(tmp_path: Path) -> None:
    source = tmp_path / "disease.py"
    source.write_text(
        'COMMON_DISEASE_ROOTS: dict[str, dict[str, str]] = '
        '{"rare": {"gaucher_disease_type_1": "MONDO:0009265"}}\n'
    )
    obo = tmp_path / "mondo.obo"
    obo.write_text("[Term]\nid: MONDO:0009265\nname: Gaucher disease type 1\n")
    report = inspect(source, obo)
    assert report["requires_review"] == 0
    assert "not independent biological validation" in report["note"]
