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


@pytest.mark.unit
def test_main_returns_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """main([]) must invoke run_stdio() and return 0 on success.

    We replace run_stdio with a no-op so the server doesn't actually start
    (it would block forever waiting on stdin).
    """
    from alphafold_sovereign import __main__ as entry
    from alphafold_sovereign.server import stdio as stdio_mod

    calls: list[int] = []

    def fake_run_stdio() -> None:
        calls.append(1)

    monkeypatch.setattr(stdio_mod, "run_stdio", fake_run_stdio)

    rc = entry.main([])
    assert rc == 0
    assert calls == [1], "main() should invoke run_stdio exactly once"


@pytest.mark.unit
def test_main_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    """``--version`` prints the package version and returns 0."""
    from alphafold_sovereign import __main__ as entry
    from alphafold_sovereign import __version__ as expected_version

    rc = entry.main(["--version"])
    out = capsys.readouterr().out.strip()
    assert rc == 0
    assert out == expected_version


@pytest.mark.unit
def test_main_self_test_flag(capsys: pytest.CaptureFixture[str]) -> None:
    """``--self-test`` runs the offline self-test and prints PASS on the BRCA1 fixture."""
    from alphafold_sovereign import __main__ as entry

    rc = entry.main(["--self-test"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "SELF-TEST PASS" in out


@pytest.mark.unit
def test_self_test_function_directly() -> None:
    """``_run_self_test()`` returns 0 and does not require network."""
    from alphafold_sovereign import __main__ as entry

    rc = entry._run_self_test()
    assert rc == 0
