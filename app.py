import os
import requests
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from streamlit_autorefresh import st_autorefresh

# ---- Configurazione iniziale ----
st.set_page_config(
    page_title="Whale Monitor Dashboard",
    page_icon=":whale:",
    layout="wide"
)

# Caricamento chiavi/API da environment (se presenti)
WHALE_API_KEY = os.getenv("WHALE_ALERT_KEY", "")
TWILIO_SID = os.getenv("TWILIO_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN", "")
TWILIO_WHATSAPP_TO = os.getenv("TWILIO_WHATSAPP_TO", "")  # destinatario WhatsApp
# Mittente WhatsApp Twilio sandbox (numero fisso fornito da Twilio)
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

# Configurazione lingua default e supportate
if "lang" not in st.session_state:
    # Imposta italiano come default
    st.session_state.lang = "it"
lang = st.session_state.lang

# Dizionari testi per EN/IT
TEXT = {
    "en": {
        "title": "Whale Monitor Dashboard",
        "subtitle": "Live tracker of large crypto transactions (Top 5 by market cap)",
        "last_update": "Last update",
        "sel_language": "Language",
        "sel_language_it": "Italiano",
        "sel_language_en": "English",
        "guide": "Open Guide",
        "auto_refresh": "Auto-refresh (every 15s)",
        "manual_refresh": "Refresh now",
        "loading": "Loading data...",
        "no_data": "No transactions to display.",
        "table_title": "Latest Whale Transactions (>$500k)",
        "col_time": "Time (UTC)",
        "col_asset": "Asset",
        "col_amount": "Amount",
        "col_amount_usd": "Value (USD)",
        "col_from": "From",
        "col_to": "To",
        "col_notes": "Notes",
        "pattern_alert": "Pattern Alert",
        "exchange_in": "Large deposit to exchange!",
        "exchange_out": "Large withdrawal from exchange!",
        "multiple_whales": "Multiple whales activity!",
        "whatsapp_alert_sent": "🔔 Alert sent via WhatsApp",
    },
    "it": {
        "title": "Dashboard Monitor Balene",
        "subtitle": "Tracciamento in tempo reale di grandi transazioni crypto (Top 5 per capitalizzazione)",
        "last_update": "Ultimo aggiornamento",
        "sel_language": "Lingua",
        "sel_language_it": "Italiano",
        "sel_language_en": "Inglese",
        "guide": "Apri Guida",
        "auto_refresh": "Aggiornamento automatico (ogni 15s)",
        "manual_refresh": "Aggiorna adesso",
        "loading": "Caricamento dati...",
        "no_data": "Nessuna transazione da mostrare.",
        "table_title": "Ultime transazioni delle balene (>$500k)",
        "col_time": "Ora (UTC)",
        "col_asset": "Asset",
        "col_amount": "Quantità",
        "col_amount_usd": "Valore (USD)",
        "col_from": "Da",
        "col_to": "A",
        "col_notes": "Note",
        "pattern_alert": "Allerta Pattern",
        "exchange_in": "Grande deposito su exchange!",
        "exchange_out": "Grande prelievo da exchange!",
        "multiple_whales": "Attività inusuale di più balene!",
        "whatsapp_alert_sent": "🔔 Allerta inviata via WhatsApp",
    }
}

# ---- Barra laterale (sidebar) ----
st.sidebar.title("Whale Monitor")
lang_option = st.sidebar.selectbox(
    TEXT[lang]["sel_language"],
    options=["Italiano", "English"],
    index=(0 if lang == "it" else 1),
)
new_lang = "it" if lang_option == "Italiano" else "en"
if new_lang != lang:
    st.session_state.lang = new_lang
    st.experimental_rerun()
lang = st.session_state.lang

# Link guida
st.sidebar.markdown(f"[*{TEXT[lang]['guide']}*](/Guida)")

# Opzione Auto-refresh
auto = st.sidebar.checkbox(TEXT[lang]["auto_refresh"], value=True)
if auto:
    st_autorefresh(interval=15000, limit=10000, key="auto_refresh")

if st.sidebar.button(TEXT[lang]["manual_refresh"]):
    st.experimental_rerun()

# ---- Titolo principale ----
st.title(TEXT[lang]["title"])
st.caption(TEXT[lang]["subtitle"])
st.write(
    f"*{TEXT[lang]['last_update']}: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC*"
)
notify_placeholder = st.empty()

