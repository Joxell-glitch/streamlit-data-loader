# Hyperliquid Triangular Arbitrage Bot (Paper Trading)

This repository contains an asynchronous Python 3.8+ paper-trading bot for **triangular arbitrage** on **Hyperliquid spot markets**. It discovers tradable triangles, streams order books, simulates trades with realistic depth/fees, and records everything to a database. An offline analysis module evaluates performance and suggests tuning parameters.

> **Important:** This project is **paper trading only**. It never sends live orders. Use it to research and rehearse before building a real execution layer.

## Project Evolution & Objective

The original concept targeted classic spot-only triangular arbitrage on Hyperliquid. During development, it became clear that most spot markets are quoted only against stablecoins and that cross pairs between non-stable assets do not exist. This makes traditional spot-only triangles structurally impossible on Hyperliquid.

The project therefore pivoted to **synthetic triangular arbitrage**, combining:
- **Spot / Perpetual**
- **Perpetual / Perpetual**

The system is **research-first** and **paper-only**. It is designed to measure realistic edge after **maker/taker fees**, latency, slippage, and market microstructure constraints. The current objective is to build a research-grade paper trading system that continuously scans the entire Hyperliquid universe to detect inefficiencies, quantify fee-adjusted edge, evaluate fill probability, and adapt to market changes without executing live orders.

## Session Snapshot (Architecture & Direction)
- Spot/Spot arbitrage is structurally irrelevant on Hyperliquid and is excluded from scope.
- Synthetic arbitrage targets Spot/Perp as the primary focus, with Perp/Perp as a secondary comparative baseline.
- Current architecture lacks a synthetic triangle execution model and requires per-leg market typing for cross-market triangles.
- Triangular arbitrage is a research baseline, not the only edge class.
- The architecture must remain extensible to non-triangular edges (lead–lag, basis, liquidation-driven).

### PnL Realism & Edge Definition
- **Fees:** use effective maker/taker fees (config-driven with tier fallback) and record the fee rates used per run.
- **Net edge:** compute net PnL after fees, not just gross.
- **Frequency:** track opportunity frequency per asset/path.
- **Fill probability:** estimate fill probability for maker-maker (queue/latency proxy) and for taker scenarios.
- **Slippage:** depth-aware slippage modeling; high-frequency micro edges can still be viable if slippage is bounded—focus on total daily net.

### How we decide what to trade
- Rank candidates by **net edge × expected fill probability × frequency**, penalized by slippage/latency.
- Select top-N assets/triangles for paper trading.
- Re-run selection periodically via **Auto-Scan** to adapt to new listings and edge decay.

## Features
- Async architecture with `httpx` (REST) and `websockets` (order books).
- Configurable via YAML (`config/config.yaml`) plus environment variables loaded from `.env`.
- Supports mainnet and testnet Hyperliquid endpoints.
- Paper portfolio tracking with per-run IDs and DB persistence (SQLite by default, PostgreSQL optional).
- Triangular arbitrage scanner using live orderbook depth to estimate slippage and edge.
- Offline analysis to compute performance metrics and recommend parameter tweaks.
- Typer-based CLI to run the bot, init the DB, measure latency, and analyze past runs.
- GitHub Actions CI running pytest.

## Roadmap & Project Status

### Session Log / Snapshot (2025-12-27)
- Maker-mode fee policy locked to 0.0 on Hyperliquid with guardrails blocking non-zero maker fees in paper mode.
- `config/config.yaml` treated as local-only; safe-run workflow temporarily forces maker fees to 0.0 and auto-restores on exit.
- Canonical spot-perp paper entrypoint standardized on `python -m src.cli.run_spot_perp_paper`.
- Direction remains research-first/paper-only with next focus on data capture and edge distribution analysis.

### A) Runtime Stability & Baseline
Establish a stable, long-running paper-trading loop for synthetic triangles.
- [TODO] Spot/Perp paper trading loop and persistence (incomplete baseline)
- [DONE] Per-run IDs, SQLite logging, and heartbeats
- [TODO] Synthetic Triangle model (Spot/Perp)
- [TODO] Perp/Perp synthetic baseline (secondary/comparative)
- [DONE] Canonical entrypoint for Spot/Perp paper runs via `python -m src.cli.run_spot_perp_paper`
- [DONE] Spot/Spot excluded as structurally irrelevant on Hyperliquid

