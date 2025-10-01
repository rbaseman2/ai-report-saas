import streamlit as st
import pandas as pd
from core.analysis import compute_kpis
from core.charting import revenue_by_region_bar
from core.summarizer import generate_exec_summary

st.set_page_config(page_title="Configure Report", page_icon="🧩", layout="wide")
st.title("🧩 Step 2 — Configure Report")

if "df" not in st.session_state:
    st.error("No data found. Please upload data in Step 1.")
    st.stop()

df: pd.DataFrame = st.session_state["df"]

with st.form("report-config"):
    col1, col2 = st.columns([2, 1])
    with col1:
        title = st.text_input("Report Title", "Monthly Sales Summary")
        sections = st.multiselect(
            "Include Sections",
            ["Executive Summary", "KPIs", "Trends"],
            default=["Executive Summary", "KPIs", "Trends"],
        )
        industry = st.selectbox("Industry tone", ["General", "Consulting", "Finance", "Marketing"], index=1)
        detail = st.select_slider("Detail level", options=["Brief", "Medium", "Detailed"], value="Medium")
    with col2:
        brand_color = st.color_picker("Brand color", "#38bdf8")
        temperature = st.slider("Creativity (temperature)", 0.0, 1.0, 0.4, 0.1)
        logo = st.file_uploader("Upload Logo (optional)", type=["png", "jpg", "jpeg"])

    generate = st.form_submit_button("Generate Insights")

if generate:
    kpis = compute_kpis(df)
    st.session_state["kpis"] = kpis
    st.session_state["report_meta"] = {
        "title": title,
        "sections": sections,
        "industry": industry,
        "detail": detail,
        "brand_color": brand_color,
        "logo_bytes": logo.read() if logo else None,
    }
    exec_summary = generate_exec_summary(
        kpis=kpis,
        context={"brand": "Rob AI Solutions", "industry": industry, "sections": sections, "detail": detail},
        temperature=temperature,
    )
    st.session_state["exec_summary"] = exec_summary

    by_region = kpis.get("by_region", {})
    chart_png = revenue_by_region_bar(by_region) if by_region else None
    st.session_state["chart_png"] = chart_png

if "exec_summary" in st.session_state:
    st.subheader("Executive Summary (AI)")
    st.write(st.session_state["exec_summary"])

    st.subheader("KPIs")
    st.json(st.session_state["kpis"])

    if st.session_state.get("chart_png"):
        st.subheader("Chart Preview")
        st.image(st.session_state["chart_png"], caption="Revenue by Region", use_column_width=False)

    st.page_link("pages/3_📄_Preview_&_Export.py", label="Continue → Preview & Export", icon="➡️")
else:
    st.info("Configure options and click **Generate Insights**.")
