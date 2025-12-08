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
