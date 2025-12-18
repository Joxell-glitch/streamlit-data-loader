from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from src.config.models import FeedHealthSettings


@dataclass
class BookHealth:
    ts: float = 0.0
    best_bid: float = 0.0
    best_ask: float = 0.0
    incomplete: bool = False
    crossed: bool = False

    def age_ms(self, now: Optional[float] = None) -> float:
        now_ts = now or time.time()
        if not self.ts:
            return float("inf")
        return max(0.0, (now_ts - self.ts) * 1000.0)


@dataclass
class AssetHealth:
    spot: BookHealth = field(default_factory=BookHealth)
    perp: BookHealth = field(default_factory=BookHealth)
    stale: bool = False
    out_of_sync: bool = False


class FeedHealthTracker:
    def __init__(self, settings: Optional[FeedHealthSettings] = None) -> None:
        self.settings = settings or FeedHealthSettings()
        self.ws_msgs_total = 0
        self.duplicate_events = 0
        self.heartbeat_only = 0
        self.book_incomplete = 0
        self.stale_book = 0
        self.crossed_book = 0
        self.out_of_sync = 0
        self._asset_health: Dict[str, AssetHealth] = {}
        self._dedup_cache: Dict[str, float] = {}

    def register_message(self, msg: Dict[str, Any]) -> bool:
        """Register a raw WebSocket message and return True if duplicate."""
        self.ws_msgs_total += 1
        self._cleanup_dedup_cache()
        key = self._dedup_key(msg)
        now = time.time()
        if key and key in self._dedup_cache and now - self._dedup_cache[key] <= self.settings.dedup_ttl_sec:
            self.duplicate_events += 1
            self._dedup_cache[key] = now
            return True
        if key:
            self._dedup_cache[key] = now
        return False

    def register_heartbeat(self, msg: Dict[str, Any]) -> None:
        """Track heartbeat/keepalive messages that do not update books."""
        if self._looks_like_heartbeat(msg):
            self.heartbeat_only += 1

    def on_book_update(
        self,
        asset: str,
        kind: str,
        best_bid: float,
        best_ask: float,
        ts: float,
        bids: Optional[Any] = None,
        asks: Optional[Any] = None,
    ) -> None:
        health = self._asset_health.setdefault(asset, AssetHealth())
        target = health.perp if kind == "perp" else health.spot
        target.ts = float(ts) if ts else time.time()
        target.best_bid = best_bid or 0.0
        target.best_ask = best_ask or 0.0
        target.incomplete = not (bids and asks and target.best_bid > 0 and target.best_ask > 0)
        target.crossed = target.best_bid >= target.best_ask and target.best_bid > 0 and target.best_ask > 0
        now = time.time()
        if target.incomplete:
            self.book_incomplete += 1
        if target.age_ms(now) > self.settings.stale_ms:
            health.stale = True
            self.stale_book += 1
        else:
            health.stale = False
        if target.crossed:
            self.crossed_book += 1
        self._update_out_of_sync(asset)

    def _update_out_of_sync(self, asset: str) -> None:
        health = self._asset_health.setdefault(asset, AssetHealth())
        spot_ts = health.spot.ts
        perp_ts = health.perp.ts
        if spot_ts and perp_ts:
            delta_ms = abs(spot_ts - perp_ts) * 1000.0
            health.out_of_sync = delta_ms > self.settings.out_of_sync_ms
            if health.out_of_sync:
                self.out_of_sync += 1
        else:
            health.out_of_sync = False

    def get_asset_health(self, asset: str) -> AssetHealth:
        return self._asset_health.setdefault(asset, AssetHealth())

    def build_asset_snapshot(self, asset: str) -> Dict[str, Any]:
        now = time.time()
        health = self.get_asset_health(asset)
        spot_age = health.spot.age_ms(now)
        perp_age = health.perp.age_ms(now)
        stale_now = spot_age > self.settings.stale_ms or perp_age > self.settings.stale_ms
        crossed = health.spot.crossed or health.perp.crossed
        return {
            "asset": asset,
            "spot_age_ms": spot_age,
            "perp_age_ms": perp_age,
            "spot_incomplete": health.spot.incomplete,
            "perp_incomplete": health.perp.incomplete,
            "stale": stale_now or health.stale,
            "crossed": crossed,
            "out_of_sync": health.out_of_sync,
            "spot_bid": health.spot.best_bid,
            "spot_ask": health.spot.best_ask,
            "perp_bid": health.perp.best_bid,
            "perp_ask": health.perp.best_ask,
            "ws_msgs_total": self.ws_msgs_total,
            "duplicate_events": self.duplicate_events,
            "heartbeat_only": self.heartbeat_only,
            "book_incomplete": self.book_incomplete,
            "stale_book": self.stale_book,
            "crossed_book": self.crossed_book,
            "out_of_sync_count": self.out_of_sync,
        }

    def _dedup_key(self, msg: Dict[str, Any]) -> Optional[str]:
        channel = msg.get("channel") or msg.get("type")
        payload = self._extract_payload(msg)
        coin = payload.get("coin") or payload.get("asset") or msg.get("coin") or msg.get("asset")
        ts = payload.get("ts") or payload.get("time") or msg.get("ts") or msg.get("time")
        seq = payload.get("seq") or msg.get("seq")
        if channel and coin and (seq is not None or ts is not None):
            return f"{channel}:{coin}:{seq or ts}"
        if channel and coin:
            return f"{channel}:{coin}:{hashlib.sha256(str(msg).encode()).hexdigest()}"
        try:
            return hashlib.sha256(json.dumps(msg, sort_keys=True).encode()).hexdigest()
        except Exception:
            return None

    def _cleanup_dedup_cache(self) -> None:
        now = time.time()
        ttl = self.settings.dedup_ttl_sec
        expired = [k for k, ts in self._dedup_cache.items() if now - ts > ttl]
        for key in expired:
            del self._dedup_cache[key]

    def _looks_like_heartbeat(self, msg: Dict[str, Any]) -> bool:
        channel = str(msg.get("channel") or msg.get("type") or "").lower()
        if channel in {"pong", "ping", "heartbeat"}:
            return True
        keys = set(msg.keys())
        return keys.issubset({"channel", "type", "time", "ts"})

    def _extract_payload(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        payload = msg.get("data") or msg.get("result") or msg.get("levels") or msg.get("payload") or {}
        return payload if isinstance(payload, dict) else {}

