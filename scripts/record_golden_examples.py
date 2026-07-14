#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Record the golden examples' upstream traffic from the live public APIs.

Run this once (with network access) to regenerate the recorded fixtures:

    uv run python scripts/record_golden_examples.py

For each example in ``tests/golden/_cassette.py::EXAMPLES`` it wraps
``BaseAsyncClient._request`` — the point past the client's retry loop, so only
the final successful response of each upstream call is captured — runs the
pipeline tool live, and writes two artefacts under ``examples/golden/<slug>/``:

* ``cassette.json`` — every real request/response, each tagged with its source,
  method, URL, and a SHA-256 of the response body for provenance.
* ``expected.json`` — the tool's output with the volatile provenance
  version/timestamp redacted, i.e. exactly what the golden test asserts.

The golden test (``tests/golden/test_golden_examples.py``) replays the
cassettes offline via respx and diffs against ``expected.json``; it never
touches the network. Regenerate the fixtures only intentionally — a diff in
``expected.json`` means an upstream classification or the pipeline's output
changed, which is a fact to review, not to rubber-stamp.
"""

from __future__ import annotations

import asyncio
import base64
import datetime
import hashlib
import json
import pathlib
import sys
from typing import TYPE_CHECKING, Any

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tests" / "golden"))

import _cassette  # noqa: E402

import alphafold_sovereign.clients._base as base_mod  # noqa: E402

if TYPE_CHECKING:
    import httpx


def _encode_interaction(
    source: str, request: httpx.Request, response: httpx.Response
) -> dict[str, Any]:
    body = response.content
    entry: dict[str, Any] = {
        "source": source,
        "method": request.method,
        "url": str(request.url),
        "status": response.status_code,
        "response_sha256": hashlib.sha256(body).hexdigest(),
    }
    request_body = request.content
    if request_body:
        try:
            entry["request_json"] = json.loads(request_body)
        except ValueError:
            entry["request_text"] = request_body.decode("utf-8", "replace")
    try:
        entry["response_json"] = json.loads(body)
    except ValueError:
        try:
            entry["response_text"] = body.decode("utf-8")
        except UnicodeDecodeError:
            entry["response_base64"] = base64.b64encode(body).decode("ascii")
    return entry


async def _record_one(example: dict[str, Any]) -> tuple[list[dict[str, Any]], Any]:
    interactions: list[dict[str, Any]] = []
    original = base_mod.BaseAsyncClient._request

    async def recording(
        self: base_mod.BaseAsyncClient,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        json: object = None,
        extra_headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        response = await original(
            self, method, path, params=params, json=json, extra_headers=extra_headers
        )
        interactions.append(_encode_interaction(self.upstream_name, response.request, response))
        return response

    base_mod.BaseAsyncClient._request = recording  # type: ignore[method-assign]
    try:
        output = await _cassette.run_tool(example["tool"], example["input"])
    finally:
        base_mod.BaseAsyncClient._request = original  # type: ignore[method-assign]

    # Dedupe identical (source, method, url, body) interactions and sort for a
    # stable, minimal git diff on re-record. respx matches by route, not order,
    # so re-ordering is safe.
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for entry in interactions:
        key = json.dumps(entry, sort_keys=True)
        if key not in seen:
            seen.add(key)
            unique.append(entry)
    unique.sort(key=lambda e: (e["source"], e["method"], e["url"]))
    return unique, output


async def main() -> int:
    recorded_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for example in _cassette.EXAMPLES:
        interactions, output = await _record_one(example)
        target = _cassette.GOLDEN_DIR / example["slug"]
        target.mkdir(parents=True, exist_ok=True)
        cassette = {
            "example": example["slug"],
            "tool": example["tool"],
            "input": example["input"],
            "recorded_at": recorded_at,
            "note": (
                "Real upstream responses captured live from the public APIs; "
                "replayed offline and deterministically in CI."
            ),
            "interactions": interactions,
        }
        (target / "cassette.json").write_text(
            json.dumps(cassette, indent=2) + "\n", encoding="utf-8"
        )
        (target / "expected.json").write_text(
            json.dumps(_cassette.normalize_output(output), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"recorded {example['slug']}: {len(interactions)} interactions")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
