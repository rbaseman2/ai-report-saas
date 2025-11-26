import requests
import streamlit as st

BACKEND_URL = st.secrets.get("BACKEND_URL")  # you already have this

st.title("Billing & Plans")

# --- Read query params from the URL (status=success, session_id=cs_...) ---
params = st.query_params  # QueryParamsProxy behaves like a dict of lists

status = params.get("status", [None])[0]
session_id = params.get("session_id", [None])[0]

if status == "success":
    st.success(
        "Checkout complete! To activate your new plan, make sure the same email "
        "you used at checkout is saved below."
    )
elif status == "cancel":
    st.info("Checkout was cancelled. You can try again or choose a different plan.")
