import streamlit as st

st.set_page_config(page_title="AI Report Generator", page_icon="📊", layout="wide")

st.title("📊 AI Business Report Generator")
st.write("Upload your data, configure branding, and export a polished, client-ready report.")

st.page_link("pages/1_🏁_Upload_Data.py", label="Start → Upload Data", icon="🏁")
st.page_link("pages/2_🧩_Configure_Report.py", label="Step 2 → Configure Report", icon="🧩")
st.page_link("pages/3_📄_Preview_&_Export.py", label="Step 3 → Preview & Export", icon="📄")

st.divider()
st.caption("Tip: Move through the steps from left to right. Your progress is saved in session state.")
