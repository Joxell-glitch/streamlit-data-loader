import os
from datetime import datetime
from typing import Dict, List

import altair as alt
import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ---- Configurazione iniziale ----
st.set_page_config(
    page_title="Whale Monitor Dashboard",
    page_icon=":whale:",
    layout="wide",
)

def get_secret_value(key: str, default: str = "") -> str:
    try:
        return st.secrets.get(key, default)
    except Exception:
        return os.getenv(key, default)


TWILIO_SID = get_secret_value("TWILIO_SID", "")
TWILIO_TOKEN = get_secret_value("TWILIO_TOKEN", "")
TWILIO_WHATSAPP_TO = get_secret_value("TWILIO_WHATSAPP_TO", "")
TWILIO_WHATSAPP_FROM = get_secret_value(
    "TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886"
)

BLOCKCHAIR_BASE_URL = "https://api.blockchair.com"
SUPPORTED_ASSETS = {
    "BTC": {"chain": "bitcoin"},
    "ETH": {"chain": "ethereum"},
}
MIN_VALUE_USD = 500_000
AUTO_REFRESH_SECONDS = max(60, int(os.getenv("AUTO_REFRESH_SECONDS", "180")))
SUPER_WHALE_THRESHOLD = 10_000_000
VOLUME_SPIKE_THRESHOLD = 50_000_000
ACTIVITY_SPIKE_COUNT = 5
PATTERN_WINDOW_MINUTES = 30

# Configurazione lingua default e supportate
if "lang" not in st.session_state:
    st.session_state.lang = "it"
lang = st.session_state.lang

TEXT = {
    "en": {
        "title": "Whale Monitor Dashboard",
        "subtitle": "BTC & ETH whale activity powered by the free Blockchair API",
        "last_update": "Last update",
        "sel_language": "Language",
        "sel_language_it": "Italiano",
        "sel_language_en": "English",
        "guide": "Open Guide",
        "auto_refresh_minutes": "Automatic refresh (every {minutes} minutes)",
        "manual_refresh": "Refresh now",
        "loading": "Loading data...",
        "no_data": "No transactions to display.",
        "table_title": "Latest Whale Transactions (≥$500k)",
        "col_time": "Time (UTC)",
        "col_asset": "Asset",
        "col_value_native": "Value (coin)",
        "col_amount_usd": "Value (USD)",
        "col_coinbase": "Coinbase?",
        "col_hash": "Transaction",
        "col_signals": "Signals",
        "yes": "Yes",
        "no": "No",
        "pattern_alert": "Pattern Alert",
        "pattern_none": "No significant pattern detected in the latest data.",
        "pattern_details_title": "Potential signals detected",
        "pattern_details_none": "No alerts right now.",
        "whatsapp_alert_sent": "🔔 Alert sent via WhatsApp",
        "data_source_blockchair": "Data provided by Blockchair (free plan, BTC and ETH)",
        "signals_column_default": "-",
        "min_value_label": "Minimum transaction value (USD)",
        "flow_chart_title": "Whale flows over time (USD)",
        "heatmap_title": "Whale activity heatmap by hour (UTC)",
        "blockchair_error_msg": "Error fetching data from Blockchair (free plan). Please try again later.",
        "super_whale_msg": "Super-whale on {chain}: at least one transaction ≥ 10M USD.",
        "volume_spike_msg": "Volume spike on {chain}: ≥ {value} USD moved in the last 30 minutes.",
        "activity_spike_msg": "Activity spike on {chain}: {count} transactions ≥ {threshold} in the last 30 minutes.",
        "no_pattern_msg": "No significant pattern detected in the latest data.",
        "not_enough_data_msg": "Not enough data to build this visualization yet.",
    },
    "it": {
        "title": "Dashboard Monitor Balene",
        "subtitle": "Attività delle balene BTC e ETH con API gratuita di Blockchair",
        "last_update": "Ultimo aggiornamento",
        "sel_language": "Lingua",
        "sel_language_it": "Italiano",
        "sel_language_en": "Inglese",
        "guide": "Apri Guida",
        "auto_refresh_minutes": "Aggiornamento automatico (ogni {minutes} minuti)",
        "manual_refresh": "Aggiorna adesso",
        "loading": "Caricamento dati...",
        "no_data": "Nessuna transazione da mostrare.",
        "table_title": "Ultime transazioni delle balene (≥$500k)",
        "col_time": "Ora (UTC)",
        "col_asset": "Asset",
        "col_value_native": "Valore (coin)",
        "col_amount_usd": "Valore (USD)",
        "col_coinbase": "Coinbase?",
        "col_hash": "Transazione",
        "col_signals": "Segnali",
        "yes": "Sì",
        "no": "No",
        "pattern_alert": "Allerta Pattern",
        "pattern_none": "Nessun pattern particolare rilevato negli ultimi dati.",
        "pattern_details_title": "Segnali potenziali rilevati",
        "pattern_details_none": "Nessuna allerta al momento.",
        "whatsapp_alert_sent": "🔔 Allerta inviata via WhatsApp",
        "data_source_blockchair": "Dati forniti da Blockchair (piano gratuito, BTC ed ETH)",
        "signals_column_default": "-",
        "min_value_label": "Valore minimo transazione (USD)",
        "flow_chart_title": "Flussi delle balene nel tempo (USD)",
        "heatmap_title": "Heatmap attività balene per ora (UTC)",
        "blockchair_error_msg": "Errore nel recupero dati da Blockchair (piano gratuito). Riprova più tardi.",
        "super_whale_msg": "Super-balena su {chain}: almeno una transazione ≥ 10M USD.",
        "volume_spike_msg": "Spike di volume su {chain}: ≥ {value} USD mossi negli ultimi 30 minuti.",
        "activity_spike_msg": "Spike di attività su {chain}: {count} transazioni ≥ {threshold} negli ultimi 30 minuti.",
        "no_pattern_msg": "Nessun pattern particolare rilevato negli ultimi dati.",
        "not_enough_data_msg": "Dati insufficienti per costruire questa visualizzazione.",
    },
}


