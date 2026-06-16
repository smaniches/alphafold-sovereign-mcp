# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Repository metadata contract tests.

These tests fail CI when the release, citation, and deposition metadata
surfaces drift apart: the package version, the Zenodo deposition metadata,
the citation files, and the headline claims in the README and docs (tool
count, module count, data-source count and names, test count, DOI, and the
install command).

They are the mechanical guard that replaces the manual "fix stale counts"
cleanup releases (see the 1.1.8-1.1.10 entries in CHANGELOG.md). Every claim
is recomputed from a source of truth and compared, so the tests stay correct
as the project evolves rather than encoding a frozen snapshot.

All repository files are read as UTF-8 explicitly so the suite behaves
identically on the Linux and macOS CI runners and on a Windows checkout.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

# Importing the tool modules runs their @mcp.tool decorators against the shared
# FastMCP instance, so mcp.list_tools() reports the full live tool registry.
from alphafold_sovereign.server.app import mcp
from alphafold_sovereign.tools import (  # noqa: F401  (imported for registration)
    disease,
    knowledge_graph_tools,
    precision_medicine,
    structure_intelligence,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]

# The concept (version-independent) Zenodo DOI lives in the citation surfaces.
_CONCEPT_DOI = "10.5281/zenodo.20134773"

# The nine data sources this server wraps (AlphaFold + 8 others). Each must be
# named on every surface that lists them, so a dropped/renamed source is caught.
_EXPECTED_SOURCES = (
    "AlphaFold",
    "Open Targets",
    "ChEMBL",
    "Ensembl",
    "ClinVar",
    "gnomAD",
    "MONDO",
    "HPO",
    "DisGeNET",
)

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

# Doc surfaces that state an exact test count, and the patterns counts appear in.
_TEST_COUNT_FILES = ("README.md", "CITATION.cff", "STATUS.md", "docs/index.md")
_TEST_COUNT_PATTERNS = (
    r"tests-(\d+)%20passing",  # shields.io badge
    r"\((\d+)\s+tests[,)]",  # "(N tests," or "(N tests)"
    r"\*\*(\d+)\s+tests\*\*",  # "**N tests**"
    r"(\d+)\s+unit\s+tests",  # "N unit tests"
)
# Machine manifests published to registries must NOT embed a volatile count.
_NO_COUNT_FILES = (".well-known/mcp.json", "smithery.yaml")


def _read(relative: str) -> str:
    return (_REPO_ROOT / relative).read_text(encoding="utf-8")


def _load_json(relative: str) -> dict[str, Any]:
    return json.loads(_read(relative))


def _normalize(text: str) -> str:
    """Collapse runs of whitespace so line-wrapped phrases match as substrings.

    Multi-word source names ("Open Targets") wrap across lines in YAML folded
    scalars and prose, so a raw substring search would miss them.
    """
    return re.sub(r"\s+", " ", text)


def _search1(pattern: str, text: str, what: str) -> str:
    match = re.search(pattern, text)
    assert match, f"could not find {what}"
    return match.group(1)


def _pyproject_field(field: str) -> str:
    """First ``field = "value"`` under the leading ``[project]`` table."""
    return _search1(
        rf'(?m)^{field}\s*=\s*"([^"]+)"', _read("pyproject.toml"), f"{field} in pyproject"
    )


def _zenodo_version_is_release_managed() -> bool:
    extra_files = _load_json("release-please-config.json")["packages"]["."]["extra-files"]
    return any(
        isinstance(entry, dict)
        and entry.get("path") == ".zenodo.json"
        and entry.get("jsonpath") == "$.version"
        for entry in extra_files
    )


