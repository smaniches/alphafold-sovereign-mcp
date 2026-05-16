# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Unit tests for the async HTTP base client (circuit breaker, retry, rate limit)."""

from __future__ import annotations

import pytest

from alphafold_sovereign.clients._base import (
    CircuitBreaker,
    CircuitState,
    UpstreamConfig,
    UpstreamError,
)


# ── CircuitBreaker ─────────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_circuit_starts_closed() -> None:
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=30)
    assert cb._state == CircuitState.CLOSED  # type: ignore[attr-defined]


@pytest.mark.unit
async def test_circuit_opens_after_threshold() -> None:
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=30)
    await cb.record_failure()
    await cb.record_failure()
    assert cb._state == CircuitState.CLOSED  # type: ignore[attr-defined]  # not yet
    await cb.record_failure()
    assert cb._state == CircuitState.OPEN  # type: ignore[attr-defined]


@pytest.mark.unit
async def test_circuit_resets_on_success() -> None:
    cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=30)
    await cb.record_failure()
    await cb.record_failure()
    assert cb._state == CircuitState.OPEN  # type: ignore[attr-defined]
    cb._state = CircuitState.HALF_OPEN  # type: ignore[attr-defined]
    await cb.record_success()
    assert cb._state == CircuitState.CLOSED  # type: ignore[attr-defined]


@pytest.mark.unit
async def test_circuit_allow_request_closed() -> None:
    cb = CircuitBreaker(failure_threshold=5, cooldown_seconds=9999)
    allowed = await cb.allow_request()
    assert allowed is True


@pytest.mark.unit
async def test_circuit_blocks_when_open() -> None:
    cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=9999)
    await cb.record_failure()
    allowed = await cb.allow_request()
    assert allowed is False


# ── UpstreamConfig ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_upstream_config_defaults() -> None:
    cfg = UpstreamConfig(base_url="https://api.example.com")
    assert cfg.timeout == pytest.approx(30.0)
    assert cfg.max_retries == 3
    assert cfg.calls_per_second > 0


# ── UpstreamError ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_upstream_error_message() -> None:
    err = UpstreamError("AlphaFold", 503, "Service unavailable")
    assert "503" in str(err)
    assert "AlphaFold" in str(err)
    assert isinstance(err, Exception)
    assert err.status == 503
    assert err.upstream == "AlphaFold"


@pytest.mark.unit
async def test_request_lazily_enters_when_used_outside_context() -> None:
    """``_request`` is usable without an ``async with`` block: on first use it
    lazily calls ``__aenter__`` to construct the httpx client.

    Every other test drives clients through ``async with``, so this lazy-init
    arm is otherwise never executed. Driving the circuit breaker OPEN lets the
    request short-circuit immediately after the lazy init, with no network
    call, so the test stays deterministic and offline.
    """
    import time

    from alphafold_sovereign.clients._base import BaseAsyncClient, CircuitOpenError

    class _Probe(BaseAsyncClient):
        upstream_name = "probe"
        config = UpstreamConfig(base_url="https://example.invalid")

    client = _Probe()
    assert client._client is None  # type: ignore[attr-defined]

    # Force the breaker OPEN so _request raises right after the lazy __aenter__.
    client._circuit._state = CircuitState.OPEN  # type: ignore[attr-defined]
    client._circuit._opened_at = time.monotonic()  # type: ignore[attr-defined]

    with pytest.raises(CircuitOpenError):
        await client._request("GET", "/ping")

    # The lazy-init arm ran: the httpx client now exists. Close it cleanly.
    assert client._client is not None  # type: ignore[attr-defined]
    await client.__aexit__()
