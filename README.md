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

### Net-Profit Focus (Definition)
- **Edge:** raw price discrepancy before costs.
- **Fees:** maker/taker fees per leg (config + tier fallback).
- **Fill probability:** expected completion rate for each leg.
- **Slippage:** depth- and latency-adjusted execution impact.
- **Frequency:** opportunities per day for each triangle/path.
- **KPI:** **daily net** = (edge − fees − slippage) × fill probability × frequency.

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
- [DONE] Validazione statistica edge Spot–Perp (percentile-based)
- [DONE] Execution-like stress test con haircut deterministico
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
- [BLOCKED] Live execution (pending strategy validation and risk controls)
- [TODO] Kill-switch automatici (risk guardrails pre-live)
- [TODO] Position sizing dinamico (risk-aware sizing rules)
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

## Environment & Paths
- GitHub repo: https://github.com/<ORG>/hyperliquid-triangular-arbitrage-bot
- VM path: `/workspace/hyperliquid-triangular-arbitrage-bot`

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

- Il database SQLite di default è `data/arb_bot.sqlite` (viene creato automaticamente). Puoi leggerlo con un qualsiasi client SQLite o `sqlite3 data/arb_bot.sqlite ".tables"`.
- Il file di configurazione di riferimento è `config/config.yaml` (puoi copiarlo da `config/config.example.yaml`).

### Data Retention (FIFO) – SQLite (procedura MANUALE)
- **Perché serve:** controllare la dimensione del DB, analizzare il regime recente, evitare mixing di regimi troppo diversi nello storico.
- **Quando usarla:** DB che cresce nel tempo, più coin/asset tracciati, run lunghi.
- **Backup obbligatorio prima del purge** (non saltare questo passaggio):
  ```bash
  mkdir -p data/backups
  cp -a data/arb_bot.sqlite "data/backups/arb_bot.sqlite.$(date +%Y%m%d_%H%M%S).bak"
  ```
