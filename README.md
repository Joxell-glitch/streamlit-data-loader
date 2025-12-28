# Hyperliquid Triangular Arbitrage Bot

The system is **research-first** and **paper-only**. It is designed to measure real,
survivable edge under realistic microstructure constraints.

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
- Paper portfolio tracking with per-run IDs and DB persistence (SQLite by default).
- Synthetic Spot/Perp edge evaluation (paper-only).
- Typer-based CLI to run the bot, init DB, and analyze runs.
- GitHub Actions CI running pytest.

## Roadmap & Project Status

### Stato attuale RoadMap
- **A) Runtime Stability & Baseline** — COMPLETATA
- **B) Feed Integrity & Observability** — COMPLETATA (Decision Trace deterministico)
- **C) Strategy Logic Validation** — NON AVVIATA (Autoscan non ancora eseguito)
- **D) Dataset & Offline Analysis** — PARZIALE
- **E) Hardening & Risk Controls** — BLOCCATA (dipende da C)
- **F) Future Extensions** — BLOCCATA

### Snapshot di handoff (stato attuale)
- Fonte della verità: **VM**
- Branch `main` allineato alla VM
- Tutti i test pytest passano
- Decision Trace normalizzato (**READY / SKIP / HALT**)
- Kill-switch isolati dai test
- Autoscan **NON** ancora eseguito
- Nessuna ottimizzazione PnL avviata

## Handoff & Continuity Prompt
Questa README è la **fonte unica di contesto e continuità** del progetto.

Ogni nuova chat deve:
- leggere **integralmente** questo file
- continuare **senza fare assunzioni esterne**
- rispettare le Linee Guida Operative sottostanti

Questo prompt viene **sempre sovrascritto**, mai appeso.

## Linee Guida Operative

Da ora in poi:
- L’utente **NON scrive né modifica codice**
- L’assistente prepara **solo**:
  - Prompt per Codex (sempre in blocchi di codice)
  - Comandi per la VM (sempre in blocchi di codice, con output filtrato)

Regola operativa:
- **Codex = propone**
- **VM = fonte della verità**
- **GitHub = specchio della VM**

Metodo di lavoro:
- Micro-step (max 1–2 passi)
- Stop obbligatorio in attesa dell’output VM
- Vietato anticipare step futuri
- Approccio deterministico, niente trial-and-error
- Se serve visione completa → chiedere ZIP/file prima
- Spiegazioni brevi, chiare, zero ridondanza
- Nessuna scelta multipla: l’assistente guida e decide
- La RoadMap nel README va aggiornata periodicamente con le stesse diciture

## Requirements
- Python 3.8
- Accesso alle API Hyperliquid (offline test via mock)

## Environment & Paths
- Repo GitHub: https://github.com/Joxell-glitch/hyperliquid-triangular-arbitrage-bot
- VM path: `/home/ubuntu/hyperliquid-triangular-arbitrage-bot`
