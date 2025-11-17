import streamlit as st
from datetime import date
from data_loader import download_data

st.title("⚙️ Impostazioni Download")

if "raw_data" not in st.session_state:
    st.session_state.raw_data = None

col1, col2 = st.columns(2)
with col1:
    market_type = st.selectbox("Tipo di mercato", ["forex","crypto","stock","index","etf"])
    symbol = st.text_input("Simbolo", "EURUSD")
with col2:
    timeframe = st.selectbox("Timeframe", ["1m","5m","15m","1h","4h","1d"])
    today = date.today()
    start = st.date_input("Inizio", date(today.year-1, today.month, today.day))
    end = st.date_input("Fine", today)

if st.button("Scarica dati"):
    df = download_data(market_type, symbol, timeframe, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    st.session_state.raw_data = df
    st.success("Dati scaricati!")