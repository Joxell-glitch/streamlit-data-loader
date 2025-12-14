from __future__ import annotations

import asyncio
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from src.arb.triangular_scanner import Opportunity
from src.core.logging import get_logger

logger = get_logger(__name__)


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _load_json(path: str) -> Dict[str, List[Dict]]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to load JSON from %s: %s", path, exc)
        return {}


def _atomic_write_json(path: str, data: Dict[str, List[Dict]]) -> None:
    directory = os.path.dirname(path) or "."
    _ensure_dir(directory)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix="tmp_top_hour", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp_path, path)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to write JSON to %s: %s", path, exc)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


class ProfitRecorder:
    def __init__(self, data_dir: Optional[str] = None, top_n_per_hour: Optional[int] = None):
        self.data_dir = data_dir or os.getenv("DATA_DIR", "data")
        self.top_n_per_hour = top_n_per_hour or int(os.getenv("TOP_N_PER_HOUR", "10"))
        _ensure_dir(self.data_dir)
        self.profitable_path = os.path.join(self.data_dir, "profitable.jsonl")
        self.top_per_hour_path = os.path.join(self.data_dir, "top_per_hour.json")

    async def record_opportunity_async(self, opp: Opportunity) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.record_opportunity, opp)

    def record_opportunity(self, opp: Opportunity) -> None:
        try:
            ts_str, dt = self._format_timestamp(opp.timestamp)
            profit_absolute = opp.theoretical_final_amount - opp.initial_size
            payload = {
                "timestamp": ts_str,
                "triangle": {"id": opp.triangle_id, "assets": opp.assets},
                "initial_size": opp.initial_size,
                "theoretical_final_amount": opp.theoretical_final_amount,
                "profit_absolute": profit_absolute,
                "profit_percent": opp.theoretical_edge * 100,
                "slippage": opp.slippage,
            }
            self._append_jsonl(payload)
            self._update_hourly_top(dt, payload, profit_absolute)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to persist profitable opportunity: %s", exc)

    def _format_timestamp(self, ts: float) -> tuple[str, datetime]:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC"), dt

    def _append_jsonl(self, payload: Dict) -> None:
        try:
            with open(self.profitable_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload) + "\n")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to append profitable opportunity: %s", exc)

    def _update_hourly_top(self, dt: datetime, payload: Dict, profit_absolute: float) -> None:
        hour_key = dt.strftime("%Y-%m-%d %H")
        top_data = _load_json(self.top_per_hour_path)
        entries = top_data.get(hour_key, [])
        entries.append(
            {
                "hour": hour_key,
                "timestamp": payload["timestamp"],
                "triangle": payload["triangle"],
                "profit_absolute": profit_absolute,
                "profit_percent": payload["profit_percent"],
                "initial_size": payload["initial_size"],
                "theoretical_final_amount": payload["theoretical_final_amount"],
                "slippage": payload["slippage"],
            }
        )
        entries.sort(key=lambda e: e.get("profit_absolute", 0.0), reverse=True)
        top_data[hour_key] = entries[: self.top_n_per_hour]
        _atomic_write_json(self.top_per_hour_path, top_data)


def load_recent_profitable(limit: int, data_dir: Optional[str] = None) -> List[Dict]:
    path = os.path.join(data_dir or os.getenv("DATA_DIR", "data"), "profitable.jsonl")
    if not os.path.exists(path):
        return []

    records: List[Dict] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:  # pragma: no cover - defensive
                    continue
        return records[-limit:][::-1]
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to load profitable records: %s", exc)
        return []


def load_top_per_hour(hours: int, data_dir: Optional[str] = None) -> List[Dict]:
    path = os.path.join(data_dir or os.getenv("DATA_DIR", "data"), "top_per_hour.json")
    top_data = _load_json(path)
    if not top_data:
        return []

    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    earliest = now - timedelta(hours=hours - 1)
    results: List[Dict] = []

    for hour_key, entries in top_data.items():
        try:
            hour_dt = datetime.strptime(hour_key, "%Y-%m-%d %H").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if hour_dt < earliest:
            continue
        results.append({"hour": hour_key, "records": entries})

    results.sort(key=lambda e: e.get("hour"), reverse=True)
    return results