def format_minutes(seconds: int) -> str:
    minutes = seconds / 60
    if minutes.is_integer():
        return str(int(minutes))
    return f"{minutes:.1f}"


def format_usd(value: float) -> str:
    return f"${value:,.0f}"


def fetch_blockchair_transactions(asset_symbol: str, chain: str, limit: int = 100) -> pd.DataFrame:
    url = f"{BLOCKCHAIR_BASE_URL}/{chain}/transactions"
    params = {"limit": limit}
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"{chain}: {exc}") from exc

    payload = response.json()
    tx_list = payload.get("data", [])
    rows = []
    for tx in tx_list:
        tx_hash = tx.get("hash")
        if not tx_hash:
            continue
        time_value = tx.get("time")
        try:
            tx_time = pd.to_datetime(time_value, utc=True)
        except Exception:
            continue
        input_total = float(tx.get("input_total") or 0)
        output_total = float(tx.get("output_total") or 0)
        input_total_usd = float(tx.get("input_total_usd") or 0)
        output_total_usd = float(tx.get("output_total_usd") or 0)
        value_native = max(input_total, output_total)
        value_usd = max(input_total_usd, output_total_usd)
        rows.append(
            {
                "asset": asset_symbol,
                "chain": chain,
                "time": tx_time,
                "tx_hash": tx_hash,
                "value_native": value_native,
                "value_usd": value_usd,
                "is_coinbase": bool(tx.get("is_coinbase", False)),
                "link_explorer": f"https://blockchair.com/{chain}/transaction/{tx_hash}",
            }
        )
    return pd.DataFrame(rows)


