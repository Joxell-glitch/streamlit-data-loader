# Hyperliquid Triangular Arbitrage Bot (Paper Trading)

This repository contains an asynchronous Python 3.8+ paper-trading bot for **triangular arbitrage** on **Hyperliquid spot markets**. It discovers tradable triangles, streams order books, simulates trades with realistic depth/fees, and records everything to a database. An offline analysis module evaluates performance and suggests tuning parameters.

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
- Python 3.8
- Access to the internet to reach Hyperliquid APIs (for live streaming). Offline tests use mocks.

## Installazione riproducibile (Python 3.8)
I lock sono conservati in `requirements-lock.txt`. Installa sempre da lì, non dalle dipendenze dirette.

### Setup pulito
```bash
rm -rf .venv
python3.8 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
```

### Install dal lock
```bash
python -m pip install -r requirements-lock.txt
python -m pip check
```

### Rigenerare il lock (solo quando serve)
Usa un ambiente funzionante con Python 3.8, tutti i pacchetti installati e nessun errore `pip check`:
```bash
python -m pip install -r requirements.in
python -m pip check
python -m pip freeze --all > requirements-lock.txt
```
Commita il nuovo lock solo se l'applicazione continua a funzionare e `pip check` resta pulito.

### Rollback se esplode tutto
```bash
git checkout -- requirements-lock.txt requirements.in README.md
rm -rf .venv
python3.8 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
python -m pip check
```

### Comandi principali
- Inizializza il DB: `python -m src.cli init-db --config-path config/config.yaml`
- Avvia il paper bot: `python -m src.cli.run_paper_bot --config-path config/config.yaml`
- Analizza una run: `python -m src.cli analyze-run --run-id <RUN_ID> --config-path config/config.yaml`
- Misura la latenza API: `python -m src.cli measure-latency --config-path config/config.yaml`

## Quick start
1. Clone the repo e crea un ambiente virtuale (Python 3.8):
   ```bash
   python3.8 -m venv .venv
   source .venv/bin/activate
   python -m pip install --upgrade pip setuptools wheel
   python -m pip install -r requirements-lock.txt
   python -m pip check
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
   python -m src.cli.run_paper_bot --config-path config/config.yaml
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

7. Avviare la web dashboard (Next.js) per analizzare le run salvate tramite il backend FastAPI:
   ```bash
   cd web-dashboard
   npm install
   NEXT_PUBLIC_BACKEND_URL=http://localhost:8000 npm run dev
   ```
   La dashboard chiama sempre il backend FastAPI configurato in `NEXT_PUBLIC_BACKEND_URL` (nessun accesso diretto a file o SQLite).

## Bootstrap (one-liner)
`rm -rf .venv && python3.8 -m venv .venv && source .venv/bin/activate && python -m pip install --upgrade pip setuptools wheel && python -m pip install -r requirements-lock.txt && python -m pip check && python -m src.cli.run_spot_perp_paper --assets BTC`

## Configuration
- `config/config.yaml` holds defaults. Environment variables (from `.env`) override file values.
- Example keys include network selection, quote asset, edge thresholds, position sizing, whitelists/blacklists, DB backend, and logging settings.
- See `config/config.example.yaml` and `.env.example` for templates.

## Next steps to go live
- Implement a real order execution layer using Hyperliquid authenticated endpoints and handle signatures.
- Add latency-sensitive routing and partial-fill management.
- Migrate from a free VPS to a low-latency host near Hyperliquid infra (e.g., central Europe) for production arbitrage.

## Come far funzionare la dashboard su Vercel con il backend sulla VM
### Sul server (VM)
1. Clonare la repo e creare l'ambiente Python:
   ```bash
   git clone <REPO_URL>
   cd hyperliquid-triangular-arbitrage-bot
   python3.8 -m venv .venv
   source .venv/bin/activate
   python -m pip install --upgrade pip setuptools wheel
   python -m pip install -r requirements-lock.txt
   ```
2. Creare il file `.env` (puoi partire da `.env.example`):
   ```bash
   cp .env.example .env
   ```
   Imposta almeno:
   ```bash
   DB_PATH=data/arb_bot.sqlite
   ALLOWED_ORIGINS=https://<DOMAIN_VERCEL>  # usa * solo per test veloci
   ```
3. Avviare il backend FastAPI esponendolo sulla rete pubblica della VM:
   ```bash
   uvicorn api.main:app --host 0.0.0.0 --port 8000
   ```
4. Per tenerlo in esecuzione con tmux:
   ```bash
   tmux new -s hyperliquid-api
   uvicorn api.main:app --host 0.0.0.0 --port 8000
   # premi Ctrl+B poi D per fare detach
   ```

### Su Vercel (dashboard)
1. Imposta il root directory a `web-dashboard`.
2. Framework preset: **Next.js**.
3. Build command: `npm run build`.
4. Output directory: `.next`.
5. Variabili d'ambiente (Production):
   - `NEXT_PUBLIC_BACKEND_URL = http://<IP-PUBBLICO-DELLA-VM>:8000`
6. Esegui il deploy e testa la dashboard. Se vedi errori CORS, verifica il valore di `ALLOWED_ORIGINS` nel `.env` del backend.

## Project layout
- `src/config`: configuration loader with env overrides.
- `src/hyperliquid_client`: REST + WebSocket client.
- `src/arb`: market graph, orderbook cache, scanner, and paper trader.
- `src/db`: SQLAlchemy models and DB helpers.
- `src/analysis`: metrics, tuning, reporting.
- `src/cli.py`: Typer CLI entry point.
- `tests/`: unit tests using synthetic data.
- `web-dashboard/`: dashboard Next.js (deployabile su Vercel) che consuma il backend FastAPI e mostra run, trade e log.
- `.github/workflows/ci.yml`: CI running pytest.

## Disclaimer
This code is for research and paper trading only. Use at your own risk.
