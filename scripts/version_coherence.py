#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""Assert that every version-bearing file agrees with pyproject.toml.

The project publishes its identity across many surfaces — PyPI metadata, the
Python package, the Citation File Format record, the Zenodo deposition, the
MCP ``server.json`` and ``.well-known/mcp.json`` manifests, and the Smithery
manifest. release-please stamps all of them on each release, but a hand-edit or
a botched merge could silently desync them. This script is the guard: it reads
the canonical version from ``pyproject.toml`` and fails loudly if any other
surface disagrees.

Run locally with ``python scripts/version_coherence.py``; CI runs it on
every push and pull request. Exit code 0 means perfect coherence; 1 means a
drift was found (printed as a table); 2 means a file or field was missing.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _toplevel_yaml_version(rel: str) -> str | None:
    """Return the first column-zero ``version:`` value in a YAML file.

    Anchored at line start so nested ``version:`` keys (e.g. a referenced
    dependency's version inside CITATION.cff) are ignored.
    """
    m = re.search(r'(?m)^version:\s*"?([^"\s#]+)"?', _read(rel))
    return m.group(1) if m else None


def collect() -> dict[str, str | None]:
    """Map each surface label to the version string it declares."""
    found: dict[str, str | None] = {}

    # Canonical source.
    found["pyproject.toml [project.version]"] = tomllib.loads(_read("pyproject.toml"))["project"][
        "version"
    ]

    # Python package dunder.
    m = re.search(
        r'^__version__\s*=\s*"([^"]+)"',
        _read("src/alphafold_sovereign/__init__.py"),
        re.MULTILINE,
    )
    found["src/alphafold_sovereign/__init__.py"] = m.group(1) if m else None

    # Top-level YAML version: lines.
    found["CITATION.cff"] = _toplevel_yaml_version("CITATION.cff")
    found["smithery.yaml"] = _toplevel_yaml_version("smithery.yaml")

    # JSON manifests.
    found[".zenodo.json"] = json.loads(_read(".zenodo.json")).get("version")
    found[".well-known/mcp.json"] = json.loads(_read(".well-known/mcp.json")).get("version")

    server = json.loads(_read("server.json"))
    found["server.json [version]"] = server.get("version")
    packages = server.get("packages") or [{}]
    found["server.json [packages[0].version]"] = packages[0].get("version")

    return found


def main() -> int:
    found = collect()
    canonical = found["pyproject.toml [project.version]"]

    missing = [label for label, version in found.items() if version is None]
    if missing:
        print("ERROR: could not read a version from:", file=sys.stderr)
        for label in missing:
            print(f"  - {label}", file=sys.stderr)
        return 2

    width = max(len(label) for label in found)
    drift = {label: version for label, version in found.items() if version != canonical}
    for label, version in found.items():
        mark = "ok" if version == canonical else "DRIFT"
        print(f"  [{mark:^5}] {label:<{width}}  {version}")

    if drift:
        print(
            f"\nFAIL: {len(drift)} surface(s) disagree with the canonical "
            f"pyproject.toml version ({canonical}).",
            file=sys.stderr,
        )
        return 1

    print(f"\nOK: all {len(found)} surfaces report version {canonical}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
