# Hyperliquid Paper Trading Dashboard

Dashboard Next.js per analizzare le run di paper trading del bot di arbitraggio triangolare. Include overview delle run, dettaglio con equity curve e PnL, tabella dei trade con le tre gambe del triangolo e viewer dei log.

## Requisiti
- Node.js 18+
- Database SQLite già popolato in `../data/arb_bot.sqlite`

## Avvio locale
```bash
cd web-dashboard
npm install
npm run dev
```
Lancia il server su `http://localhost:3000`. Assicurati che il file `data/arb_bot.sqlite` esista nella root del repository o specifica un percorso alternativo via variabile d'ambiente:

```bash
DATABASE_PATH=/path/to/arb_bot.sqlite npm run dev
```

## Deploy su Vercel
- Seleziona la cartella `web-dashboard` come root del progetto.
- Usa la build command predefinita (`npm run build`).
- Imposta la variabile d'ambiente `DATABASE_PATH` se il database è ospitato altrove o montato come asset di sola lettura.
- Opzionalmente imposta `LOG_FILE_PATH` per puntare al file di log (default `../data/bot.log`).

## API
- `GET /api/runs` – elenco run con metriche aggregate.
- `GET /api/runs/:runId` – dettaglio run, equity curve, trade e opportunità collegate.
- `GET /api/logs` – ultime righe del log (max 200).
- `GET /api/status` – stato runtime del bot (abilitato, running, WebSocket, heartbeat, connessione DB).
- `POST /api/status/bot-enabled` – abilita/disabilita il bot aggiornando il flag nel DB.

## Stato sistema e toggle bot
- La tabella `runtime_status` nel DB traccia `bot_enabled`, `bot_running`, `ws_connected` e `last_heartbeat`.
- La dashboard legge questi valori via API e mostra tre indicatori (bot, WebSocket, DB).
- Il toggle “Bot abilitato” aggiorna solo il flag `bot_enabled`: se disattivato, il bot si spegne in modo pulito al prossimo check ma NON viene riavviato automaticamente (riavvio manuale via CLI/SSH).
