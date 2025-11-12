import os
import streamlit as st

st.set_page_config(page_title="Home", page_icon="🏠")

st.sidebar.title("Navigation")
st.sidebar.page_link("Home.py", label="Home", icon="🏠")
st.sidebar.page_link("pages/1_Upload_Data.py", label="Upload Data", icon="📤")
st.sidebar.page_link("pages/2_Billing.py", label="Billing", icon="💳")

st.title("Welcome")

# if you previously imported dotenv here, remove it unless you really use it
# from dotenv import load_dotenv  # <- not needed for Render env vars

st.write("Your Streamlit app is live on Render.")