### B) Feed Integrity & Observability
Ensure data quality and traceability across REST/WS feeds.
- [DONE] WebSocket reconnects with exponential backoff
- [DONE] API latency measurement tooling
- [BLOCKED] Unified feed health dashboard for cross-market streams (blocked by A)

### C) Strategy Logic Validation (NO PnL optimization)
Validate correctness of pricing logic before optimization.
- [DONE] Depth-aware edge estimation for synthetic Spot/Perp
- [BLOCKED] Synthetic triangle validation suite (Spot/Perp and Perp/Perp) (blocked by A)
- [BLOCKED] Real-fee parity across synthetic models (maker=0.0 per HL policy; taker via config/tier fallback) (blocked by A)

### D) Dataset & Offline Analysis
Build research datasets for microstructure and fill-probability studies.
- [DONE] Run-level storage of opportunities in SQLite
- [TODO] Run 15–30 min capture and export/analysis of spread_gross / pnl_net_est distributions and exceedance frequency
- [TODO] Extend spot/perp paper data collection to multi-asset (BTC+ETH) after baseline run
- [BLOCKED] Synthetic-edge datasets for slippage/latency attribution (blocked by synthetic execution model)
- [BLOCKED] Research metrics for synthetic edges: net edge distribution, hit-rate, dt_next_ms/latency buckets, fill proxy metrics (blocked by synthetic execution model)
- [BLOCKED] Offline fill-probability and microstructure labeling for synthetic edges (blocked by synthetic execution model)

### E) Hardening & Risk Controls
Add guardrails appropriate for a future live system without enabling execution.
- [BLOCKED] Universe Auto-Scan (new listings + edge decay + dynamic activation) (dependent on validated synthetic models)
- [DONE] Paper trading phase explicitly before any live execution
- [DONE] Maker-mode fee guardrail enforces maker_fee_* = 0.0 in paper mode
- [DONE] Safe-run workflow temporarily sets maker fees to 0.0 with automatic restore on exit
- [BLOCKED] Separate live execution layer as its own service (pending validation/risk controls)
- [BLOCKED] Explicit separation between research metrics and any live execution layer (dependent on validated synthetic models)

### F) Future Extensions (post-validation)
Post-research enhancements once the synthetic model is validated.
- [TODO] Dashboard on Vercel for monitoring Paper now and Live later (post-validation)
- [BLOCKED] Live trading pending strategy validation, risk controls, and regulatory review
- [TODO] Extend to non-triangular edge classes (lead–lag, basis, liquidation-driven)

## Requirements
- Python 3.8
- Access to the internet to reach Hyperliquid APIs (for live streaming). Offline tests use mocks.

## Install (runtime) – Python 3.8
`requirements-lock.txt` contiene **solo le dipendenze runtime** del bot (niente tool di sviluppo) ed è pensato per Python 3.8. Usa sempre questo file sugli ambienti che devono restare accesi a lungo.

```bash
rm -rf .venv
python3.8 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements-lock.txt
python -m pip check
```

- Il database SQLite di default è `data/arb_bot.sqlite` (viene creato automaticamente). Puoi leggerlo con un qualsiasi client SQLite o `python -m sqlite3 data/arb_bot.sqlite ".tables"`.
- Il file di configurazione di riferimento è `config/config.yaml` (puoi copiarlo da `config/config.example.yaml`).

### Data Retention (FIFO) – SQLite (procedura MANUALE)
- **Perché serve:** controllare la dimensione del DB, analizzare il regime recente, evitare mixing di regimi troppo diversi nello storico.
- **Quando usarla:** DB che cresce nel tempo, più coin/asset tracciati, run lunghi.
- **Backup obbligatorio prima del purge** (non saltare questo passaggio):
  ```bash
  cp data/arb_bot.sqlite "data/arb_bot.sqlite.bak.$(date +%Y%m%d-%H%M%S)"
  ```