def load_whale_transactions(min_value_usd: float = MIN_VALUE_USD) -> pd.DataFrame:
    frames = []
    for asset_symbol, meta in SUPPORTED_ASSETS.items():
        df_chain = fetch_blockchair_transactions(asset_symbol, meta["chain"], limit=100)
        frames.append(df_chain)
    if not frames:
        return pd.DataFrame()
    df_all = pd.concat(frames, ignore_index=True)
    df_all = df_all[df_all["value_usd"] >= min_value_usd]
    if df_all.empty:
        return df_all
    return df_all.sort_values("time", ascending=False).reset_index(drop=True)


def detect_pattern_messages(
    df: pd.DataFrame, lang_key: str, min_value_usd: float
) -> List[str]:
    if df.empty:
        return []

    now_utc = pd.Timestamp.utcnow().tz_localize("UTC")
    window_start = now_utc - pd.Timedelta(minutes=PATTERN_WINDOW_MINUTES)
    messages: List[str] = []

    for asset_symbol in SUPPORTED_ASSETS.keys():
        subset = df[df["asset"] == asset_symbol]
        if subset.empty:
            continue
        if subset["value_usd"].max() >= SUPER_WHALE_THRESHOLD:
            messages.append(TEXT[lang_key]["super_whale_msg"].format(chain=asset_symbol))

        recent = subset[subset["time"] >= window_start]
        if recent.empty:
            continue
        vol_30 = recent["value_usd"].sum()
        if vol_30 >= VOLUME_SPIKE_THRESHOLD:
            messages.append(
                TEXT[lang_key]["volume_spike_msg"].format(
                    chain=asset_symbol, value=format_usd(vol_30)
                )
            )
        count_30 = len(recent)
        if count_30 >= ACTIVITY_SPIKE_COUNT:
            messages.append(
                TEXT[lang_key]["activity_spike_msg"].format(
                    chain=asset_symbol,
                    count=count_30,
                    threshold=format_usd(min_value_usd),
                )
            )

    return messages


def send_whatsapp_alert(pattern_messages: List[str]) -> bool:
    if not (TWILIO_SID and TWILIO_TOKEN and TWILIO_WHATSAPP_TO):
        return False
    if not pattern_messages:
        return False
    try:
        from twilio.rest import Client

        client = Client(TWILIO_SID, TWILIO_TOKEN)
        body = "⚠️ Nuovo pattern balene rilevato:\n" + "\n".join(pattern_messages)
        client.messages.create(
            body=body,
            from_=TWILIO_WHATSAPP_FROM,
            to=f"whatsapp:{TWILIO_WHATSAPP_TO}",
        )
        return True
    except Exception as exc:
        st.warning(f"WhatsApp alert failed: {exc}")
        return False

# ---- Barra laterale ----
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

st.sidebar.markdown(f"[*{TEXT[lang]['guide']}*](/Guida)")
st.sidebar.caption(TEXT[lang]["data_source_blockchair"])

min_value_usd = st.sidebar.slider(
    TEXT[lang]["min_value_label"],
    min_value=100_000,
    max_value=10_000_000,
    value=500_000,
    step=50_000,
)

auto_refresh_label = TEXT[lang]["auto_refresh_minutes"].format(
    minutes=format_minutes(AUTO_REFRESH_SECONDS)
)
auto = st.sidebar.checkbox(auto_refresh_label, value=True)
if auto:
    st_autorefresh(interval=AUTO_REFRESH_SECONDS * 1000, limit=10000, key="auto_refresh")

if st.sidebar.button(TEXT[lang]["manual_refresh"]):
    st.experimental_rerun()

# ---- Titolo principale ----
st.title(TEXT[lang]["title"])
st.caption(TEXT[lang]["subtitle"])
st.write(
    f"*{TEXT[lang]['last_update']}: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC*"
)
notify_placeholder = st.empty()

with st.spinner(TEXT[lang]["loading"]):
    try:
        df_transactions = load_whale_transactions(min_value_usd)
    except RuntimeError:
        st.error(TEXT[lang]["blockchair_error_msg"])
        df_transactions = pd.DataFrame()

