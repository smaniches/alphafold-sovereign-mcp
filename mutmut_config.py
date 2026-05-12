# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""``mutmut`` configuration.

Targets the shipped source tree (``src/alphafold_sovereign/``) excluding
the archived monolith and SPDX/copyright headers.

Run via:

    nox -s mutate -- --runs 50         # bounded, ~5 min
    nox -s mutate                      # full, ~30 min

Per-module mutation scores are summarised in
``docs/quality/mutation-scores.md``.
"""

from __future__ import annotations

# Files to mutate. mutmut globs against these.
paths_to_mutate = "src/alphafold_sovereign/"

# Files to skip.
paths_to_exclude = [
    "_archive/",
    "tests/",
    "src/alphafold_sovereign/__init__.py",  # mostly metadata
    "src/alphafold_sovereign/__main__.py",  # exercised by --self-test fixture
]

# Test command mutmut runs to evaluate each mutant.
runner = "pytest tests/ -q -x --tb=no -p no:cacheprovider"

# Don't mutate SPDX/copyright headers, docstrings, type-only constructs.
def pre_mutation(context) -> None:  # noqa: ANN001
    """Skip mutation of lines that are pure SPDX/header noise."""
    line = context.current_source_line.strip()
    if line.startswith("# SPDX-License-Identifier"):
        context.skip = True
    if line.startswith("# Copyright"):
        context.skip = True
