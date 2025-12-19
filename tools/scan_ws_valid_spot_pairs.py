from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config.loader import load_config
from src.core.logging import setup_logging
from src.hyperliquid_client.client import HyperliquidClient


DEFAULT_TIMEOUT_SEC = 2.5
DEFAULT_CONCURRENCY = 10


@dataclass
class SpotPair:
    base: str
    quote: str
    pair: str
    index: int


@dataclass
class ScanResult:
    pair: SpotPair
    ok: bool
    fallback_used: bool
    primary_error: Optional[str]
    fallback_error: Optional[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan spot pairs for WS l2Book availability")
    parser.add_argument(
        "--config",
        default="config/config.yaml",
        help="Path to config file (default: config/config.yaml)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SEC,
        help="Seconds to wait for l2Book messages before falling back",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help="Maximum concurrent WS checks",
    )
    return parser.parse_args()


def _extract_universe(spot_meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates: Iterable[Tuple[str, Any]] = spot_meta.items() if isinstance(spot_meta, dict) else []
    for key, val in candidates:
        if key.lower() in {"universe", "spot_universe", "spots", "assets"} and isinstance(val, list):
            return list(val)
    if isinstance(spot_meta, list):
        return list(spot_meta)
    return []


def extract_spot_pairs(spot_meta: Dict[str, Any]) -> List[SpotPair]:
    universe = _extract_universe(spot_meta)
    pairs: List[SpotPair] = []
    for idx, entry in enumerate(universe):
        if not isinstance(entry, dict):
            continue
        base = (
            entry.get("name")
            or entry.get("base")
            or entry.get("coin")
            or entry.get("asset")
            or entry.get("symbol")
        )
        if not base:
            continue
        base = str(base).upper()
        quote = str(entry.get("quote") or "USDC").upper()
        pair_name = entry.get("pair") or f"{base}/{quote}"
        if "/" not in str(pair_name):
            pair_name = f"{pair_name}/{quote}"
        pair_name = str(pair_name).upper()
        pair_index = entry.get("index")
        try:
            index = int(pair_index) if pair_index is not None else int(idx)
        except Exception:
            index = int(idx)
        pairs.append(SpotPair(base=base, quote=quote, pair=pair_name, index=index))
    return pairs


def looks_like_l2book(msg: Dict[str, Any]) -> bool:
    def _check(payload: Dict[str, Any]) -> bool:
        kind = payload.get("type") or payload.get("channel")
        if isinstance(kind, str) and kind.lower() == "l2book":
            return True
        return "bids" in payload or "asks" in payload or "levels" in payload

    if not isinstance(msg, dict):
        return False
    if _check(msg):
        return True
    for key in ("data", "result", "payload"):
        val = msg.get(key)
        if isinstance(val, dict) and _check(val):
            return True
    return False


async def subscribe_and_wait(ws_url: str, coin: str, timeout: float) -> Tuple[bool, Optional[str]]:
    start = time.monotonic()
    try:
        async with websockets.connect(ws_url) as ws:
            await ws.send(json.dumps({"method": "subscribe", "subscription": {"type": "l2Book", "coin": coin}}))
            while True:
                remaining = timeout - (time.monotonic() - start)
                if remaining <= 0:
                    return False, "timeout"
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    return False, "timeout"
                except (ConnectionClosed, WebSocketException) as exc:
                    return False, f"closed:{type(exc).__name__}"
                if raw is None:
                    return False, "empty"
                try:
                    msg: Dict[str, Any] = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if looks_like_l2book(msg):
                    return True, None
    except (ConnectionClosed, WebSocketException) as exc:
        return False, f"closed:{type(exc).__name__}"
    except Exception as exc:  # pragma: no cover - defensive
        return False, str(exc)


async def scan_pair(ws_url: str, pair: SpotPair, timeout: float) -> ScanResult:
    primary_coin = f"@{pair.index}"
    ok_primary, err_primary = await subscribe_and_wait(ws_url, primary_coin, timeout)
    if ok_primary:
        return ScanResult(pair=pair, ok=True, fallback_used=False, primary_error=None, fallback_error=None)

    ok_fallback, err_fallback = await subscribe_and_wait(ws_url, pair.pair, timeout)
    return ScanResult(
        pair=pair,
        ok=ok_fallback,
        fallback_used=ok_fallback,
        primary_error=err_primary,
        fallback_error=err_fallback,
    )


def print_result(result: ScanResult) -> None:
    status = "OK"
    if result.ok and result.fallback_used:
        status = "OK (fallback BASE/QUOTE)"
    elif not result.ok:
        status = "FAIL"

    line = f"{result.pair.base} | @{result.pair.index} {result.pair.pair} | {status}"

    if not result.ok:
        details = []
        if result.primary_error:
            details.append(f"primary={result.primary_error}")
        if result.fallback_error:
            details.append(f"fallback={result.fallback_error}")
        if details:
            line = f"{line} [{' ; '.join(details)}]"

    print(line)


async def main_async() -> None:
    args = parse_args()

    settings = load_config(args.config)
    setup_logging(settings.logging)
    client = HyperliquidClient(settings.api, settings.network)
    spot_meta = await client.fetch_spot_meta()
    ws_url = client.websocket_url
    pairs = extract_spot_pairs(spot_meta)
    await client.close()

    if not pairs:
        print("No spot pairs found in spotMeta response")
        return

    semaphore = asyncio.Semaphore(max(1, args.concurrency))

    async def _run_with_semaphore(p: SpotPair) -> ScanResult:
        async with semaphore:
            return await scan_pair(ws_url, p, args.timeout)

    tasks = [asyncio.create_task(_run_with_semaphore(pair)) for pair in pairs]
    results = await asyncio.gather(*tasks)

    for res in sorted(results, key=lambda r: r.pair.index):
        print_result(res)


if __name__ == "__main__":
    asyncio.run(main_async())
