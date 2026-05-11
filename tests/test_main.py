# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Smoke tests for __main__.py entry point and package metadata."""
from __future__ import annotations

import importlib

import pytest


@pytest.mark.unit
def test_package_version() -> None:
    import alphafold_sovereign
    assert hasattr(alphafold_sovereign, "__version__")
    assert alphafold_sovereign.__version__  # non-empty


@pytest.mark.unit
def test_package_license() -> None:
    import alphafold_sovereign
    assert getattr(alphafold_sovereign, "__license__", "").startswith("Apache")


@pytest.mark.unit
def test_main_module_importable() -> None:
    """__main__.py must be importable and expose a `main` callable."""
    mod = importlib.import_module("alphafold_sovereign.__main__")
    assert callable(getattr(mod, "main", None))
