from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(usecwd=True), override=False, verbose=True)

# streamlit/Home.py
from dotenv import load_dotenv
load_dotenv()  # loads .env so your Streamlit env vars are available

import streamlit as st

st.set_page_config(page_title="AI Report SaaS", page_icon="📊")
st.title("AI Report SaaS")

# Dev/testing: set a default email once per session; allow editing from sidebar
if "user_email" not in st.session_state:
    st.session_state["user_email"] = "rbaseman2@yahoo.com"
with st.sidebar:
    st.text_input("Email (for entitlements)", key="user_email")

# Links to pages (filenames must match exactly and live under streamlit/pages/)
st.page_link("pages/1_Upload_Data.py", label="Start → Upload Data", icon="📄")
st.page_link("pages/2_Billing.py",     label="Billing",            icon="💳")
