from __future__ import annotations

from dataclasses import dataclass
from math import inf
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.core.logging import get_logger
from src.hyperliquid_client.client import HyperliquidClient


logger = get_logger(__name__)


@dataclass(frozen=True)
class AutoAssetCandidate:
    symbol: str
    spread: Optional[float]
    volume_24h: Optional[float]


def _extract_meta_payload(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        merged: Dict[str, Any] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            for key in ("universe", "tokens", "spotMeta", "assetCtxs"):
                if key in item and key not in merged:
                    merged[key] = item[key]
        return merged
    return {}


def _spot_universe_and_tokens(spot_meta: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    universe = spot_meta.get("universe") or []
    tokens = spot_meta.get("tokens") or []
    spot_meta_data = spot_meta.get("spotMeta")
    if isinstance(spot_meta_data, dict):
        tokens = tokens + (spot_meta_data.get("tokens") or [])
        universe = spot_meta_data.get("universe") or universe
    return universe, tokens


def _spot_base_symbols(spot_meta: Dict[str, Any]) -> set[str]:
    bases: set[str] = set()
    universe, tokens = _spot_universe_and_tokens(spot_meta)
    token_map = {
        token.get("index"): str(token.get("name")).upper()
        for token in tokens
        if token.get("index") is not None and token.get("name")
    }
    for entry in universe:
        if not isinstance(entry, dict):
            continue
        if token_map and isinstance(entry.get("tokens"), list) and len(entry["tokens"]) == 2:
            base_id = entry["tokens"][0]
            base = token_map.get(base_id)
        else:
            base = entry.get("base") or entry.get("coin") or entry.get("name") or entry.get("symbol")
        if base:
            bases.add(str(base).upper())
    return bases


def _perp_base_symbols(perp_meta: Dict[str, Any]) -> set[str]:
    bases: set[str] = set()
    for entry in perp_meta.get("universe", []) or []:
        if not isinstance(entry, dict):
            continue
        symbol = entry.get("name") or entry.get("symbol") or entry.get("coin") or entry.get("base")
        if symbol:
            bases.add(str(symbol).upper())
    return bases


def _asset_contexts(spot_meta: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    contexts: Dict[str, Dict[str, Any]] = {}
    for ctx in spot_meta.get("assetCtxs", []) or []:
        if not isinstance(ctx, dict):
            continue
        coin = ctx.get("coin") or ctx.get("base") or ctx.get("name")
        if coin:
            contexts[str(coin).upper()] = ctx
    return contexts


def _parse_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _spread_proxy(ctx: Dict[str, Any]) -> Optional[float]:
    bid = _parse_float(ctx.get("bidPx") or ctx.get("bestBid") or ctx.get("bid"))
    ask = _parse_float(ctx.get("askPx") or ctx.get("bestAsk") or ctx.get("ask"))
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None
    mid = _parse_float(ctx.get("midPx") or ctx.get("markPx"))
    if mid is None or mid <= 0:
        mid = (bid + ask) / 2
    return (ask - bid) / mid if mid else None


def _volume_proxy(ctx: Dict[str, Any]) -> Optional[float]:
    return _parse_float(
        ctx.get("dayNtlVlm")
        or ctx.get("volume24h")
        or ctx.get("volume")
        or ctx.get("dayNotionalVolume")
    )


def select_auto_assets_from_meta(
    spot_meta_raw: Any,
    perp_meta_raw: Any,
    *,
    limit: int = 15,
    major_asset: str = "ETH",
) -> Tuple[List[str], str]:
    spot_meta = _extract_meta_payload(spot_meta_raw)
    perp_meta = _extract_meta_payload(perp_meta_raw)

    spot_bases = _spot_base_symbols(spot_meta)
    perp_bases = _perp_base_symbols(perp_meta)
    candidates = sorted(spot_bases & perp_bases)

    ctxs = _asset_contexts(spot_meta)
    ranked: List[AutoAssetCandidate] = []
    for symbol in candidates:
        ctx = ctxs.get(symbol, {})
        ranked.append(
            AutoAssetCandidate(
                symbol=symbol,
                spread=_spread_proxy(ctx),
                volume_24h=_volume_proxy(ctx),
            )
        )

    has_spread = any(item.spread is not None for item in ranked)
    reason = "spread_desc_volume_asc" if has_spread else "volume_asc"

    def sort_key(item: AutoAssetCandidate) -> Tuple[bool, float, float]:
        spread_missing = item.spread is None
        spread_value = item.spread or 0.0
        volume_value = item.volume_24h if item.volume_24h is not None else inf
        return (spread_missing, -spread_value, volume_value)

    ranked.sort(key=sort_key)
    limit = max(limit, 1)
    selected = [item.symbol for item in ranked[:limit]]

    major = major_asset.upper()
    if major in candidates and major not in selected:
        if len(selected) >= limit:
            selected = selected[: max(limit - 1, 0)]
        selected.append(major)
        reason = f"{reason};major={major}"

    return selected, reason


async def select_auto_assets(
    client: HyperliquidClient,
    *,
    limit: int = 15,
    major_asset: str = "ETH",
) -> List[str]:
    spot_meta = await client.fetch_spot_meta_and_asset_ctxs()
    perp_meta = await client.fetch_perp_meta()
    selected, reason = select_auto_assets_from_meta(
        spot_meta,
        perp_meta,
        limit=limit,
        major_asset=major_asset,
    )
    logger.info("[AUTO_ASSETS] selected=%s reason=%s", ",".join(selected), reason)
    return selected
