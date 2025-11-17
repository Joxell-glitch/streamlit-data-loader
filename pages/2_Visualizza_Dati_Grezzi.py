import streamlit as st
from utils import basic_stats

st.title("📄 Dati Grezzi")

df = st.session_state.get("raw_data")
if df is None:
    st.warning("Scarica prima i dati.")
    st.stop()

st.write(basic_stats(df))
st.dataframe(df.head(200))