from __future__ import annotations

import argparse
import asyncio
import contextlib
import time
from typing import Any, Callable, Dict, Iterable, Tuple

from src.config.loader import load_config
from src.core.logging import setup_logging
from src.hyperliquid_client.client import HyperliquidClient


def _best_price(levels: Iterable[Any], reverse: bool) -> float:
    best = None
    for level in levels or []:
        price = None
        if isinstance(level, (list, tuple)) and level:
            try:
                price = float(level[0])
            except Exception:
                price = None
        elif isinstance(level, dict):
            candidate = level.get("px") or level.get("price") or level.get("p")
            try:
                price = float(candidate)
            except Exception:
                price = None
        if price is None:
            continue
        if best is None:
            best = price
        else:
            best = max(best, price) if reverse else min(best, price)
    return float(best or 0.0)


def _extract_best(snapshot: Dict[str, Any]) -> Tuple[float, float]:
    bids = snapshot.get("bids", []) if isinstance(snapshot, dict) else []
    asks = snapshot.get("asks", []) if isinstance(snapshot, dict) else []
    best_bid = snapshot.get("bid")
    best_ask = snapshot.get("ask")
    if best_bid is None:
        best_bid = _best_price(bids, reverse=True)
    if best_ask is None:
        best_ask = _best_price(asks, reverse=False)
    return float(best_bid or 0.0), float(best_ask or 0.0)


async def _subscribe_books(client: HyperliquidClient, symbol_map: Dict[str, str], kind: str) -> None:
    await client.connect_ws()
    await client.subscribe_orderbooks(symbol_map, kind=kind)


async def main(duration: float, timeout: float) -> None:
    settings = load_config("config/config.yaml")
    setup_logging(settings.logging)

    spot_pair = "PURR/USDC"
    perp_coin = "PURR"

    spot_client = HyperliquidClient(settings.api, settings.network)
    perp_client = HyperliquidClient(settings.api, settings.network)

    first_received = {"spot": asyncio.Event(), "perp": asyncio.Event()}

    def _make_listener(kind: str, client: HyperliquidClient) -> Callable[[str, str, Dict[str, Any]], None]:
        def _listener(_: str, asset: str, snapshot: Dict[str, Any]) -> None:
            now = time.time()
            best_bid, best_ask = _extract_best(snapshot)
            coin = asset
            if kind == "spot":
                coin = client.get_resolved_spot_coin(asset) or client.get_resolved_spot_coin(spot_pair) or asset
            timestamp = time.strftime("%H:%M:%S", time.localtime(now))
            print(f"{timestamp} [{kind.upper()}] coin={coin} bid={best_bid:.8f} ask={best_ask:.8f}")
            if not first_received[kind].is_set():
                first_received[kind].set()

        return _listener

    spot_client.add_orderbook_listener(_make_listener("spot", spot_client))
    perp_client.add_orderbook_listener(_make_listener("perp", perp_client))

    spot_symbol_map = {spot_client._normalize_spot_symbol(spot_pair): spot_pair}
    perp_symbol_map = {perp_client._normalize_perp_symbol(perp_coin): perp_coin}

    await asyncio.gather(
        _subscribe_books(spot_client, spot_symbol_map, kind="spot"),
        _subscribe_books(perp_client, perp_symbol_map, kind="perp"),
    )

    async def _timeout(kind: str) -> None:
        try:
            await asyncio.wait_for(first_received[kind].wait(), timeout=timeout)
        except asyncio.TimeoutError:
            print(f"TIMEOUT kind={kind.upper()}")

    timeout_tasks = [
        asyncio.create_task(_timeout("spot")),
        asyncio.create_task(_timeout("perp")),
    ]

    start = time.time()
    try:
        while time.time() - start < duration:
            await asyncio.sleep(0.5)
    finally:
        for task in timeout_tasks:
            task.cancel()
        with contextlib.suppress(Exception):
            await asyncio.gather(*timeout_tasks)
        await asyncio.gather(spot_client.close(), perp_client.close())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Smoke test for PURR spot/perp l2Book feeds.")
    parser.add_argument("--duration", type=float, default=10.0, help="Seconds to stream updates.")
    parser.add_argument("--timeout", type=float, default=5.0, help="Seconds before emitting TIMEOUT per feed.")
    args = parser.parse_args()

    asyncio.run(main(args.duration, args.timeout))
