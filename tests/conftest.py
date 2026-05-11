# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Shared pytest fixtures for the AlphaFold Sovereign MCP test suite.

Provides:
- ``respx_mock``: respx Router scoped per-test (any host, no auto-assert).
- ``ok_json`` helper for building JSON responses.
- ``_fast_retry`` autouse fixture to collapse retry/backoff to milliseconds.
- ``_disable_rate_limit`` autouse fixture so the aiolimiter token bucket
  doesn't add wall-clock latency to tests.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
import respx


@pytest.fixture
def respx_mock() -> Iterator[respx.MockRouter]:
    """Per-test respx router. Routes match against any host."""
    with respx.mock(assert_all_called=False) as router:
        yield router


@pytest.fixture(autouse=True)
def _fast_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Collapse retry/back-off so the request path runs in milliseconds."""
    from alphafold_sovereign.clients import _base

    monkeypatch.setattr(
        _base,
        "wait_exponential_jitter",
        lambda **_: lambda *_a, **_kw: 0,
    )


@pytest.fixture(autouse=True)
def _disable_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable aiolimiter so token-bucket sleeps don't accumulate per test."""
    from alphafold_sovereign.clients import _base

    monkeypatch.setattr(_base, "AsyncLimiter", None)


def _ok_json(payload: Any, status: int = 200) -> httpx.Response:
    """Build an httpx.Response with a JSON body — useful in respx routes."""
    return httpx.Response(status_code=status, json=payload)


@pytest.fixture
def ok_json() -> Callable[..., httpx.Response]:
    """Expose the :func:`_ok_json` helper to tests."""
    return _ok_json
