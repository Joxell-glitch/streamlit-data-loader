# Hyperliquid Triangular Arbitrage Bot

The system is **research-first** and **paper-only**.
It is designed to measure **real, survivable edge** under realistic market microstructure constraints.

## Net-Profit Focus (Definition)

- **Edge:** raw price discrepancy before costs
- **Fees:** maker/taker fees per leg (config + tier fallback)
- **Fill probability:** expected completion rate for each leg
- **Slippage:** depth- and latency-adjusted execution impact
- **Frequency:** opportunities per day per asset/path
- **KPI:**  
  **daily net** = (edge − fees − slippage) × fill probability × frequency

## How Trading Candidates Are Selected

- Rank assets by **net edge × expected fill probability × frequency**
- Penalize for slippage and latency
- Select top-N candidates for paper evaluation
- Periodically re-run selection via **Auto-Scan** to adapt to new listings and edge decay

## Features

- Async architecture using `httpx` (REST) and `websockets` (order books)
- YAML-based configuration (`config/config.yaml`) + environment variables
- Hyperliquid mainnet and testnet support
- Paper portfolio tracking with per-run IDs
- SQLite persistence (default)
- Synthetic Spot/Perp edge evaluation (paper-only)
- Typer-based CLI
- GitHub Actions CI running pytest

## Roadmap & Project Status

### Current Roadmap Status

- **A) Runtime Stability & Baseline** — COMPLETED
- **B) Feed Integrity & Observability** — COMPLETED (Deterministic Decision Trace)
- **C) Strategy Logic Validation** — NOT STARTED (Autoscan not executed)
- **D) Dataset & Offline Analysis** — PARTIAL
- **E) Hardening & Risk Controls** — BLOCKED (depends on C)
- **F) Future Extensions** — BLOCKED

### Handoff Snapshot (Current State)

- Source of truth: **VM**
- `main` branch aligned with VM
- All pytest tests passing
- Decision Trace normalized (**READY / SKIP / HALT**)
- Kill-switch logic isolated from tests
- Autoscan **NOT** executed
- No PnL optimization performed

## Continuity & Execution Contract

This README is the **canonical high-level context document**.

Cursor must:
- Read this file entirely before acting
- Treat it as a **binding contract**
- Continue work without external assumptions

Operational continuity is enforced through:
- `README.md` — high-level project state
- `PROTOCOL.md` — execution rules and constraints
- `ROADMAP.md` — active phase and micro-step
- `DECISIONS.md` — decisions taken and explicitly avoided
- `SESSION_*.json` — session-level technical summaries

## Operational Guidelines (Cursor)

- Cursor operates directly on the **VM**
- Cursor has full read/write access to the codebase
- Cursor executes changes autonomously

Principles:
- Prefer **deterministic solutions**
- Avoid exploratory or speculative changes unless explicitly requested
- If information is insufficient, **stop and ask**
- Detect and report VM/GitHub divergence; do not silently auto-fix

Execution model:
- Cursor = executor and analyst
- Human = decision authority
- GitHub = persistence layer (may lag VM)

## Requirements

- Python 3.8
- Network access to Hyperliquid APIs (offline tests via mocks)

## Environment & Paths

- GitHub repository: https://github.com/Joxell-glitch/hyperliquid-triangular-arbitrage-bot
- VM path: `/home/ubuntu/hyperliquid-triangular-arbitrage-bot`
