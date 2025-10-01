import os, io, streamlit as st
from core.export_pdf import export_pdf
from core.export_docx import export_docx_bytes

st.set_page_config(page_title="Preview & Export", page_icon="📄", layout="wide")
st.title("📄 Step 3 — Preview & Export")

missing = [k for k in ("exec_summary", "kpis", "report_meta") if k not in st.session_state]
if missing:
    st.error("Not ready. Please complete Steps 1 and 2 first.")
    st.stop()

exec_summary = st.session_state["exec_summary"]
kpis = st.session_state["kpis"]
meta = st.session_state["report_meta"]
chart_png = st.session_state.get("chart_png")
logo_bytes = meta.get("logo_bytes")
brand_color = meta.get("brand_color", "#38bdf8")
title = meta.get("title", "AI Report")

st.subheader("Preview")
st.markdown(f"### {title}")
st.write(exec_summary)
st.json(kpis)
if chart_png:
    st.image(chart_png, caption="Revenue by Region", use_column_width=False)

st.divider()
col1, col2 = st.columns(2)

with col1:
    if st.button("Export as PDF"):
        pdf_path = "report.pdf"
        export_pdf(
            path=pdf_path,
            title=title,
            exec_summary=exec_summary,
            kpi_dict=kpis,
            chart_png_bytes=chart_png,
            brand_color=brand_color,
            logo_path=None if not logo_bytes else io.BytesIO(logo_bytes),
        )
        with open(pdf_path, "rb") as f:
            st.download_button("Download report.pdf", f, file_name="report.pdf", mime="application/pdf")
        try:
            os.remove(pdf_path)
        except:
            pass

with col2:
    if st.button("Export as DOCX"):
        docx_bytes = export_docx_bytes(
            title=title,
            exec_summary=exec_summary,
            kpi_dict=kpis,
            chart_png_bytes=chart_png,
            logo_bytes=logo_bytes,
        )
        st.download_button(
            "Download report.docx",
            data=docx_bytes,
            file_name="report.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
