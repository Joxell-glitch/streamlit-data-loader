import streamlit as st

st.set_page_config(page_title="Guida - Whale Monitor", page_icon="❓", layout="wide")

lang = st.session_state.get("lang", "it")

guida_it = """
# Guida all'utilizzo di Whale Monitor

Whale Monitor è una dashboard personale per tracciare i movimenti delle balene su **Bitcoin (BTC)** ed **Ethereum (ETH)**. I dati provengono esclusivamente dalla REST API gratuita di [Blockchair](https://blockchair.com/api/docs), così puoi usare l'app senza chiavi proprietarie a pagamento.

## Sezioni della Dashboard
- **Ultime transazioni delle balene:** tabella aggiornata con le transazioni sopra i 500.000 USD su BTC/ETH. Per ogni movimento sono mostrati: ora UTC, asset, valore nella coin, controvalore USD, flag Coinbase (true/false) e link diretto all'explorer Blockchair.
- **Pattern di attenzione:** la sezione "Allerta Pattern" riassume eventuali segnali statistici come super-balene (singole tx ≥10M USD), cluster multipli (almeno 3 tx ≥1M USD in 30 minuti sulla stessa chain) e spike d'attività (variazioni nette di tx ≥500k USD tra l'ultima ora e la precedente). Questi non sono consigli di investimento, ma indizi da monitorare.
- **Auto-refresh:** per rispettare i limiti gratuiti di Blockchair, l'aggiornamento automatico è impostato di default a ogni 3 minuti. Puoi disattivarlo dalla sidebar o forzare un refresh manuale con il pulsante "Aggiorna adesso".

## Notifiche WhatsApp (Twilio)
Configura le variabili `TWILIO_SID`, `TWILIO_TOKEN`, `TWILIO_WHATSAPP_TO`, `TWILIO_WHATSAPP_FROM` per ricevere messaggi WhatsApp quando viene rilevato un nuovo pattern rispetto al precedente refresh. Ogni alert contiene asset, valore stimato, timestamp UTC e link Blockchair.

## Suggerimenti di lettura dei segnali
- **Super-balena:** singola transazione gigantesca (≥10M USD). Può precedere movimenti di mercato importanti, specialmente se avviene vicino a resistenze o supporti.
- **Cluster di balene:** almeno tre trasferimenti ≥1M USD sulla stessa chain in 30 minuti. I cluster possono indicare coordinamento o risposta a una notizia in arrivo.
- **Spike improvviso:** quando nell'ultima ora avviene un numero di transazioni ≥500k USD molto superiore all'ora precedente. Può essere preludio a volatilità.

## Limiti e buone pratiche
- Solo BTC ed ETH sono monitorati. Altre chain non sono incluse.
- I dati sono pubblici e potrebbero avere ritardi di alcuni secondi rispetto al blocco originale.
- Nessun indirizzo viene etichettato come exchange nel piano gratuito Blockchair, quindi il contesto "deposito" o "prelievo" non è disponibile.
- I segnali sono indicazioni statistiche, **non** garanzie di profitto. Combinali con analisi tecnica/fondamentale.

## Configurazione rapida
1. Installa le dipendenze (`pip install -r requirements.txt`).
2. Esegui `streamlit run app.py`.
3. (Opzionale) Imposta le credenziali Twilio per WhatsApp.
4. Personalizza l'intervallo di refresh settando `AUTO_REFRESH_SECONDS` (minimo 60s) se vuoi limitare ulteriormente le richieste a Blockchair.

Buon monitoraggio e buona gestione del rischio!
"""

guida_en = """
# Guide to Using Whale Monitor

Whale Monitor is a personal dashboard to track whale movements on **Bitcoin (BTC)** and **Ethereum (ETH)**. All data comes from the free [Blockchair](https://blockchair.com/api/docs) REST API, so you no longer need a paid Whale Alert key.

## Dashboard Sections
- **Latest whale transactions:** table listing BTC/ETH transfers above $500k USD. Each row shows UTC time, asset, value in native coin, USD estimate, Coinbase flag, and a direct Blockchair explorer link.
- **Attention patterns:** the "Pattern Alert" section lists statistical signals such as super-whales (single tx ≥$10M), whale clusters (≥3 tx ≥$1M within 30 minutes on the same chain), and activity spikes (big change in ≥$500k tx between the last hour and the previous hour). These are *not* investment advice—use them as early warnings.
- **Auto-refresh:** to stay within Blockchair's free quota, automatic refresh defaults to every 3 minutes. Disable it from the sidebar or press "Refresh now" for a manual update.

## WhatsApp Notifications (Twilio)
Set `TWILIO_SID`, `TWILIO_TOKEN`, `TWILIO_WHATSAPP_TO`, and `TWILIO_WHATSAPP_FROM` to receive WhatsApp alerts when a new pattern appears compared to the previous refresh. Alerts include asset, estimated value, UTC timestamp, and a Blockchair link.

## Reading the Signals
- **Super-whale:** a single massive transfer (≥$10M). It often precedes strong market moves, especially if liquidity is thin.
- **Whale cluster:** at least three ≥$1M transfers on the same chain within 30 minutes, possibly hinting at coordinated activity or reaction to fresh news.
- **Sudden spike:** when the number of ≥$500k transfers in the last hour far exceeds the previous hour. Expect volatility when this happens near key price levels.

## Limitations & Best Practices
- Only BTC and ETH are covered.
- Data may lag the on-chain block by a few seconds.
- Exchange tagging is unavailable on the free Blockchair tier, so direction (deposit/withdrawal) is unknown.
- Signals are statistical hints, **not** financial advice. Combine them with your own analysis.

## Quick Setup
1. Install dependencies (`pip install -r requirements.txt`).
2. Run `streamlit run app.py`.
3. (Optional) add Twilio WhatsApp credentials for push alerts.
4. Adjust `AUTO_REFRESH_SECONDS` (minimum 60s) if you need a different polling interval.

Happy monitoring—and stay cautious!
"""

if lang == "it":
    st.markdown(guida_it)
else:
    st.markdown(guida_en)
