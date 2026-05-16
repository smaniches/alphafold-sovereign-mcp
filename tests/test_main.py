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


@pytest.mark.unit
def test_self_test_reports_failure_when_acmg_helper_regresses(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``_run_self_test`` returns 1 and reports every failing fixture when the
    ACMG helper functions regress.

    The passing path (exercised by ``test_self_test_function_directly``) never
    enters the failure-reporting branch. Monkeypatching all three helpers to
    return an empty mapping makes every one of the five fixtures fail, which
    drives ``_run_self_test`` through that branch. This verifies the self-test
    can actually detect a regression, which is the whole point of shipping it.
    """
    from alphafold_sovereign import __main__ as entry
    from alphafold_sovereign.tools import precision_medicine

    def _empty(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {}

    monkeypatch.setattr(precision_medicine, "_vep_to_acmg", _empty)
    monkeypatch.setattr(precision_medicine, "_gnomad_to_acmg", _empty)
    monkeypatch.setattr(precision_medicine, "_am_to_acmg_evidence", _empty)

    rc = entry._run_self_test()
    err = capsys.readouterr().err

    assert rc == 1
    assert "SELF-TEST FAIL" in err
    # All five fixtures (PVS1, PM2, PP3, BP4, BS1) must be reported as failed.
    assert err.count("  - ") == 5
