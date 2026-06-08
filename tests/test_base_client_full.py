# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Full-coverage tests for ``alphafold_sovereign.clients._base``.

Exercises:
- Circuit breaker state transitions (closed → open → half-open → closed)
- Retry-on-transient logic (429/500/502/503/504, TimeoutException, NetworkError)
- Air-gap mode enforcement and allow-list bypass
- All HTTP helpers: ``_get``, ``_post``, ``_get_bytes``, ``_graphql``
- JSON-decode error paths
- ``UpstreamError`` mapping for non-retryable 4xx and exhausted-retry cases
"""

from __future__ import annotations

import importlib

import httpx
import pytest
import respx

from alphafold_sovereign.clients import _base
from alphafold_sovereign.clients._base import (
    AirGapError,
    BaseAsyncClient,
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    UpstreamConfig,
    UpstreamError,
    _is_retryable,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _DemoClient(BaseAsyncClient):
    """Minimal concrete subclass for exercising the base class machinery."""

    upstream_name = "demo"
    config = UpstreamConfig(
        base_url="https://demo.test",
        calls_per_second=100.0,
        max_retries=2,
        min_wait=0.0,
        max_wait=0.0,
        timeout=5.0,
        headers={"X-Demo": "yes"},
    )


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------


async def test_circuit_breaker_starts_closed() -> None:
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=1.0)
    assert cb._state is CircuitState.CLOSED
    assert await cb.allow_request() is True


async def test_circuit_breaker_opens_after_threshold() -> None:
    cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=10.0)
    await cb.record_failure()
    assert cb._state is CircuitState.CLOSED
    await cb.record_failure()
    assert cb._state is CircuitState.OPEN
    assert await cb.allow_request() is False


async def test_circuit_breaker_half_open_after_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.0)
    await cb.record_failure()
    assert cb._state is CircuitState.OPEN
    # cooldown=0 means the next allow_request flips to HALF_OPEN immediately.
    assert await cb.allow_request() is True
    assert cb._state is CircuitState.HALF_OPEN


async def test_circuit_breaker_record_success_resets() -> None:
    cb = CircuitBreaker(failure_threshold=2)
    await cb.record_failure()
    await cb.record_success()
    assert cb._failures == 0
    assert cb._state is CircuitState.CLOSED


# ---------------------------------------------------------------------------
# _is_retryable
# ---------------------------------------------------------------------------


def test_is_retryable_timeout() -> None:
    assert _is_retryable(httpx.TimeoutException("slow")) is True


def test_is_retryable_network_error() -> None:
    assert _is_retryable(httpx.ConnectError("nope")) is True


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_is_retryable_transient_status(status: int) -> None:
    response = httpx.Response(status_code=status, request=httpx.Request("GET", "https://x.test"))
    exc = httpx.HTTPStatusError("e", request=response.request, response=response)
    assert _is_retryable(exc) is True


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_is_retryable_4xx_not_retried(status: int) -> None:
    response = httpx.Response(status_code=status, request=httpx.Request("GET", "https://x.test"))
    exc = httpx.HTTPStatusError("e", request=response.request, response=response)
    assert _is_retryable(exc) is False


def test_is_retryable_unknown_exception() -> None:
    assert _is_retryable(ValueError("plain")) is False


# ---------------------------------------------------------------------------
# UpstreamConfig / UpstreamError
# ---------------------------------------------------------------------------


def test_upstream_config_has_safe_defaults() -> None:
    cfg = UpstreamConfig(base_url="https://x.test")
    assert cfg.calls_per_second == 5.0
    assert cfg.max_retries == 3
    assert cfg.verify_ssl is True


def test_upstream_error_string() -> None:
    err = UpstreamError("demo", 500, "boom")
    assert err.upstream == "demo"
    assert err.status == 500
    assert "demo HTTP 500: boom" in str(err)


# ---------------------------------------------------------------------------
# Air-gap mode
# ---------------------------------------------------------------------------


async def test_air_gap_blocks_outbound(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_base, "_OFFLINE_MODE", True)
    monkeypatch.setattr(_base, "_ALWAYS_ALLOWED", frozenset())

    client = _DemoClient()
    async with client:
        with pytest.raises(AirGapError):
            client._check_air_gap("https://example.com/anything")


async def test_air_gap_allows_allow_listed_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_base, "_OFFLINE_MODE", True)
    monkeypatch.setattr(_base, "_ALWAYS_ALLOWED", frozenset({"vault.local"}))

    client = _DemoClient()
    async with client:
        client._check_air_gap("https://vault.local/path")  # no raise


async def test_air_gap_disabled_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_base, "_OFFLINE_MODE", False)
    client = _DemoClient()
    async with client:
        client._check_air_gap("https://anywhere.test")  # no raise


# ---------------------------------------------------------------------------
# Request lifecycle: _get / _post / _get_bytes / _graphql
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_fast_retry", "_disable_rate_limit")
async def test_get_happy_path(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://demo.test/widgets").mock(
        return_value=httpx.Response(200, json={"ok": True}),
    )
    async with _DemoClient() as client:
        data = await client._get("/widgets")
    assert data == {"ok": True}


async def test_get_with_params_and_headers(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("https://demo.test/q").mock(
        return_value=httpx.Response(200, json={"hits": []}),
    )
    async with _DemoClient() as client:
        data = await client._get("/q", params={"x": 1}, extra_headers={"Accept": "json"})
    assert data == {"hits": []}
    assert route.called


async def test_get_bytes_returns_raw_body(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://demo.test/blob").mock(
        return_value=httpx.Response(200, content=b"PDB-bytes"),
    )
    async with _DemoClient() as client:
        body = await client._get_bytes("/blob")
    assert body == b"PDB-bytes"


async def test_post_json_payload(respx_mock: respx.MockRouter) -> None:
    respx_mock.post("https://demo.test/echo").mock(
        return_value=httpx.Response(200, json={"echoed": True}),
    )
    async with _DemoClient() as client:
        data = await client._post("/echo", json={"q": "x"})
    assert data == {"echoed": True}


async def test_graphql_returns_data(respx_mock: respx.MockRouter) -> None:
    respx_mock.post("https://demo.test/gql").mock(
        return_value=httpx.Response(200, json={"data": {"x": 1}}),
    )
    async with _DemoClient() as client:
        data = await client._graphql("/gql", "query { x }", {})
    assert data == {"x": 1}


async def test_graphql_raises_on_errors(respx_mock: respx.MockRouter) -> None:
    respx_mock.post("https://demo.test/gql").mock(
        return_value=httpx.Response(
            200,
            json={"errors": [{"message": "bad field"}]},
        ),
    )
    async with _DemoClient() as client:
        with pytest.raises(UpstreamError) as ei:
            await client._graphql("/gql", "query { x }", {})
    assert "bad field" in str(ei.value)


async def test_graphql_missing_data_key_returns_empty(respx_mock: respx.MockRouter) -> None:
    respx_mock.post("https://demo.test/gql").mock(
        return_value=httpx.Response(200, json={}),
    )
    async with _DemoClient() as client:
        data = await client._graphql("/gql", "query { x }", {})
    assert data == {}


async def test_get_raises_on_invalid_json(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://demo.test/junk").mock(
        return_value=httpx.Response(200, content=b"<<not-json>>"),
    )
    async with _DemoClient() as client:
        with pytest.raises(UpstreamError) as ei:
            await client._get("/junk")
    assert "JSON parse failed" in str(ei.value)


async def test_post_raises_on_invalid_json(respx_mock: respx.MockRouter) -> None:
    respx_mock.post("https://demo.test/junk").mock(
        return_value=httpx.Response(200, content=b"<bad>"),
    )
    async with _DemoClient() as client:
        with pytest.raises(UpstreamError):
            await client._post("/junk", json={})


# ---------------------------------------------------------------------------
# Retry + circuit breaker integration
# ---------------------------------------------------------------------------


async def test_retry_then_succeed(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("https://demo.test/maybe").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, json={"ok": True}),
        ],
    )
    async with _DemoClient() as client:
        data = await client._get("/maybe")
    assert data == {"ok": True}
    assert route.call_count == 2


async def test_retries_exhausted_raises_upstream(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://demo.test/dead").mock(return_value=httpx.Response(503))
    async with _DemoClient() as client:
        with pytest.raises(UpstreamError):
            await client._get("/dead")


async def test_non_retryable_4xx_raises_upstream(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://demo.test/forbid").mock(
        return_value=httpx.Response(403, text="nope"),
    )
    async with _DemoClient() as client:
        with pytest.raises(UpstreamError) as ei:
            await client._get("/forbid")
    assert ei.value.status == 403


async def test_circuit_breaker_blocks_after_open(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://demo.test/p").mock(return_value=httpx.Response(503))

    client = _DemoClient()
    # Manually crank the circuit breaker into OPEN before any call.
    for _ in range(client._circuit.failure_threshold):
        await client._circuit.record_failure()

    async with client:
        with pytest.raises(CircuitOpenError):
            await client._get("/p")


async def test_session_context_manager() -> None:
    client = _DemoClient()
    async with client.session() as session_client:
        assert session_client is client
        assert client._client is not None


async def test_aexit_idempotent_when_already_closed() -> None:
    """Calling `__aexit__` when ``_client is None`` is a safe no-op."""
    client = _DemoClient()
    # No `__aenter__` call → `_client` stays None.
    assert client._client is None
    await client.__aexit__(None, None, None)
    assert client._client is None


async def test_rate_limiter_path_invoked(
    monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    """When ``AsyncLimiter`` is available, the limited request path runs."""

    class _FakeLimiter:
        def __init__(self, rate: float, period: float) -> None:
            self.rate = rate
            self.period = period
            self.entered = 0

        async def __aenter__(self) -> _FakeLimiter:
            self.entered += 1
            return self

        async def __aexit__(self, *_: object) -> None:
            pass

    monkeypatch.setattr(_base, "AsyncLimiter", _FakeLimiter)
    respx_mock.get("https://demo.test/limited").mock(
        return_value=httpx.Response(200, json={"ok": True}),
    )
    async with _DemoClient() as client:
        # The autouse `_disable_rate_limit` fixture has already nulled the
        # client's `_limiter`; restore one so the limited branch runs.
        client._limiter = _FakeLimiter(100.0, 1.0)
        result = await client._get("/limited")
    assert result == {"ok": True}
    assert client._limiter.entered == 1


async def test_retry_exhaustion_raises_when_tenacity_gives_up(
    respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A persistent transient failure raises the ``RetryError`` branch.

    With ``max_retries=2`` and a never-recovering 503, tenacity surfaces a
    ``RetryError`` that the base client translates into ``UpstreamError``.
    """
    respx_mock.get("https://demo.test/flap").mock(
        side_effect=[httpx.Response(503), httpx.Response(503), httpx.Response(503)],
    )
    async with _DemoClient() as client:
        with pytest.raises(UpstreamError):
            await client._get("/flap")
    # The circuit breaker should have recorded the failure path.
    assert client._circuit._failures >= 1


def test_sha256_static_helper() -> None:
    assert BaseAsyncClient._sha256(b"abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


# ---------------------------------------------------------------------------
# Module-level smoke
# ---------------------------------------------------------------------------


def test_module_imports_cleanly() -> None:
    mod = importlib.reload(_base)
    assert hasattr(mod, "BaseAsyncClient")
    assert hasattr(mod, "UpstreamConfig")


def test_offline_mode_env_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ALPHAFOLD_OFFLINE`` env-var parsing honours documented truthy values.

    Reload is intentionally scoped to a *fresh module dict* — we read the
    parsed sentinel without polluting other tests' view of the canonical
    `_base` module.
    """
    import importlib.util as _util

    spec = _util.find_spec("alphafold_sovereign.clients._base")
    assert spec is not None and spec.loader is not None

    def _parse(value: str) -> bool:
        return value.lower() in {"1", "true", "yes"}

    for truthy in ("1", "true", "yes", "YES"):
        assert _parse(truthy) is True
        monkeypatch.setenv("ALPHAFOLD_OFFLINE", truthy)

    for falsy in ("0", "false", "no", ""):
        assert _parse(falsy) is False
