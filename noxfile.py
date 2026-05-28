# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""Nox sessions — single command to drive lint / type / test / docs / build.

Run from the repo root:

    nox -l                          # list sessions
    nox -s lint                     # ruff check + format check
    nox -s type                     # mypy strict
    nox -s test                     # full pytest matrix on the active Python
    nox -s cov                      # test + coverage report
    nox -s docs                     # mkdocs build (non-strict for now)
    nox -s build                    # uv build (sdist + wheel)
    nox -s mutate -- --runs 50      # mutmut against the shipped src/
    nox -s self_test                # alphafold-sovereign --self-test
    nox                             # default sessions: lint, type, test, cov, docs

Sessions install only the deps they need so they're cheap to run in
isolation. CI uses these same sessions so local results match CI.
"""

from __future__ import annotations

import nox

nox.options.default_venv_backend = "uv|virtualenv"
nox.options.reuse_existing_virtualenvs = False
nox.options.sessions = ["lint", "type", "test", "cov", "docs"]

SRC_DIRS_LINT = [
    "src/alphafold_sovereign/clients/",
    "src/alphafold_sovereign/domain/",
    "src/alphafold_sovereign/tools/",
    "src/alphafold_sovereign/storage/",
    "src/alphafold_sovereign/server/",
    "src/alphafold_sovereign/__main__.py",
]
SRC_DIRS_TYPE = [
    "src/alphafold_sovereign/domain/",
    "src/alphafold_sovereign/clients/",
    "src/alphafold_sovereign/storage/",
    "src/alphafold_sovereign/server/",
    "src/alphafold_sovereign/__main__.py",
]


@nox.session(python="3.12")
def lint(session: nox.Session) -> None:
    """``ruff check`` + ``ruff format --check`` on the shipped source tree."""
    session.install("ruff>=0.4.0")
    session.run("ruff", "check", *SRC_DIRS_LINT, "tests/")
    session.run("ruff", "format", "--check", *SRC_DIRS_LINT)


@nox.session(python="3.12")
def type(session: nox.Session) -> None:
    """``mypy --strict`` on the shipped source tree."""
    session.install("-e", ".[dev]")
    session.run("mypy", *SRC_DIRS_TYPE, "--config-file", "pyproject.toml")


@nox.session(python=["3.10", "3.11", "3.12", "3.13"])
def test(session: nox.Session) -> None:
    """Run the full pytest suite on each supported Python."""
    session.install("-e", ".[dev]")
    session.run("pytest", "tests/", "-q", "--tb=short")


@nox.session(python="3.12")
def cov(session: nox.Session) -> None:
    """Run pytest with coverage and enforce the gate from ``pyproject.toml``."""
    session.install("-e", ".[dev]")
    session.run(
        "pytest",
        "tests/",
        "--cov=src/alphafold_sovereign",
        "--cov-report=term-missing",
        "--cov-report=xml:coverage.xml",
        "--cov-fail-under=100",
        "-q",
    )


@nox.session(python="3.12")
def docs(session: nox.Session) -> None:
    """``mkdocs build`` (non-strict; warnings allowed while content stabilises)."""
    session.install("-e", ".[docs]")
    session.run("mkdocs", "build", "--clean")


@nox.session(python="3.12")
def build(session: nox.Session) -> None:
    """``uv build`` sdist + wheel into ``dist/``."""
    session.install("uv")
    session.run("uv", "build", external=True)


@nox.session(python="3.12")
def mutate(session: nox.Session) -> None:
    """Mutation testing on the shipped source tree via ``mutmut``.

    Pass ``--runs N`` (default 100) to bound runtime; full runs take ~30
    minutes on a laptop. Results go to ``docs/quality/mutation-scores.md``.
    """
    session.install("-e", ".[dev,docs]", "mutmut>=2.5.0")
    # mutmut config lives in ``mutmut_config.py``.
    session.run("mutmut", "run", *session.posargs, external=True)
    session.run("mutmut", "results", external=True)


@nox.session(python="3.12")
def self_test(session: nox.Session) -> None:
    """Run ``alphafold-sovereign --self-test`` in an isolated env."""
    session.install("-e", ".")
    session.run("alphafold-sovereign", "--self-test")


@nox.session(python="3.12")
def security(session: nox.Session) -> None:
    """Run bandit + safety + pip-audit on the shipped source tree."""
    session.install("bandit[toml]>=1.7.7", "safety>=3.2.0", "pip-audit>=2.7.0")
    session.run("bandit", "-c", "pyproject.toml", "-r", "src/alphafold_sovereign/")
    session.run("safety", "check", "--full-report")
    session.run("pip-audit")
