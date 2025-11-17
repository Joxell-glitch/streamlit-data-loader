import streamlit as st
from utils import detect_gaps, detect_duplicates, clean_data

st.title("🧹 Pulizia")

df = st.session_state.get("raw_data")
if df is None:
    st.warning("Scarica prima i dati.")
    st.stop()

st.subheader("Gap")
st.write(detect_gaps(df, "1H").head())

st.subheader("Duplicati")
st.write(detect_duplicates(df).head())

if st.button("Pulisci"):
    cl = clean_data(df)
    st.session_state.clean_data = cl
    st.success("Pulizia fatta!")