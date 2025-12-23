import asyncio
import pytest

from src.config.models import APISettings
from src.hyperliquid_client.client import HyperliquidClient


def _make_client() -> HyperliquidClient:
    api_settings = APISettings(
        rest_base="https://example.com",
        info_path="/info",
        websocket_url="wss://example.com/ws",
        testnet_rest_base="https://test.example.com",
        testnet_websocket_url="wss://test.example.com/ws",
    )
    return HyperliquidClient(api_settings)


def test_extract_spot_ws_coin_from_universe():
    universe = [
        {"name": "PURR/USDC", "index": 0},
        {"name": "FOO/USDC", "index": 3},
    ]

    ws_coin = HyperliquidClient.extract_spot_ws_coin_from_universe(universe, "PURR/USDC")

    assert ws_coin == "@0"


def test_resolve_spot_ws_coin_prefers_pair_when_unresolved(monkeypatch: pytest.MonkeyPatch):
    client = _make_client()

    async def _noop_resolve(*_: str) -> None:
        return None

    monkeypatch.setattr(client, "_resolve_spot_ws_coin_from_universe", _noop_resolve)

    primary, fallback = asyncio.run(client._resolve_spot_ws_coin("PURR", "PURR/USDC"))

    assert primary == "PURR/USDC"
    assert fallback == "PURR/USDC"
    assert client.get_resolved_spot_coin("PURR") == "PURR/USDC"


def test_resolve_spot_ws_coin_prefers_index(monkeypatch: pytest.MonkeyPatch):
    client = _make_client()

    async def _fake_meta_fetch(*_: str, **__: str):
        return {
            "spotMeta": {
                "tokens": [
                    {"index": 0, "name": "ETH"},
                    {"index": 1, "name": "USDC"},
                ],
                "universe": [
                    {
                        "tokens": [0, 1],
                        "index": 142,
                        "name": "ETH/USDC",
                        "isCanonical": True,
                    }
                ],
            }
        }

    monkeypatch.setattr(client, "fetch_spot_meta_and_asset_ctxs", _fake_meta_fetch)

    primary, fallback = asyncio.run(client._resolve_spot_ws_coin("ETH", "ETH/USDC"))

    assert primary == "@142"
    assert fallback == "@142"
    assert client.get_resolved_spot_coin("ETH") == "@142"


def test_resolve_spot_ws_coin_falls_back_to_u_prefix_pair(monkeypatch: pytest.MonkeyPatch):
    client = _make_client()

    async def _fake_meta_fetch(*_: str, **__: str):
        return {
            "spotMeta": {
                "tokens": [
                    {"index": 0, "name": "USDC"},
                    {"index": 221, "name": "UETH"},
                ],
                "universe": [
                    {
                        "tokens": [221, 0],
                        "index": 151,
                        "name": "@151",
                        "isCanonical": False,
                    }
                ],
            }
        }

    monkeypatch.setattr(client, "fetch_spot_meta_and_asset_ctxs", _fake_meta_fetch)

    resolved = asyncio.run(client._resolve_spot_ws_coin_from_universe("ETH", "ETH/USDC"))

    assert resolved == "@151"


def test_resolve_spot_ws_coin_uses_canonical_pair(monkeypatch: pytest.MonkeyPatch):
    client = _make_client()

    async def _fail_resolve(*_: str) -> None:
        raise AssertionError("should not call universe resolve for canonical pairs")

    monkeypatch.setattr(client, "_resolve_spot_ws_coin_from_universe", _fail_resolve)

    primary, fallback = asyncio.run(client._resolve_spot_ws_coin("purr", "purr/usdc"))

    assert primary == "PURR/USDC"
    assert fallback == "PURR/USDC"
    assert client.get_resolved_spot_coin("purr") == "PURR/USDC"
