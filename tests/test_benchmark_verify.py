# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches
"""Tests for ``benchmarks.verify._values_equal`` float-precision tolerance."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_VERIFY_PATH = _REPO_ROOT / "benchmarks" / "verify.py"

# benchmarks/ is not a package; load the module by path so we can test it
# without polluting the public src tree.
spec = importlib.util.spec_from_file_location("benchmarks_verify", _VERIFY_PATH)
assert spec is not None and spec.loader is not None
_verify = importlib.util.module_from_spec(spec)
sys.modules["benchmarks_verify"] = _verify
spec.loader.exec_module(_verify)


@pytest.mark.unit
def test_values_equal_exact_match() -> None:
    assert _verify._values_equal(1, 1)
    assert _verify._values_equal("BRCA1", "BRCA1")
    assert _verify._values_equal(None, None)


@pytest.mark.unit
def test_values_equal_float_tolerance() -> None:
    # Two floats one ULP apart — exact equality would fail.
    assert _verify._values_equal(1.42e-5, 1.42e-5 + 1e-20)


@pytest.mark.unit
def test_values_equal_float_real_difference() -> None:
    # A real difference must still be caught.
    assert not _verify._values_equal(1.42e-5, 2.42e-5)


@pytest.mark.unit
def test_values_equal_nested_dict_float() -> None:
    a = {"af": 1.42e-5, "n": 4, "label": "PASS"}
    b = {"af": 1.42e-5 + 1e-20, "n": 4, "label": "PASS"}
    assert _verify._values_equal(a, b)


@pytest.mark.unit
def test_values_equal_nested_dict_mismatch() -> None:
    a = {"af": 1.42e-5, "label": "PASS"}
    b = {"af": 1.42e-5, "label": "FAIL"}
    assert not _verify._values_equal(a, b)


@pytest.mark.unit
def test_values_equal_nested_dict_different_keys() -> None:
    a = {"af": 1.0}
    b = {"af": 1.0, "extra": 1}
    assert not _verify._values_equal(a, b)


@pytest.mark.unit
def test_values_equal_list_floats() -> None:
    a = [0.1, 0.2, 0.3]
    b = [0.1 + 1e-20, 0.2, 0.3]
    assert _verify._values_equal(a, b)


@pytest.mark.unit
def test_values_equal_list_different_length() -> None:
    assert not _verify._values_equal([1, 2], [1, 2, 3])


@pytest.mark.unit
def test_diff_record_skips_timestamps() -> None:
    a = {"id": "B01", "timestamp": "20260101T000000Z", "value": 1}
    b = {"id": "B01", "timestamp": "20260201T000000Z", "value": 1}
    assert _verify._diff_record(a, b) == []


@pytest.mark.unit
def test_diff_record_reports_real_diff() -> None:
    a = {"id": "B01", "value": 1}
    b = {"id": "B01", "value": 2}
    diffs = _verify._diff_record(a, b)
    assert len(diffs) == 1
    assert "value" in diffs[0]