def _collect_versions() -> dict[str, str]:
    """Every version surface release-please keeps in lock-step."""
    server = _load_json("server.json")
    return {
        "manifest": _load_json(".release-please-manifest.json")["."],
        "pyproject": _pyproject_field("version"),
        "__init__": _search1(
            r'__version__\s*=\s*"([^"]+)"',
            _read("src/alphafold_sovereign/__init__.py"),
            "__version__",
        ),
        "citation": _search1(
            r'(?m)^version:\s*"([^"]+)"', _read("CITATION.cff"), "CITATION version"
        ),
        "zenodo": _load_json(".zenodo.json")["version"],
        "server.json": server["version"],
        "server.json/pkg": server["packages"][0]["version"],
        "mcp.json": _load_json(".well-known/mcp.json")["version"],
        "smithery": _search1(
            r'(?m)^version:\s*"([^"]+)"', _read("smithery.yaml"), "smithery version"
        ),
        "readme-bibtex": _search1(
            r"version\s*=\s*\{([0-9]+\.[0-9]+\.[0-9]+)\}",
            _read("README.md"),
            "README bibtex version",
        ),
    }


def _collect_test_counts() -> dict[str, set[str]]:
    counts: dict[str, set[str]] = {}
    for relative in _TEST_COUNT_FILES:
        text = _read(relative)
        found: set[str] = set()
        for pattern in _TEST_COUNT_PATTERNS:
            found.update(re.findall(pattern, text))
        if found:
            counts[relative] = found
    return counts


# --------------------------------------------------------------------------- #
# Zenodo deposition metadata
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_zenodo_json_present_and_schema_valid() -> None:
    zenodo = _load_json(".zenodo.json")

    assert zenodo["upload_type"] == "software"
    assert zenodo["access_right"] == "open"
    assert zenodo["license"] == "Apache-2.0"
    assert zenodo["title"], "Zenodo deposition needs a title"
    assert zenodo["description"], "Zenodo deposition needs a description"

    creators = zenodo["creators"]
    assert isinstance(creators, list)
    assert creators, "at least one creator required"
    author = creators[0]
    assert author["name"] == "Maniches, Santiago"
    assert author["orcid"] == "0009-0005-6480-1987"
    assert author["affiliation"] == "TOPOLOGICA LLC"

    keywords = zenodo["keywords"]
    assert isinstance(keywords, list)
    assert keywords, "Zenodo deposition needs keywords"

    # Zenodo mints the version-specific DOI for each GitHub release; the file
    # must NOT hardcode one. The concept DOI lives in CITATION.cff / README.
    assert "doi" not in zenodo, ".zenodo.json must not pin a DOI (Zenodo mints it)"


@pytest.mark.unit
def test_zenodo_version_is_release_please_managed() -> None:
    # Guards the lock itself: if the .zenodo.json updater is ever removed from
    # release-please, the version would silently drift on the next release.
    assert _zenodo_version_is_release_managed(), (
        ".zenodo.json must be listed in release-please-config.json extra-files "
        "with jsonpath $.version so its version stays in lock-step"
    )


# --------------------------------------------------------------------------- #
# Version consistency across release-please-managed surfaces
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_version_consistent_across_managed_surfaces() -> None:
    versions = _collect_versions()
    assert len(set(versions.values())) == 1, f"version surfaces disagree: {versions}"


@pytest.mark.unit
def test_license_consistent_across_surfaces() -> None:
    pyproject_license = re.search(
        r'license\s*=\s*\{\s*text\s*=\s*"([^"]+)"\s*\}', _read("pyproject.toml")
    )
    citation_license = re.search(r"(?m)^license:\s*(\S+)", _read("CITATION.cff"))
    zenodo_license = _load_json(".zenodo.json")["license"]

    assert pyproject_license, "pyproject.toml is missing a license"
    assert citation_license, "CITATION.cff is missing a license"

    licenses = {pyproject_license.group(1), citation_license.group(1), zenodo_license}
    assert licenses == {"Apache-2.0"}, f"license surfaces disagree: {licenses}"