pattern_messages = detect_pattern_messages(df_transactions, lang, min_value_usd)

if "last_sig" not in st.session_state:
    st.session_state["last_sig"] = ""

signature = "|".join(sorted(pattern_messages)) if pattern_messages else ""
if signature != st.session_state["last_sig"] and pattern_messages:
    if send_whatsapp_alert(pattern_messages):
        notify_placeholder.success(TEXT[lang]["whatsapp_alert_sent"])
    st.session_state["last_sig"] = signature
else:
    st.session_state["last_sig"] = signature

st.subheader(TEXT[lang]["pattern_alert"])
if pattern_messages:
    for message in pattern_messages:
        st.markdown(f"- {message}")
else:
    st.info(TEXT[lang]["no_pattern_msg"])

st.markdown(f"### {TEXT[lang]['table_title']}")
if df_transactions.empty:
    st.info(TEXT[lang]["no_data"])
else:
    df_transactions["signals_text"] = TEXT[lang]["signals_column_default"]
    df_transactions["display_time"] = df_transactions["time"].dt.strftime("%Y-%m-%d %H:%M:%S")
    df_transactions["value_native_fmt"] = df_transactions.apply(
        lambda row: f"{row['value_native']:,.4f} {row['asset']}", axis=1
    )
    df_transactions["value_usd_fmt"] = df_transactions["value_usd"].apply(format_usd)
    df_transactions["coinbase_fmt"] = df_transactions["is_coinbase"].apply(
        lambda x: TEXT[lang]["yes"] if x else TEXT[lang]["no"]
    )
    df_transactions["tx_link"] = df_transactions.apply(
        lambda row: f"<a href='{row['link_explorer']}' target='_blank'>{row['tx_hash'][:12]}...</a>",
        axis=1,
    )

    display_df = pd.DataFrame(
        {
            TEXT[lang]["col_time"]: df_transactions["display_time"],
            TEXT[lang]["col_asset"]: df_transactions["asset"],
            TEXT[lang]["col_value_native"]: df_transactions["value_native_fmt"],
            TEXT[lang]["col_amount_usd"]: df_transactions["value_usd_fmt"],
            TEXT[lang]["col_coinbase"]: df_transactions["coinbase_fmt"],
            TEXT[lang]["col_signals"]: df_transactions["signals_text"],
            TEXT[lang]["col_hash"]: df_transactions["tx_link"],
        }
    )

    styled = display_df.style
    st.write(styled.to_html(escape=False), unsafe_allow_html=True)

st.markdown(f"### {TEXT[lang]['flow_chart_title']}")
if df_transactions.empty:
    st.info(TEXT[lang]["not_enough_data_msg"])
else:
    df_transactions["time_bucket"] = df_transactions["time"].dt.floor("10min")
    flows = (
        df_transactions.groupby(["time_bucket", "asset"])["value_usd"]
        .sum()
        .unstack("asset", fill_value=0)
    )
    if flows.empty:
        st.info(TEXT[lang]["not_enough_data_msg"])
    else:
        st.line_chart(flows)

st.markdown(f"### {TEXT[lang]['heatmap_title']}")
if df_transactions.empty:
    st.info(TEXT[lang]["not_enough_data_msg"])
else:
    df_transactions["hour_utc"] = df_transactions["time"].dt.hour
    heat = (
        df_transactions.groupby(["hour_utc", "asset"]).size().reset_index(name="count")
    )
    if heat.empty:
        st.info(TEXT[lang]["not_enough_data_msg"])
    else:
        chart = (
            alt.Chart(heat)
            .mark_rect()
            .encode(
                x=alt.X("hour_utc:O", title="Hour (UTC)"),
                y=alt.Y("asset:N", title="Asset"),
                color=alt.Color("count:Q", title="Count", scale=alt.Scale(scheme="inferno")),
                tooltip=["asset", "hour_utc", "count"],
            )
        )
        st.altair_chart(chart, use_container_width=True)
