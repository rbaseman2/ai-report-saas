# ---- Post-checkout redirect handling (Stripe returns user to /Billing) ----
try:
    qp = st.query_params  # Streamlit >= 1.30
except Exception:
    qp = st.experimental_get_query_params()  # fallback for older Streamlit

status = None
session_id = None

# support both dict-like and QueryParams types
if isinstance(qp, dict):
    status = qp.get("status", [None])[0] if isinstance(qp.get("status"), list) else qp.get("status")
    session_id = qp.get("session_id", [None])[0] if isinstance(qp.get("session_id"), list) else qp.get("session_id")
else:
    status = qp.get("status")
    session_id = qp.get("session_id")

if status == "success":
    st.success("✅ Payment successful! Your subscription is active.")
    st.markdown(
        """
        **Next step:** Go to **Upload Data** to upload a PDF and generate your summary.
        """
    )

    col1, col2 = st.columns([1, 2])
    with col1:
        # Streamlit supports markdown links for internal pages
        st.markdown("➡️ **[Go to Upload Data](/Upload_Data)**")

    with col2:
        # Optional: show session id in small text (helpful for debugging)
        if session_id:
            st.caption(f"Checkout session: {session_id}")

    # Optional: clear query params so refresh doesn't keep showing success forever
    # Comment this out if you prefer to keep it visible
    try:
        st.query_params.clear()
    except Exception:
        st.experimental_set_query_params()

    st.stop()

elif status == "cancel":
    st.warning("Checkout was canceled. You can choose a plan below anytime.")
    # (do NOT st.stop(); let them continue to select a plan)