# --------------------------------------------------------------------------- #
# DOI consistency
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_doi_consistent_across_surfaces() -> None:
    citation = _search1(r'(?m)^doi:\s*"([^"]+)"', _read("CITATION.cff"), "CITATION DOI")
    assert citation == _CONCEPT_DOI
    assert _load_json(".well-known/mcp.json")["doi"] == _CONCEPT_DOI

    # README references the DOI url-encoded (badge) and plain (link, bibtex).
    readme = _read("README.md").replace("%2F", "/")
    found = set(re.findall(r"10\.5281/zenodo\.\d+", readme))
    assert found == {_CONCEPT_DOI}, f"README references unexpected Zenodo DOIs: {found}"


# --------------------------------------------------------------------------- #
# README / docs headline claims
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_tool_count_and_module_count_match_readme() -> None:
    live_count = len(await mcp.list_tools())

    claim = re.search(
        r"exposes\s+(\d+)\s+MCP\s+tools\s+across\s+(\w+)\s+modules", _read("README.md")
    )
    assert claim, "README must state 'exposes N MCP tools across M modules'"
    assert int(claim.group(1)) == live_count, (
        f"README claims {claim.group(1)} tools but the server registers {live_count}"
    )

    tools_dir = _REPO_ROOT / "src" / "alphafold_sovereign" / "tools"
    tool_modules = [
        path
        for path in tools_dir.glob("*.py")
        if path.name != "__init__.py" and "@mcp.tool" in path.read_text(encoding="utf-8")
    ]
    word = claim.group(2).lower()
    claimed_modules = _NUMBER_WORDS.get(word, int(word) if word.isdigit() else None)
    assert claimed_modules == len(tool_modules), (
        f"README says {claim.group(2)} modules; found {len(tool_modules)} tool modules"
    )


@pytest.mark.unit
def test_data_sources_count_and_names() -> None:
    readme = _read("README.md")
    section_match = re.search(r"## Data sources\n(.*?)\n## ", readme, re.DOTALL)
    assert section_match, "README must have a Data sources section"
    section = section_match.group(1)

    table_rows = [ln for ln in section.splitlines() if ln.strip().startswith("|")]
    separator = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
    content_rows = [r for r in table_rows if not separator.match(r)]
    data_rows = content_rows[1:]  # drop the header row
    assert len(data_rows) == 9, (
        f"expected AlphaFold + 8 = 9 data-source rows, found {len(data_rows)}"
    )

    # The prose count must agree with the table on both citation surfaces.
    citation = _read("CITATION.cff")
    assert "8 other" in _normalize(readme)
    assert "8 other" in _normalize(citation)

    # And every named source must appear on each surface that lists them.
    # Match against the table rows only (not the section's trailing prose,
    # which also names some sources) so a count-preserving rename is caught.
    # Normalize first: names like "Open Targets" wrap across lines in the
    # CITATION folded scalar and would otherwise miss a raw substring search.
    table_text = _normalize("\n".join(data_rows))
    citation_text = _normalize(citation)
    zenodo_text = _normalize(_load_json(".zenodo.json")["description"])
    for source in _EXPECTED_SOURCES:
        assert source in table_text, f"{source} missing from README data-sources table"
        assert source in citation_text, f"{source} missing from CITATION abstract"
        assert source in zenodo_text, f"{source} missing from .zenodo.json description"


@pytest.mark.unit
def test_test_count_claims_agree() -> None:
    counts = _collect_test_counts()
    assert counts, "no test-count claim found on any documented surface"
    all_counts = set().union(*counts.values())
    assert len(all_counts) == 1, f"test-count claims disagree across surfaces: {counts}"


@pytest.mark.unit
def test_machine_manifests_carry_no_test_count() -> None:
    # Registry manifests publish on release only, so an embedded count is
    # perpetually stale; the count belongs to the doc surfaces guarded above.
    for relative in _NO_COUNT_FILES:
        assert not re.search(r"\d+\s+tests", _read(relative)), (
            f"{relative} must not embed a volatile test count"
        )


@pytest.mark.unit
def test_install_commands_use_distribution_name() -> None:
    name = _pyproject_field("name")
    readme = _read("README.md")
    assert f"pip install {name}" in readme, "README pip install must use the dist name"
    assert f"uvx {name}" in readme, "README uvx command must use the dist name"
