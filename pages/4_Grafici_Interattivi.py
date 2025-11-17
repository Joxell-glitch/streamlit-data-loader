import streamlit as st
import plotly.graph_objects as go
import pandas as pd

st.title("📊 Grafici")

df = st.session_state.get("clean_data") or st.session_state.get("raw_data")
if df is None:
    st.warning("Scarica prima i dati.")
    st.stop()

df_plot = df.copy()
df_plot["timestamp"] = pd.to_datetime(df_plot["timestamp"])

fig = go.Figure()
fig.add_trace(go.Candlestick(
    x=df_plot["timestamp"],
    open=df_plot["open"],
    high=df_plot["high"],
    low=df_plot["low"],
    close=df_plot["close"]
))
fig.update_layout(xaxis_rangeslider_visible=False)
st.plotly_chart(fig)