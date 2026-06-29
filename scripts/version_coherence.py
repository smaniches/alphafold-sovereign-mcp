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
drift was found (printed as a table); 2 means a file was missing/malformed or a
version field could not be read.

Deliberately stdlib-only and TOML-parser-free (``tomllib`` is 3.11+), so it runs
across the project's full ``>=3.10`` support range with zero dependencies.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _toml_project_version(rel: str) -> str | None:
    """Read ``[project].version`` from a TOML file without a TOML parser.

    The match is scoped to the ``[project]`` table so unrelated ``version``
    keys (e.g. a ``[tool.*]`` setting) can never be picked up by mistake.
    """
    section = re.search(r"(?ms)^\[project\]\s*$(.*?)(?=^\[|\Z)", _read(rel))
    if section is None:
        return None
    m = re.search(r'(?m)^version\s*=\s*"([^"]+)"', section.group(1))
    return m.group(1) if m else None


def _re_version(rel: str, pattern: str) -> str | None:
    """Return the first capture group of ``pattern`` (line-anchored) in a file."""
    m = re.search(pattern, _read(rel), re.MULTILINE)
    return m.group(1) if m else None


def _toplevel_yaml_version(rel: str) -> str | None:
    """First column-zero ``version:`` value; nested ``version:`` keys ignored."""
    return _re_version(rel, r'^version:\s*"?([^"\s#]+)"?')


def _json_path(rel: str, *keys: str | int) -> Any:  # noqa: ANN401 - returns the raw JSON node
    """Walk ``keys`` (dict keys or list indices) into a parsed JSON file."""
    node: Any = json.loads(_read(rel))
    for key in keys:
        node = node[key]
    return node


def _safe(extractor: Callable[[], str | None]) -> str | None:
    """Run an extractor, mapping a missing or malformed source to ``None``.

    Narrow by design: a missing file (``OSError``), malformed JSON/TOML
    (``ValueError`` — ``json.JSONDecodeError`` is a subclass), or an absent
    key/index (``KeyError``/``IndexError``/``TypeError``) all surface as a
    ``None`` version, which ``main`` reports as a coherence failure (exit 2).
    """
    try:
        return extractor()
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None


def collect() -> dict[str, str | None]:
    """Map each surface label to the version string it declares (or ``None``)."""
    return {
        "pyproject.toml [project.version]": _safe(lambda: _toml_project_version("pyproject.toml")),
        "src/alphafold_sovereign/__init__.py": _safe(
            lambda: _re_version(
                "src/alphafold_sovereign/__init__.py",
                r'^__version__\s*=\s*"([^"]+)"',
            )
        ),
        "CITATION.cff": _safe(lambda: _toplevel_yaml_version("CITATION.cff")),
        "smithery.yaml": _safe(lambda: _toplevel_yaml_version("smithery.yaml")),
        ".zenodo.json": _safe(lambda: _json_path(".zenodo.json", "version")),
        ".well-known/mcp.json": _safe(lambda: _json_path(".well-known/mcp.json", "version")),
        "server.json [version]": _safe(lambda: _json_path("server.json", "version")),
        "server.json [packages[0].version]": _safe(
            lambda: _json_path("server.json", "packages", 0, "version")
        ),
    }


def main() -> int:
    found = collect()
    canonical = found["pyproject.toml [project.version]"]
    if canonical is None:
        print(
            "ERROR: could not read the canonical version from pyproject.toml.",
            file=sys.stderr,
        )
        return 2

    width = max(len(label) for label in found)
    missing = [label for label, version in found.items() if version is None]
    drift = {
        label: version
        for label, version in found.items()
        if version is not None and version != canonical
    }
    for label, version in found.items():
        mark = "ok" if version == canonical else ("MISS" if version is None else "DRIFT")
        print(f"  [{mark:^5}] {label:<{width}}  {version}")

    if missing:
        print(
            f"\nFAIL: {len(missing)} surface(s) missing/unreadable (see MISS above).",
            file=sys.stderr,
        )
        return 2
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
