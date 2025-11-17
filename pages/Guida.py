import streamlit as st

st.set_page_config(page_title="Guida - Whale Monitor", page_icon="❓", layout="wide")

lang = st.session_state.get("lang", "it")

guida_it = """
# Guida all'utilizzo di Whale Monitor

Whale Monitor controlla esclusivamente le chain **Bitcoin (BTC)** ed **Ethereum (ETH)** utilizzando solo i dati del piano gratuito di [Blockchair](https://blockchair.com/api/docs). Nessuna integrazione con Whale Alert o altri provider a pagamento.

## Cosa trovi nella dashboard
- **Slider valore minimo:** dalla sidebar imposta la soglia (100k → 10M USD, default 500k) per filtrare le transazioni mostrate e i pattern calcolati.
- **Ultime transazioni:** tabella bilingue con orario UTC, asset, valore nella coin, controvalore USD, flag coinbase e link Blockchair.
- **Pattern avanzati:** la sezione "Allerta Pattern" evidenzia tre situazioni per BTC e ETH: super-balene (tx ≥10M USD), spike di volume 30 minuti (≥50M USD in totale), spike di attività 30 minuti (≥5 tx sopra soglia). I messaggi sono in italiano/inglese.
- **Grafico dei flussi:** aggregazione dei volumi USD ogni 10 minuti per visualizzare il ritmo dei trasferimenti.
- **Heatmap attività:** matrice oraria (UTC) che mostra in quali ore le balene sono più attive per ciascuna chain.
- **Notifiche WhatsApp:** se configuri Twilio, ricevi un messaggio solo quando compare un nuovo pattern rispetto al refresh precedente.
- **Auto-refresh:** l'app si aggiorna automaticamente ogni 3 minuti (valore consigliato per restare nel limite del piano gratuito Blockchair). Puoi disattivarlo o forzare un refresh manuale.

## Configurazione WhatsApp
Inserisci in `st.secrets` le chiavi `TWILIO_SID`, `TWILIO_TOKEN`, `TWILIO_WHATSAPP_FROM`, `TWILIO_WHATSAPP_TO`. L'app invia un'unica notifica con tutti i pattern rilevati solo quando la firma dei messaggi cambia.

## Limiti e buone pratiche
- I dati provengono da Blockchair free tier: possono esserci piccoli ritardi e non sono disponibili etichette exchange.
- Solo BTC ed ETH sono supportati.
- I pattern sono indizi statistici, non consigli d'investimento.

## Avvio rapido
1. Installa le dipendenze (`pip install -r requirements.txt`).
2. Esegui `streamlit run app.py`.
3. (Opzionale) aggiungi le credenziali Twilio nei secrets.
4. Personalizza `AUTO_REFRESH_SECONDS` (minimo 60) se vuoi modificare la frequenza.

Buon monitoraggio!
"""

guida_en = """
# Guide to Using Whale Monitor

Whale Monitor focuses on **Bitcoin (BTC)** and **Ethereum (ETH)** only, pulling data exclusively from the free [Blockchair](https://blockchair.com/api/docs) plan. No Whale Alert dependency is required.

## What the dashboard includes
- **Minimum value slider:** from the sidebar you can choose the USD threshold (100k → 10M, default 500k). The filter applies to both the table and pattern logic.
- **Latest transactions:** bilingual table showing UTC time, asset, native amount, USD value, coinbase flag, and the Blockchair explorer link.
- **Advanced patterns:** the "Pattern Alert" area highlights three BTC/ETH situations—super-whale (≥$10M tx), 30-minute volume spikes (≥$50M total), and 30-minute activity spikes (≥5 transfers above the threshold). Messages adapt to the selected language.
- **Flow chart:** 10-minute buckets of USD volume to visualize how funds move over time.
- **Activity heatmap:** hour-by-hour (UTC) view of when whales are the most active per chain.
- **WhatsApp alerts:** once Twilio is configured, a notification is sent only when new patterns appear compared to the previous refresh.
- **Auto-refresh:** the app refreshes every 3 minutes by default to respect the Blockchair free-plan limits. Disable it or trigger a manual reload if needed.

## WhatsApp setup
Store `TWILIO_SID`, `TWILIO_TOKEN`, `TWILIO_WHATSAPP_FROM`, and `TWILIO_WHATSAPP_TO` inside `st.secrets`. The app builds a signature for detected patterns and sends a single message only when the signature changes.

## Limitations & tips
- Blockchair free tier may introduce slight delays and does not include exchange tagging.
- Only BTC and ETH are monitored.
- Patterns are statistical hints, not trading advice.

## Quick start
1. Install dependencies (`pip install -r requirements.txt`).
2. Launch with `streamlit run app.py`.
3. (Optional) add Twilio credentials to Streamlit secrets.
4. Adjust `AUTO_REFRESH_SECONDS` (minimum 60) if you need a different schedule.

Happy monitoring!
"""

if lang == "it":
    st.markdown(guida_it)
else:
    st.markdown(guida_en)
