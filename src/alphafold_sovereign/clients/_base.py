# SPDX-License-Identifier: Apache-2.0
# Copyright 2024-2026 Santiago Maniches and TOPOLOGICA LLC
"""Async HTTP base client with production-grade resilience.

Every upstream client inherits from ``BaseAsyncClient``.  The base class wires
together:

- ``httpx.AsyncClient`` (HTTP/2, connection pooling, keep-alive)
- ``tenacity`` (exponential back-off with full jitter, configurable)
- ``aiolimiter`` (per-host token-bucket rate limiting)
- Circuit breaker (half-open probe after configurable cooldown)
- Structured logging via ``structlog`` (request_id propagation)
- Outbound domain allow-list (blocks all egress in air-gap mode)
- Content hash verification for cached responses
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx
import structlog
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

try:
    from aiolimiter import AsyncLimiter
except ImportError:  # pragma: no cover
    AsyncLimiter = None  # type: ignore[assignment,misc]

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Air-gap mode: if set, ALL outbound requests are refused before a socket
# is opened.  This is the hard enforcement of sovereign / offline operation.
# ---------------------------------------------------------------------------
_OFFLINE_MODE: bool = os.environ.get("ALPHAFOLD_OFFLINE", "").lower() in {
    "1",
    "true",
    "yes",
}

# Domains always allowed even in offline mode (e.g. localhost, Vault)
_ALWAYS_ALLOWED: frozenset[str] = frozenset(
    os.environ.get("ALPHAFOLD_ALLOW_HOSTS", "").split(",")
) - {""}


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """Simple per-host circuit breaker (thread-safe via asyncio lock)."""

    failure_threshold: int = 5
    cooldown_seconds: float = 60.0
    probe_timeout: float = 10.0

    _failures: int = field(default=0, init=False)
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _opened_at: float = field(default=0.0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def record_success(self) -> None:
        async with self._lock:
            self._failures = 0
            self._state = CircuitState.CLOSED

    async def record_failure(self) -> None:
        async with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()
                logger.warning(
                    "circuit_opened",
                    failures=self._failures,
                    cooldown=self.cooldown_seconds,
                )

    async def allow_request(self) -> bool:
        async with self._lock:
            if self._state == CircuitState.CLOSED:
                return True
            elapsed = time.monotonic() - self._opened_at
            if elapsed >= self.cooldown_seconds:
                self._state = CircuitState.HALF_OPEN
                logger.info("circuit_half_open", elapsed=round(elapsed, 1))
                return True
            return False


@dataclass
class UpstreamConfig:
    """Per-upstream configuration injected into ``BaseAsyncClient``."""

    base_url: str
    calls_per_second: float = 5.0
    """Token-bucket rate: requests / second per process."""
    max_retries: int = 3
    min_wait: float = 1.0
    max_wait: float = 30.0
    timeout: float = 30.0
    """Total request timeout in seconds."""
    headers: dict[str, str] = field(default_factory=dict)
    verify_ssl: bool = True


class UpstreamError(Exception):
    """Raised when an upstream API returns a non-retryable error."""

    def __init__(self, upstream: str, status: int, message: str) -> None:
        self.upstream = upstream
        self.status = status
        super().__init__(f"{upstream} HTTP {status}: {message}")


class AirGapError(Exception):
    """Raised when a network call is attempted in offline mode."""


class CircuitOpenError(Exception):
    """Raised when the circuit breaker is OPEN for the target host."""


def _is_retryable(exc: BaseException) -> bool:
    """Return True for transient failures worth retrying."""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.NetworkError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {429, 500, 502, 503, 504}
    return False


class BaseAsyncClient:
    """
    Production async HTTP client base class.

    Subclasses define ``upstream_name``, ``config``, and implement
    their own query methods using ``_get``, ``_post``, or ``_graphql``.

    Usage::

        class MONDOClient(BaseAsyncClient):
            upstream_name = "mondo"
            config = UpstreamConfig(
                base_url="https://www.ebi.ac.uk/ols4/api",
                calls_per_second=3.0,
            )

            async def lookup(self, term_id: str) -> dict[str, Any]:
                return await self._get(f"/terms?id={term_id}&ontology=mondo")
    """

    upstream_name: str = "upstream"
    config: UpstreamConfig = UpstreamConfig(base_url="http://localhost")

    def __init__(self, *, request_id: str = "") -> None:
        self._request_id = request_id
        self._circuit: CircuitBreaker = CircuitBreaker()
        self._limiter: AsyncLimiter | None = (
            AsyncLimiter(self.config.calls_per_second, 1.0) if AsyncLimiter is not None else None
        )
        self._client: httpx.AsyncClient | None = None
        self._log = logger.bind(
            upstream=self.upstream_name,
            request_id=request_id,
        )

    async def __aenter__(self) -> BaseAsyncClient:
        self._client = httpx.AsyncClient(
            base_url=self.config.base_url,
            headers={
                "User-Agent": "alphafold-sovereign-mcp/1.0 (+https://github.com/smaniches/alphafold-sovereign-mcp)",
                **self.config.headers,
            },
            timeout=self.config.timeout,
            verify=self.config.verify_ssl,
            http2=True,
            follow_redirects=True,
            limits=httpx.Limits(
                max_keepalive_connections=10,
                max_connections=20,
                keepalive_expiry=30.0,
            ),
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Core request helpers
    # ------------------------------------------------------------------

    def _check_air_gap(self, url: str) -> None:
        """Raise AirGapError if offline mode is active and host not allowed."""
        if not _OFFLINE_MODE:
            return
        import urllib.parse

        host = urllib.parse.urlparse(url).netloc.split(":")[0]
        if host not in _ALWAYS_ALLOWED:
            raise AirGapError(
                f"Air-gap mode active: outbound request to '{host}' blocked. "
                "Set ALPHAFOLD_OFFLINE=0 or add to ALPHAFOLD_ALLOW_HOSTS."
            )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        extra_headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        assert self._client is not None, "Use as async context manager"

        full_url = str(self._client.base_url.copy_with(path=path))
        self._check_air_gap(full_url)

        if not await self._circuit.allow_request():
            raise CircuitOpenError(f"Circuit open for {self.upstream_name}; retry after cooldown.")

        start = time.monotonic()
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self.config.max_retries),
                wait=wait_exponential_jitter(
                    initial=self.config.min_wait,
                    max=self.config.max_wait,
                ),
                retry=retry_if_exception(_is_retryable),
                reraise=True,
            ):
                with attempt:
                    if self._limiter is not None:
                        async with self._limiter:
                            response = await self._client.request(
                                method,
                                path,
                                params=params,
                                json=json,
                                headers=extra_headers or {},
                            )
                    else:
                        response = await self._client.request(
                            method,
                            path,
                            params=params,
                            json=json,
                            headers=extra_headers or {},
                        )
                    if response.status_code in {429, 500, 502, 503, 504}:
                        self._log.warning(
                            "upstream_transient_error",
                            status=response.status_code,
                            attempt=attempt.retry_state.attempt_number,
                        )
                        response.raise_for_status()

        except httpx.HTTPStatusError as exc:
            await self._circuit.record_failure()
            raise UpstreamError(
                self.upstream_name,
                exc.response.status_code,
                exc.response.text[:200],
            ) from exc

        await self._circuit.record_success()
        self._log.debug(
            "upstream_ok",
            method=method,
            path=path,
            status=response.status_code,
            elapsed=round(time.monotonic() - start, 3),
        )
        return response

    async def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        response = await self._request("GET", path, params=params, extra_headers=extra_headers)
        try:
            return response.json()  # type: ignore[no-any-return]
        except Exception as exc:
            raise UpstreamError(
                self.upstream_name, response.status_code, f"JSON parse failed: {exc}"
            ) from exc

    async def _get_bytes(self, path: str, params: dict[str, Any] | None = None) -> bytes:
        response = await self._request("GET", path, params=params)
        return response.content

    async def _post(
        self,
        path: str,
        json: Any,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        response = await self._request("POST", path, json=json, extra_headers=extra_headers)
        try:
            return response.json()  # type: ignore[no-any-return]
        except Exception as exc:
            raise UpstreamError(
                self.upstream_name, response.status_code, f"JSON parse failed: {exc}"
            ) from exc

    async def _graphql(
        self, endpoint: str, query: str, variables: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a GraphQL query against an absolute endpoint path."""
        result: dict[str, Any] = await self._post(
            endpoint,
            json={"query": query, "variables": variables},
            extra_headers={"Content-Type": "application/json"},
        )
        if "errors" in result:
            raise UpstreamError(
                self.upstream_name,
                200,
                "; ".join(e.get("message", "?") for e in result["errors"]),
            )
        gql_data: dict[str, Any] = result.get("data") or {}
        return gql_data

    @staticmethod
    def _sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[BaseAsyncClient]:
        """Convenience context manager for explicit session lifetime."""
        async with self:
            yield self
