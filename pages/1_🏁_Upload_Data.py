import io
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Upload Data", page_icon="🏁", layout="wide")
st.title("🏁 Step 1 — Upload Data")

uploaded = st.file_uploader("Upload a CSV or Excel file", type=["csv", "xlsx"])

sample = st.checkbox("Use sample dataset instead", value=False)
if sample:
    sample_csv = """Date,Region,Salesperson,Revenue
2025-07-01,East,Rob,5400
2025-07-02,West,Tina,3200
2025-07-05,East,Rob,7000
2025-07-09,West,Tina,2100
"""
    df = pd.read_csv(io.StringIO(sample_csv))
    st.session_state["df"] = df
    st.success("Loaded sample data.")
elif uploaded:
    if uploaded.name.lower().endswith(".csv"):
        df = pd.read_csv(uploaded)
    else:
        df = pd.read_excel(uploaded)
    st.session_state["df"] = df
    st.success(f"Loaded {uploaded.name}")

if "df" in st.session_state:
    st.subheader("Data Preview")
    st.dataframe(st.session_state["df"].head(50), use_container_width=True)
    st.page_link("pages/2_🧩_Configure_Report.py", label="Continue → Configure", icon="➡️")
else:
    st.info("Upload a file or tick 'Use sample dataset' to continue.")
