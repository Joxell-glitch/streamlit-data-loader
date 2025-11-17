import os
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

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

TWILIO_SID = os.getenv("TWILIO_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN", "")
TWILIO_WHATSAPP_TO = os.getenv("TWILIO_WHATSAPP_TO", "")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

BLOCKCHAIR_BASE_URL = "https://api.blockchair.com"
SUPPORTED_ASSETS = {
    "BTC": {"chain": "bitcoin"},
    "ETH": {"chain": "ethereum"},
}
MIN_VALUE_USD = 500_000
AUTO_REFRESH_SECONDS = max(60, int(os.getenv("AUTO_REFRESH_SECONDS", "180")))
SUPER_WHALE_THRESHOLD = 10_000_000
CLUSTER_WINDOW_MIN = 30
CLUSTER_MIN_COUNT = 3
CLUSTER_THRESHOLD_USD = 1_000_000
SPIKE_WINDOW_HOURS = 1
SPIKE_MIN_DIFF = 5

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
        "pattern_none": "No special patterns detected in the latest data.",
        "pattern_super_whale": "Super-whale: transaction ≥ {value_usd} on {asset}.",
        "pattern_cluster": "Cluster on {asset}: {count} tx ≥ $1M within 30 minutes.",
        "pattern_spike": "Activity spike on {asset}: {count_current} tx ≥ $500k in the last hour vs {count_previous} in the previous hour.",
        "signal_super_whale": "Super-whale",
        "signal_cluster": "Cluster",
        "signal_spike": "Spike",
        "pattern_details_title": "Potential signals detected",
        "pattern_details_none": "No alerts right now.",
        "whatsapp_alert_sent": "🔔 Alert sent via WhatsApp",
        "data_source_blockchair": "Data provided by Blockchair (free plan, BTC and ETH)",
        "error_blockchair": "Error retrieving data from Blockchair: {error}",
        "signals_column_default": "-",
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
        "pattern_super_whale": "Super-balena: transazione ≥ {value_usd} su {asset}.",
        "pattern_cluster": "Cluster su {asset}: {count} tx ≥ 1M $ in 30 minuti.",
        "pattern_spike": "Spike di attività su {asset}: {count_current} tx ≥ 500k $ nell'ultima ora vs {count_previous} nell'ora precedente.",
        "signal_super_whale": "Super-balena",
        "signal_cluster": "Cluster",
        "signal_spike": "Spike",
        "pattern_details_title": "Segnali potenziali rilevati",
        "pattern_details_none": "Nessuna allerta al momento.",
        "whatsapp_alert_sent": "🔔 Allerta inviata via WhatsApp",
        "data_source_blockchair": "Dati forniti da Blockchair (piano gratuito, BTC ed ETH)",
        "error_blockchair": "Errore nel recupero dati da Blockchair: {error}",
        "signals_column_default": "-",
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
    params = {"s": "time(desc)", "limit": limit}
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
                "input_total": input_total,
                "input_total_usd": input_total_usd,
                "output_total": output_total,
                "output_total_usd": output_total_usd,
                "value_native": value_native,
                "value_usd": value_usd,
                "is_coinbase": bool(tx.get("is_coinbase", False)),
                "direction": "transfer",
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


def detect_patterns(df: pd.DataFrame) -> Tuple[List[Dict], Dict[str, List[str]]]:
    patterns: List[Dict] = []
    signal_map: Dict[str, List[str]] = {}
    if df.empty:
        return patterns, signal_map

    latest_time = df["time"].max()

    # Super whale pattern
    super_rows = df[df["value_usd"] >= SUPER_WHALE_THRESHOLD]
    for _, row in super_rows.iterrows():
        pattern_id = f"super_{row['tx_hash']}"
        patterns.append(
            {
                "id": pattern_id,
                "type": "super_whale",
                "asset": row["asset"],
                "value_usd": row["value_usd"],
                "time": row["time"],
                "tx_hash": row["tx_hash"],
                "link": row["link_explorer"],
            }
        )
        signal_map.setdefault(row["tx_hash"], []).append("super_whale")

    # Cluster pattern
    cluster_window_start = latest_time - timedelta(minutes=CLUSTER_WINDOW_MIN)
    recent = df[df["time"] >= cluster_window_start]
    for asset_symbol in SUPPORTED_ASSETS.keys():
        subset = recent[(recent["asset"] == asset_symbol) & (recent["value_usd"] >= CLUSTER_THRESHOLD_USD)]
        if len(subset) >= CLUSTER_MIN_COUNT:
            subset = subset.sort_values("time", ascending=False)
            ref_row = subset.iloc[0]
            pattern_id = f"cluster_{asset_symbol}_{int(ref_row['time'].timestamp())}"
            patterns.append(
                {
                    "id": pattern_id,
                    "type": "cluster",
                    "asset": asset_symbol,
                    "count": len(subset),
                    "value_usd": ref_row["value_usd"],
                    "time": ref_row["time"],
                    "tx_hash": ref_row["tx_hash"],
                    "link": ref_row["link_explorer"],
                }
            )
            for tx_hash in subset["tx_hash"].tolist():
                signal_map.setdefault(tx_hash, []).append("cluster")

    # Spike pattern (compare last hour vs previous hour)
    hour_window_start = latest_time - timedelta(hours=SPIKE_WINDOW_HOURS)
    two_hour_window_start = latest_time - timedelta(hours=2 * SPIKE_WINDOW_HOURS)
    for asset_symbol in SUPPORTED_ASSETS.keys():
        current_mask = (
            (df["asset"] == asset_symbol)
            & (df["value_usd"] >= MIN_VALUE_USD)
            & (df["time"] >= hour_window_start)
        )
        previous_mask = (
            (df["asset"] == asset_symbol)
            & (df["value_usd"] >= MIN_VALUE_USD)
            & (df["time"] >= two_hour_window_start)
            & (df["time"] < hour_window_start)
        )
        count_current = int(current_mask.sum())
        count_previous = int(previous_mask.sum())
        if count_current - count_previous >= SPIKE_MIN_DIFF and count_current >= SPIKE_MIN_DIFF:
            subset = df[current_mask].sort_values("time", ascending=False)
            ref_row = subset.iloc[0]
            pattern_id = f"spike_{asset_symbol}_{int(ref_row['time'].timestamp())}"
            patterns.append(
                {
                    "id": pattern_id,
                    "type": "spike",
                    "asset": asset_symbol,
                    "count_current": count_current,
                    "count_previous": count_previous,
                    "value_usd": ref_row["value_usd"],
                    "time": ref_row["time"],
                    "tx_hash": ref_row["tx_hash"],
                    "link": ref_row["link_explorer"],
                }
            )
            for tx_hash in subset["tx_hash"].tolist():
                signal_map.setdefault(tx_hash, []).append("spike")

    return patterns, signal_map


