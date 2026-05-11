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
