import streamlit as st

# ---------------------------------------------------------
# Page Config
# ---------------------------------------------------------
st.set_page_config(
    page_title="AI Report Generator",
    page_icon="📊",
    layout="wide"
)

# ---------------------------------------------------------
# Detect Stripe Checkout Return
# ---------------------------------------------------------
params = st.query_params

checkout_success = (
    params.get("checkout") == "success"
    or "session_id" in params
)

# ---------------------------------------------------------
# Post-Checkout Success UI (Safe / No Billing Changes)
# ---------------------------------------------------------
if checkout_success:
    st.success("✅ Payment successful! You're ready to upload your data.")

    if st.button("Go to Upload Data"):
        st.switch_page("pages/1_🏁_Upload_Data.py")

    st.stop()  # Prevent normal page content from rendering

# ---------------------------------------------------------
# Normal Landing Page Content
# ---------------------------------------------------------
st.title("📊 AI Business Report Generator")
st.write("Upload your data, configure branding, and export a polished, client-ready report.")

st.page_link("pages/1_🏁_Upload_Data.py", label="Start → Upload Data", icon="🏁")
st.page_link("pages/2_🧩_Configure_Report.py", label="Step 2 → Configure Report", icon="🧩")
st.page_link("pages/3_📄_Preview_&_Export.py", label="Step 3 → Preview & Export", icon="📄")

st.divider()
st.caption("Tip: Move through the steps from left to right. Your progress is saved in session state.")
