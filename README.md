# Hyperliquid Triangular Arbitrage Bot (Paper Trading)

This repository contains an asynchronous Python 3.11+ paper-trading bot for **triangular arbitrage** on **Hyperliquid spot markets**. It discovers tradable triangles, streams order books, simulates trades with realistic depth/fees, and records everything to a database. An offline analysis module evaluates performance and suggests tuning parameters.

> **Important:** This project is **paper trading only**. It never sends live orders. Use it to research and rehearse before building a real execution layer.

## Features
- Async architecture with `httpx` (REST) and `websockets` (order books).
- Configurable via YAML (`config/config.yaml`) plus environment variables loaded from `.env`.
- Supports mainnet and testnet Hyperliquid endpoints.
- Paper portfolio tracking with per-run IDs and DB persistence (SQLite by default, PostgreSQL optional).
- Triangular arbitrage scanner using live orderbook depth to estimate slippage and edge.
- Offline analysis to compute performance metrics and recommend parameter tweaks.
- Typer-based CLI to run the bot, init the DB, measure latency, and analyze past runs.
- GitHub Actions CI running pytest.

## Requirements
- Python 3.11+
- Access to the internet to reach Hyperliquid APIs (for live streaming). Offline tests use mocks.

## Quick start
1. Clone the repo and create a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip
   pip install -e .
   ```

2. Copy the example configuration and environment files:
   ```bash
   cp config/config.example.yaml config/config.yaml
   cp .env.example .env
   ```
   Adjust values as needed (network, DB, thresholds, filters).

3. Initialize the database:
   ```bash
   python -m src.cli init-db --config-path config/config.yaml
   ```

4. Run the paper bot (streams order books, scans triangles, simulates trades):
   ```bash
   python -m src.cli run-paper-bot --config-path config/config.yaml
   ```
   Stop with `Ctrl+C`. A new `run_id` is generated unless provided.

5. Analyze a run:
   ```bash
   python -m src.cli analyze-run --run-id <RUN_ID> --config-path config/config.yaml
   ```
   Reports are written to `analysis_output/` by default.

6. Measure API latency:
   ```bash
   python -m src.cli measure-latency --config-path config/config.yaml
   ```

7. Avviare la web dashboard (Next.js) per analizzare le run salvate:
   ```bash
   cd web-dashboard
   npm install
   npm run dev
   ```
   La dashboard legge `data/arb_bot.sqlite` e include API interne (`/api/runs`, `/api/runs/:runId`, `/api/logs`) pensate per il deploy su Vercel.

## Configuration
- `config/config.yaml` holds defaults. Environment variables (from `.env`) override file values.
- Example keys include network selection, quote asset, edge thresholds, position sizing, whitelists/blacklists, DB backend, and logging settings.
- See `config/config.example.yaml` and `.env.example` for templates.

## Next steps to go live
- Implement a real order execution layer using Hyperliquid authenticated endpoints and handle signatures.
- Add latency-sensitive routing and partial-fill management.
- Migrate from a free VPS to a low-latency host near Hyperliquid infra (e.g., central Europe) for production arbitrage.

## Project layout
- `src/config`: configuration loader with env overrides.
- `src/hyperliquid_client`: REST + WebSocket client.
- `src/arb`: market graph, orderbook cache, scanner, and paper trader.
- `src/db`: SQLAlchemy models and DB helpers.
- `src/analysis`: metrics, tuning, reporting.
- `src/cli.py`: Typer CLI entry point.
- `tests/`: unit tests using synthetic data.
- `web-dashboard/`: dashboard Next.js (deployabile su Vercel) che legge il database SQLite e mostra run, trade e log.
- `.github/workflows/ci.yml`: CI running pytest.

## Disclaimer
This code is for research and paper trading only. Use at your own risk.
