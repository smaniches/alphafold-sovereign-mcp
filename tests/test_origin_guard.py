"""Adversarial tests for per-upstream HTTP origin enforcement."""

from __future__ import annotations

import httpx
import pytest
import respx

import alphafold_sovereign.clients._base as base_mod
from alphafold_sovereign.clients._base import BaseAsyncClient, UpstreamConfig


class _OriginProbe(BaseAsyncClient):
    upstream_name = "origin-probe"
    config = UpstreamConfig(
        base_url="https://api.example.test",
        calls_per_second=100.0,
        max_retries=1,
    )


async def test_same_origin_redirect_is_followed(respx_mock: respx.MockRouter) -> None:
    start = respx_mock.get("https://api.example.test/start").mock(
        return_value=httpx.Response(307, headers={"Location": "/final"})
    )
    final = respx_mock.get("https://api.example.test/final").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    async with _OriginProbe() as client:
        result = await client._get("/start")

    assert start.called
    assert final.called
    assert result == {"ok": True}


async def test_cross_origin_redirect_is_blocked_before_dispatch(
    respx_mock: respx.MockRouter,
) -> None:
    start = respx_mock.get("https://api.example.test/start").mock(
        return_value=httpx.Response(
            307,
            headers={"Location": "https://evil.example/steal?api_key=secret"},
        )
    )
    escaped = respx_mock.get("https://evil.example/steal?api_key=secret").mock(
        return_value=httpx.Response(200, json={"unexpected": True})
    )

    async with _OriginProbe() as client:
        with pytest.raises(base_mod.UpstreamOriginError) as exc_info:
            await client._get("/start")

    assert start.called
    assert not escaped.called
    assert "evil.example" in str(exc_info.value)
    assert "secret" not in str(exc_info.value)


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.test/insecure",
        "https://api.example.test:444/alternate-port",
        "https://evil.example/other-host",
    ],
)
async def test_absolute_cross_origin_request_is_blocked(url: str) -> None:
    async with _OriginProbe() as client:
        with pytest.raises(base_mod.UpstreamOriginError):
            await client._get(url)


async def test_same_origin_absolute_file_url_is_allowed(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("https://api.example.test/files/model.pdb").mock(
        return_value=httpx.Response(200, content=b"ATOM")
    )

    async with _OriginProbe() as client:
        body = await client._get_bytes("https://api.example.test/files/model.pdb")

    assert route.called
    assert body == b"ATOM"
