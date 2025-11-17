import streamlit as st

st.title("💾 Esporta")

raw = st.session_state.get("raw_data")
clean = st.session_state.get("clean_data")

if raw is None:
    st.warning("Scarica prima i dati.")
    st.stop()

st.download_button("Scarica RAW CSV", raw.to_csv(index=False), "raw.csv")
if clean is not None:
    st.download_button("Scarica CLEAN CSV", clean.to_csv(index=False), "clean.csv")