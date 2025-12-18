from __future__ import annotations

import argparse
import sqlite3
import time
from collections import defaultdict
from typing import Dict

from src.config.loader import load_config
from src.core.logging import setup_logging


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return cursor.fetchone() is not None


def analyze(path: str, since_minutes: int):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        if not _table_exists(conn, "decision_outcomes"):
            raise RuntimeError("decision_outcomes table not found. Did you enable validation?")

        since_ms = int((time.time() - since_minutes * 60) * 1000)
        rows = conn.execute(
            "SELECT outcome, reason, COUNT(*) as cnt FROM decision_outcomes "
            "WHERE ts_ms >= ? GROUP BY outcome, reason",
            (since_ms,),
        ).fetchall()
        stats_row = conn.execute(
            "SELECT MIN(ts_ms) AS min_ts, MAX(ts_ms) AS max_ts, COUNT(*) as total "
            "FROM decision_outcomes"
        ).fetchone()
    finally:
        conn.close()

    totals: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        totals[row["outcome"]][row["reason"]] = row["cnt"]
    return totals, stats_row


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze validation outcomes")
    parser.add_argument("--config", default="config/config.yaml", help="Path to config YAML file")
    parser.add_argument("--since-minutes", type=int, default=60, help="Lookback window in minutes")
    args = parser.parse_args()

    settings = load_config(args.config)
    setup_logging(settings.logging)
    try:
        totals, stats_row = analyze(settings.database.sqlite_path, args.since_minutes)
    except Exception as exc:  # pragma: no cover - CLI convenience
        print(f"[ANALYZE] error: {exc}")
        return

    print(
        f"[ANALYZE] db_path={settings.database.sqlite_path} min_ts_ms={stats_row['min_ts']} "
        f"max_ts_ms={stats_row['max_ts']} total_rows={stats_row['total']}"
    )
    overall = sum(sum(reason_counts.values()) for reason_counts in totals.values())
    print(f"[ANALYZE] rows={overall} window_minutes={args.since_minutes}")
    for outcome, reason_counts in totals.items():
        outcome_total = sum(reason_counts.values())
        pct_outcome = (outcome_total / overall * 100.0) if overall else 0.0
        print(f"  outcome={outcome} count={outcome_total} pct={pct_outcome:.2f}%")
        for reason, count in reason_counts.items():
            pct_reason = (count / overall * 100.0) if overall else 0.0
            print(f"    reason={reason} count={count} pct={pct_reason:.2f}%")


if __name__ == "__main__":
    main()