- **Purge “keep last 24h” + VACUUM** (manuale e controllato):
  ```bash
  python -m sqlite3 data/arb_bot.sqlite \
    "DELETE FROM spot_perp_opportunities WHERE timestamp < strftime('%s','now','-24 hours');"
  python -m sqlite3 data/arb_bot.sqlite "VACUUM;"
  ```
- **Nota importante:** non attivare purge automatico di default; è una procedura opzionale e controllata.

### Dipendenze di sviluppo (opzionali)
Se vuoi eseguire lint, type-check o test, installa anche i tool DEV (compatibili con Python 3.8) dopo il runtime:
```bash
python -m pip install -r requirements-dev.txt
```

### Rigenerare il lock (solo quando serve)
Usa sempre Python 3.8 e genera il lock con `pip-compile` per ottenere solo versioni presenti su PyPI:
```bash
python -m pip install --upgrade pip setuptools wheel pip-tools
python -m piptools compile \
  --resolver=backtracking \
  --python-version 3.8 \
  --output-file requirements-lock.txt \
  requirements.in
python -m pip check
```
Commita il nuovo lock solo se l'applicazione continua a funzionare, `pip check` resta pulito e i test passano.

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
   La dashboard chiama sempre il backend FastAPI configurato in `NEXT_PUBLIC_BACKEND_URL` (nessun accesso diretto a file o SQLite) ed è pensata per monitorare prima il paper trading e in futuro il live.

## Fee configuration (important)
- `config/config.yaml` is intentionally gitignored (local-only).
- `maker_fee_spot` and `maker_fee_perp` **must** be `0.0` when using maker mode (`fee_mode`, `spot_fee_mode`, or `perp_fee_mode` set to `maker`).
- Taker fees are tier-dependent and must be configured by the user.

## Bootstrap (one-liner)
`rm -rf .venv && python3.8 -m venv .venv && source .venv/bin/activate && python -m pip install --upgrade pip setuptools wheel && python -m pip install -r requirements-lock.txt && python -m pip check && python -m src.cli.run_spot_perp_paper --assets BTC`

## Run paper (BTC,ETH,SOL)
Streaming spot/perp data and persisting paper opportunities (no live orders):

```bash
python -m src.cli.run_spot_perp_paper --config config/config.yaml --assets BTC,ETH,SOL
```

- Log metrics/heartbeats every few seconds, reconnects with exponential backoff, and persist opportunities to `data/arb_bot.sqlite`.
- Health/status only (non-trading):
  ```bash
  python -m src.cli.run_spot_perp_paper --config config/config.yaml --assets BTC,ETH,SOL --status-only
  ```
  Useful to verify config + DB path and how many `spot_perp_opportunities` rows are present without opening websockets.

## Configuration
- `config/config.yaml` holds defaults. Environment variables (from `.env`) override file values.
- Example keys include network selection, quote asset, edge thresholds, position sizing, whitelists/blacklists, DB backend, and logging settings.
- For spot/perp paper runs you can remap a logical asset to a different spot pair via `trading.spot_pair_overrides` (e.g., `BTC: "UBTC/USDC"`).
- See `config/config.example.yaml` and `.env.example` for templates.

## Troubleshooting (Python 3.8)
- **DB non creato:** assicurati che `database.backend` sia `sqlite` e che il percorso `data/arb_bot.sqlite` sia scrivibile. Il comando `python -m src.cli.run_spot_perp_paper --config config/config.yaml --status-only` mostra percorso, dimensione file e numero di `spot_perp_opportunities`.
- **Disconnessioni WebSocket:** il client riconnette con backoff esponenziale e logga il motivo. Se vedi troppi `ws_reconnects`, controlla la connettività della VM e il firewall.
- **Metriche troppo rare/dense:** cambia l'intervallo dei log periodici impostando la variabile `SPOT_PERP_METRICS_INTERVAL` (es. `export SPOT_PERP_METRICS_INTERVAL=15`).
- **Problemi TLS o certificati su Python 3.8:** aggiorna `certifi` dentro l'ambiente virtuale (`python -m pip install --upgrade certifi`) e riprova.

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