- **Purge “keep last 24h” + VACUUM** (manuale e controllato):
  ```bash
  python - <<'PY'
  import sqlite3
  import time

  cutoff = time.time() - 24 * 3600
  db_path = "data/arb_bot.sqlite"

  with sqlite3.connect(db_path) as conn:
      cursor = conn.cursor()
      cursor.execute("SELECT COUNT(*) FROM spot_perp_opportunities;")
      rows_before = cursor.fetchone()[0]
      cursor.execute(
          "DELETE FROM spot_perp_opportunities WHERE timestamp < ?;",
          (cutoff,),
      )
      rows_deleted = cursor.rowcount
      conn.commit()
      cursor.execute("VACUUM;")
      cursor.execute("SELECT COUNT(*) FROM spot_perp_opportunities;")
      rows_after = cursor.fetchone()[0]

  print(f"rows_before={rows_before}")
  print(f"rows_deleted={rows_deleted}")
  print(f"rows_after={rows_after}")
  PY
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

## End-of-Session Snapshot (Local)
- `pytest -q` → **36 passed**
- Past issue (experimental branch): `_load_liquidity_p10` raised `AttributeError: __enter__` in a local experiment; not reproducible on main.

## End-of-Session Handoff Template
- Date:
- Branch:
- Summary:
- Open items:
- Commands run:
  - `<command>` → `<result>`
- Results:
  - Tests:
  - Notes:

## Disclaimer
This code is for research and paper trading only. Use at your own risk.

### Session Snapshot (End of Session)
- Validazione edge Spot–Perp su Hyperliquid tramite paper engine completata.
- Stress test execution-like introdotto con haircut deterministico.
- Risultato chiave: Haircut 0.50% sostenibile (PnL/DD ~4 su BTC ed ETH); Haircut 0.80% non sostenibile (PnL negativo, DD elevato).
- Decisione: 0.50% adottato come baseline conservativa per paper-realistica.
- Confermato approccio percentile-driven (p90/p99 > winrate).

---

# 🔍 Strategic Scope, Edge Prioritization & Research Context

> This section records explicit design decisions, validated findings, and research priorities that emerged from real paper runs and system-level tests.
> It exists to prevent conceptual drift and repeated exploratory work when resuming development or starting a new chat/session.

## ✅ Validated Runtime Baseline (Empirical)

Empirically validated from live paper runs:

- **Spot/Perp paper loop runs stable** (no crash in steady execution)
- **SQLite persistence is active and coherent** (`data/arb_bot.sqlite`)
- Opportunity counts can reach **tens of thousands** (feeds alive + scanner active + sampling OK)
- Run lifecycle is now trackable via DB metadata:
  - `run_id`
  - start/end timestamps
  - config snapshot

**Conclusion:** runtime is a valid **research baseline**. Next work focuses on **edge quality**, not stability.

## ✅ Scope decision: which combinations matter

### ❌ Spot / Spot — explicitly out of scope (Hyperliquid-specific)

Spot/Spot arbitrage is intentionally excluded:

- Spot markets are almost exclusively **asset / USDC**
- No meaningful **cross-asset spot** pairs (BTC/ETH, ETH/SOL, etc.)
- Therefore **pure spot triangles do not exist** on HL

**Conclusion:** Spot/Spot adds noise and complexity without producing edge → excluded by design.

### ⚠️ Perp / Perp — secondary, comparative baseline only

Perp/Perp relationships exist and can be useful for research:

- basis / funding propagation studies
- measuring **inter-perp synchronization speed**
- efficiency benchmarking

But:

- markets are strongly arbitraged
- edges are small and short-lived
- live survivability is questionable without very low latency and aggressive execution

**Conclusion:** useful as a **research baseline**, not the primary profit engine.

### ✅ Spot / Perp — core focus (economic + microstructure)

Spot/Perp is the core axis of the project:

- different participant flows
- different reaction latencies
- dislocations often driven by:
  - funding expectations (dynamic)
  - spot-driven flows
  - liquidation cascades

Edges here are typically larger, more persistent, and less crowded than pure perp/perp micro-arbs.

**Conclusion:** Spot/Perp = **PRIMARY PRIORITY**.

## 🔄 Adaptive Edge Discovery (Auto-scan philosophy)

Edges are not static. The system is designed to:

- discover new opportunity structures (where none were detected before)
- detect when a previously valid structure **degrades** or **dies**
- measure **persistence**, not just frequency
- abandon dead structures early to avoid false “paper edge”

The scanner is a **research instrument**, not a blind executor.

## 🔬 Research directions (ordered by empirical value)

1) Lead–Lag inter-market (non-triangular)  
2) Dynamic basis / funding dislocations (changes, not static carry)  
3) Orderbook microstructure (queue, depth, resilience)  
4) Liquidation-driven moves (clusters/cascades)  
5) Cross-asset correlation breaks (spread mean-reversion)

Explicitly deprioritized:

- Spot/Spot
- static funding “carry”
- pure Perp/Perp triangles on majors
- classic cross-exchange latency arb (too crowded)


---

## 📎 Mini Appendix — Empirical Test Summary (Research Memory)

This section records **validated empirical findings** from early paper-trading runs.
Its purpose is to prevent repeated experimentation when resuming development.

### Spot / Perp Baseline Tests
- Market: Hyperliquid (paper trading)
- Assets tested: BTC, ETH
- Mode: execution-like simulation (deterministic haircut)

### Execution Haircut Stress Test
- Haircut **0.50%**
  - Result: sustainable
  - PnL / Max DD ≈ **4**
  - Stable across BTC and ETH
- Haircut **0.80%**
  - Result: **not sustainable**
  - Negative PnL
  - Excessive drawdown

### Key Decisions
- **0.50% haircut adopted** as conservative paper-realistic baseline
- Focus shifted from win-rate to **tail robustness**
- Percentile-driven evaluation (**p90 / p99**) preferred over averages



## Session Log / Snapshot (End of Session – 2025-12-28)

- Introduced a paper-only Synthetic Execution Layer for Spot/Perp, producing atomic synthetic trades.
- Validated Spot/Perp edge on BTC with positive, stable net PnL and no negative tail.
- Implemented persistent dataset for synthetic trades (SQLite, append-only) to enable offline analysis.
- Confirmed absence of overcounting and duplicate trade states (1 trade = 1 timestamp).
- ETH Spot/Perp observed as weak/quantized; BTC confirmed as primary research focus.

### RoadMap – Consolidated Status

#### A) Runtime Stability & Baseline
- [DONE] Spot/Perp paper trading loop and persistence
- [DONE] Synthetic Spot/Perp execution model (paper-only, atomic trades)

#### B) Feed Integrity & Observability
- [DONE] Feed health and shutdown-safe async lifecycle

#### C) Strategy Logic Validation
- [DONE] Spot/Perp validation on BTC (positive distribution, no negative tail)
- [TODO] Extend validation to additional assets only after new edge discovery

#### D) Dataset & Offline Analysis
- [DONE] Persistent dataset for synthetic Spot/Perp trades (SQLite)
- [DONE] Offline analysis of distribution, frequency, and tail behavior

#### E) Hardening & Risk Controls
- [DONE] Guardrails against duplicate trade states and overcounting
- [BLOCKED] Live execution (explicitly out of scope until further validation)
