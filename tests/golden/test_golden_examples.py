# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""End-to-end golden examples: the pipeline output pinned on canonical variants.

Each example replays real upstream responses (recorded once from the live public
APIs; see ``scripts/record_golden_examples.py``) through the full variant
clinical-report pipeline via respx, entirely offline, and asserts the tool
reproduces the committed ``expected.json`` byte-for-byte after the volatile
provenance version/timestamp is redacted. A failure here means either the
pipeline's behaviour changed or a re-recorded upstream response diverged — both
are facts to investigate, never to silence by regenerating blindly.

The scientific interpretation of each case (canonical identifiers, the
established ClinVar classification, concordance with the pipeline, and cited
literature) lives in the per-example ``README.md`` under ``examples/golden/``.
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
