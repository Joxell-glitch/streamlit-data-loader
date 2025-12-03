from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Iterable, List, Optional

import httpx
import websockets
from websockets.client import WebSocketClientProtocol

from src.config.models import APISettings
from src.core.logging import get_logger

logger = get_logger(__name__)


class HyperliquidClient:
    """Thin wrapper around Hyperliquid REST and WebSocket APIs."""

    def __init__(self, api_settings: APISettings, network: str = "mainnet") -> None:
        self.api_settings = api_settings
        self.network = network
        self._ws: Optional[WebSocketClientProtocol] = None
        self._ws_lock = asyncio.Lock()
        self._session = httpx.AsyncClient(timeout=10.0)
        self._connected_event = asyncio.Event()

    @property
    def rest_base(self) -> str:
        return self.api_settings.rest_base if self.network == "mainnet" else self.api_settings.testnet_rest_base

    @property
    def websocket_url(self) -> str:
        return self.api_settings.websocket_url if self.network == "mainnet" else self.api_settings.testnet_websocket_url

    async def fetch_info(self) -> Dict[str, Any]:
        url = f"{self.rest_base}{self.api_settings.info_path}"
        resp = await self._session.post(url, json={"type": "info"})
        resp.raise_for_status()
        return resp.json()

    async def fetch_spot_meta(self) -> Dict[str, Any]:
        url = f"{self.rest_base}{self.api_settings.info_path}"
        resp = await self._session.post(url, json={"type": "spotMeta"})
        resp.raise_for_status()
        return resp.json()

    async def fetch_orderbook_snapshot(self, coin: str) -> Dict[str, Any]:
        url = f"{self.rest_base}{self.api_settings.info_path}"
        resp = await self._session.post(url, json={"type": "l2Book", "coin": coin})
        resp.raise_for_status()
        return resp.json()

    async def connect_ws(self) -> None:
        async with self._ws_lock:
            if self._ws and not self._ws.closed:
                return
            backoff = 1
            while True:
                try:
                    logger.info("Connecting to Hyperliquid WebSocket: %s", self.websocket_url)
                    self._ws = await websockets.connect(self.websocket_url, ping_interval=20)
                    self._connected_event.set()
                    logger.info("WebSocket connected")
                    return
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("WebSocket connection failed: %s", exc)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30)

    async def subscribe_orderbooks(self, coins: Iterable[str]) -> None:
        await self._connected_event.wait()
        if not self._ws:
            raise RuntimeError("WebSocket not connected")
        sub = {"type": "subscribe", "subscriptions": [{"type": "l2Book", "coin": coin} for coin in coins]}
        await self._ws.send(json.dumps(sub))

    async def ws_messages(self):
        await self._connected_event.wait()
        assert self._ws is not None
        try:
            async for message in self._ws:
                yield json.loads(message)
        except websockets.ConnectionClosed as exc:
            logger.warning("WebSocket closed: %s", exc)
            self._connected_event.clear()
            await self.connect_ws()

    async def close(self) -> None:
        if self._ws and not self._ws.closed:
            await self._ws.close()
        await self._session.aclose()


async def stream_orderbooks(client: HyperliquidClient, coins: Iterable[str]):
    await client.connect_ws()
    await client.subscribe_orderbooks(coins)
    async for msg in client.ws_messages():
        yield msg