columns = [
    TEXT[lang]["col_time"],
    TEXT[lang]["col_asset"],
    TEXT[lang]["col_amount"],
    TEXT[lang]["col_amount_usd"],
    TEXT[lang]["col_from"],
    TEXT[lang]["col_to"],
    TEXT[lang]["col_notes"],
]

# Fetch data from Whale Alert API
transactions = []
if WHALE_API_KEY:
    url = "https://api.whale-alert.io/v1/transactions"
    params = {
        "api_key": WHALE_API_KEY,
        "min_value": 500000,
        "currency": "USD",
    }
    try:
        resp = requests.get(url, params=params, timeout=5)
        resp.raise_for_status()
    except Exception as exc:
        st.error(f"Error fetching data from Whale Alert API: {exc}")
        resp = None
else:
    resp = None
    st.warning(
        "⚠️ Whale Alert API key not provided. Please set the WHALE_ALERT_KEY environment variable."
    )

if resp is not None and resp.ok:
    data = resp.json()
    tx_list = data.get("transactions", [])
    for tx in tx_list:
        blockchain = tx.get("blockchain", "").capitalize()
        symbol = tx.get("symbol", "").upper()
        if symbol not in ["BTC", "ETH", "USDT", "BNB", "USDC"]:
            continue
        amount = tx.get("amount", 0.0)
        amount_usd = tx.get("amount_usd", 0.0)
        timestamp = tx.get("timestamp", 0)
        dt_utc = datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        from_data = tx.get("from", {})
        to_data = tx.get("to", {})
        from_owner = from_data.get("owner")
        from_addr = from_data.get("address", "")
        from_type = from_data.get("owner_type", "")
        to_owner = to_data.get("owner")
        to_addr = to_data.get("address", "")
        to_type = to_data.get("owner_type", "")

        def _display(addr: str, owner, owner_type: str) -> str:
            if owner:
                display = owner
            elif addr:
                display = f"{addr[:6]}...{addr[-4:]}"
            else:
                display = "-"
            if owner_type == "exchange":
                display += " (exchange)"
            return display

        from_display = _display(from_addr, from_owner, from_type)
        to_display = _display(to_addr, to_owner, to_type)
        note = ""
        if from_type == "exchange" and to_type != "exchange":
            note = TEXT[lang]["exchange_out"]
        elif to_type == "exchange" and from_type != "exchange":
            note = TEXT[lang]["exchange_in"]

        transactions.append(
            [
                dt_utc,
                f"{symbol} ({blockchain})",
                f"{amount:,.4f}",
                f"${amount_usd:,.0f}",
                from_display,
                to_display,
                note,
            ]
        )
    transactions.sort(key=lambda x: x[0], reverse=True)
else:
    if resp is not None:
        st.error(f"Error fetching transactions: HTTP {resp.status_code}")

if not transactions:
    st.write(TEXT[lang]["loading"] if resp is not None else TEXT[lang]["no_data"])
else:
    df = pd.DataFrame(transactions, columns=columns)
    st.table(df)

# ---- Pattern avanzati: multiple whales in short time ----
alert_message = ""
if transactions:
    deposits = [tx for tx in transactions if TEXT[lang]["exchange_in"] in tx[-1]]
    if deposits:
        deposits_times = [datetime.strptime(tx[0], "%Y-%m-%d %H:%M:%S") for tx in deposits]
        now = datetime.utcnow()
        last_10_min_count = sum(1 for t in deposits_times if now - t <= timedelta(minutes=10))
        if last_10_min_count >= 3:
            alert_message = (
                f"{TEXT[lang]['pattern_alert']}: {TEXT[lang]['multiple_whales']}"
                f" ({last_10_min_count} deposits/10min)"
            )

if alert_message:
    st.warning(alert_message)
    if TWILIO_SID and TWILIO_TOKEN and TWILIO_WHATSAPP_TO:
        try:
            from twilio.rest import Client

            client = Client(TWILIO_SID, TWILIO_TOKEN)
            client.messages.create(
                body=f"⚠️ {alert_message}",
                from_=TWILIO_WHATSAPP_FROM,
                to=f"whatsapp:{TWILIO_WHATSAPP_TO}",
            )
            notify_placeholder.success(TEXT[lang]["whatsapp_alert_sent"])
        except Exception as exc:
            notify_placeholder.error(f"WhatsApp alert failed: {exc}")
