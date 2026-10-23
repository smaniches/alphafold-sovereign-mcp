# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Replay source responses and assert deterministic pipeline output.

Fixtures record upstream HTTP responses and are tested offline.
Passing this test validates repeatability of the software path, not
independent clinical, experimental, therapeutic, or biological truth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import _cassette
import pytest

if TYPE_CHECKING:
    import respx


@pytest.mark.golden
@pytest.mark.parametrize("example", _cassette.EXAMPLES, ids=lambda e: e["slug"])
async def test_golden_example_reproduces_expected_output(
    example: dict[str, object],
    respx_mock: respx.MockRouter,
) -> None:
    example_dir = _cassette.GOLDEN_DIR / str(example["slug"])
    cassette_path = example_dir / "cassette.json"
    if not cassette_path.exists():
        # The recorded fixtures live under examples/, which is not part of the
        # packaged sdist/wheel; skip rather than error when running from a build
        # that omits them (CI runs from the full checkout, where they exist).
        pytest.skip(f"golden fixtures not packaged in this build: {cassette_path}")
    cassette = _cassette.load_json(cassette_path)
    expected = _cassette.load_json(example_dir / "expected.json")

    _cassette.install_routes(respx_mock, cassette)
    output = await _cassette.run_tool(str(example["tool"]), dict(example["input"]))  # type: ignore[arg-type]

    assert _cassette.normalize_output(output) == expected