def describe_pattern(pattern: Dict, lang_key: str) -> str:
    if pattern["type"] == "super_whale":
        return TEXT[lang_key]["pattern_super_whale"].format(
            value_usd=format_usd(pattern["value_usd"]), asset=pattern["asset"]
        )
    if pattern["type"] == "cluster":
        return TEXT[lang_key]["pattern_cluster"].format(
            asset=pattern["asset"], count=pattern.get("count", 0)
        )
    if pattern["type"] == "spike":
        return TEXT[lang_key]["pattern_spike"].format(
            asset=pattern["asset"],
            count_current=pattern.get("count_current", 0),
            count_previous=pattern.get("count_previous", 0),
        )
    return ""


def send_whatsapp_alert(patterns: List[Dict], lang_key: str) -> bool:
    if not (TWILIO_SID and TWILIO_TOKEN and TWILIO_WHATSAPP_TO):
        return False
    sent_any = False
    try:
        from twilio.rest import Client

        client = Client(TWILIO_SID, TWILIO_TOKEN)
        for pattern in patterns:
            description = describe_pattern(pattern, lang_key)
            timestamp = pattern["time"].strftime("%Y-%m-%d %H:%M:%S UTC")
            value = format_usd(pattern.get("value_usd", 0))
            message_lines = [
                "⚠️ Whale Monitor Alert",
                description,
                f"Asset: {pattern['asset']}",
                f"Value: {value}",
                f"Time: {timestamp}",
            ]
            if pattern.get("link"):
                message_lines.append(pattern["link"])
            if pattern.get("tx_hash"):
                message_lines.append(f"TX: {pattern['tx_hash']}")
            client.messages.create(
                body="\n".join(message_lines),
                from_=TWILIO_WHATSAPP_FROM,
                to=f"whatsapp:{TWILIO_WHATSAPP_TO}",
            )
            sent_any = True
    except Exception as exc:
        st.warning(f"WhatsApp alert failed: {exc}")
        return False
    return sent_any

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
        df_transactions = load_whale_transactions(MIN_VALUE_USD)
    except RuntimeError as exc:
        st.error(TEXT[lang]["error_blockchair"].format(error=exc))
        df_transactions = pd.DataFrame()

patterns, signal_map = detect_patterns(df_transactions)
if "last_pattern_ids" not in st.session_state:
    st.session_state.last_pattern_ids = set()

current_pattern_ids = {p["id"] for p in patterns}
previous_pattern_ids = st.session_state.last_pattern_ids
new_patterns = [p for p in patterns if p["id"] not in previous_pattern_ids]
st.session_state.last_pattern_ids = current_pattern_ids

if new_patterns:
    if send_whatsapp_alert(new_patterns, lang):
        notify_placeholder.success(TEXT[lang]["whatsapp_alert_sent"])

st.subheader(TEXT[lang]["pattern_alert"])
if patterns:
    for pattern in patterns:
        st.markdown(f"- {describe_pattern(pattern, lang)}")
else:
    st.info(TEXT[lang]["pattern_none"])

st.markdown(f"### {TEXT[lang]['table_title']}")
if df_transactions.empty:
    st.info(TEXT[lang]["no_data"])
else:
    df_transactions["signal_keys"] = df_transactions["tx_hash"].map(lambda x: signal_map.get(x, []))
    df_transactions["signals_text"] = df_transactions["signal_keys"].apply(
        lambda keys: ", ".join(TEXT[lang].get(f"signal_{k}", k) for k in keys) if keys else TEXT[lang]["signals_column_default"]
    )
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

    signal_mask = df_transactions["signal_keys"].apply(bool)

    def highlight_row(row):
        if signal_mask.iloc[row.name]:
            return ["background-color: #fff3cd" for _ in row]
        return ["" for _ in row]

    styled = display_df.style.apply(highlight_row, axis=1)
    st.write(styled.to_html(escape=False), unsafe_allow_html=True)
