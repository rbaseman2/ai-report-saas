import os
import requests
import streamlit as st

# -------------------------------------------------------------------
# Config
# -------------------------------------------------------------------

BACKEND_URL = st.secrets.get("BACKEND_URL", "https://ai-report-backend-ubrx.onrender.com")

PLANS = {
    "basic": {
        "name": "Basic",
        "price_display": "$9.99 / month",
        "reports_per_month": "Up to 20 reports / month",
        "characters_per_month": "Up to 400k characters / month",
        "features": [
            "Executive summaries + key insights",
        ],
    },
    "pro": {
        "name": "Pro",
        "price_display": "$19.99 / month",
        "reports_per_month": "Up to 75 reports / month",
        "characters_per_month": "Up to 1.5M characters / month",
        "features": [
            "Action items, risks, and opportunity insights",
        ],
    },
    "enterprise": {
        "name": "Enterprise",
        "price_display": "$39.99 / month",
        "reports_per_month": "Up to 250 reports / month",
        "characters_per_month": "Up to 5M characters / month",
        "features": [
            "Team accounts, shared templates, & premium support",
        ],
    },
}


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def get_email() -> str:
    """Read the email from session state or the text input."""
    if "billing_email" not in st.session_state:
        st.session_state.billing_email = ""
    return st.session_state.billing_email


def set_email(email: str) -> None:
    st.session_state.billing_email = email.strip()


def get_coupon() -> str:
    if "billing_coupon" not in st.session_state:
        st.session_state.billing_coupon = ""
    return st.session_state.billing_coupon


def set_coupon(code: str) -> None:
    st.session_state.billing_coupon = code.strip()


def fetch_subscription_status(email: str):
    """Ask the backend what plan (if any) this email currently has."""
    if not email:
        return None

    try:
        resp = requests.get(
            f"{BACKEND_URL}/subscription-status",
            params={"email": email},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as exc:
        st.warning(f"Could not refresh subscription status: {exc}")
        return None


def start_checkout(plan: str, email: str, coupon: str | None) -> None:
    """Call the backend to create a Stripe Checkout session."""
    if not email or "@" not in email:
        st.error("Please enter a valid email address before subscribing.")
        return

    payload = {"plan": plan, "email": email}
    if coupon:
        payload["coupon"] = coupon

    try:
        resp = requests.post(
            f"{BACKEND_URL}/create-checkout-session",
            json=payload,
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        checkout_url = data.get("checkout_url")
        if not checkout_url:
            st.error("Backend did not return a checkout URL.")
            return
        st.write("Redirecting you to Stripe Checkout...")
        st.markdown(
            f"[Click here if you are not redirected automatically]({checkout_url})"
        )
        st.experimental_set_query_params()  # clear URL params
        st.experimental_rerun()
    except requests.exceptions.HTTPError as exc:
        try:
            error_detail = resp.json().get("detail")
        except Exception:
            error_detail = str(exc)
        st.error(f"Checkout error: {error_detail}")
    except requests.exceptions.RequestException as exc:
        st.error(f"Network error starting checkout: {exc}")


# -------------------------------------------------------------------
# Page UI
# -------------------------------------------------------------------

def main():
    st.set_page_config(page_title="Billing & Subscription", page_icon="💳")

    st.title("Billing & Subscription")

    st.write(
        """
Use this page to view your current plan and upgrade when you're ready.
After you subscribe, you can return to **Upload Data** to begin generating summaries.
"""
    )

    # Optional backend health check
    try:
        health_resp = requests.get(f"{BACKEND_URL}/health", timeout=5)
        if health_resp.status_code != 200:
            st.warning("Backend health check did not return 200 OK.")
    except requests.exceptions.RequestException:
        st.warning("Could not reach backend health endpoint. Billing may not work.")

    # Step 1 – email + coupon
    st.subheader("Step 1 – Enter your email")

    email = st.text_input(
        "Billing email (used to associate your subscription)",
        value=get_email(),
        key="billing_email_input",
        on_change=lambda: set_email(st.session_state.billing_email_input),
        placeholder="you@example.com",
    )

    coupon = st.text_input(
        "Coupon code (optional)",
        value=get_coupon(),
        key="billing_coupon_input",
        on_change=lambda: set_coupon(st.session_state.billing_coupon_input),
        placeholder="Enter coupon code if you have one",
    )

    # Step 2 – show current plan (if we have a valid email)
    current_plan_box = st.empty()
    status = fetch_subscription_status(email)
    with current_plan_box.container():
        if not email:
            st.info("Enter your email to see your current plan.")
        elif not status or status.get("plan") is None:
            st.info("No active subscription found for this email.")
        else:
            st.success(
                f"Current plan: **{status.get('plan').title()}** "
                f"(status: {status.get('status', 'unknown')})"
            )

    st.subheader("Step 2 – Compare plans & upgrade")

    cols = st.columns(3)
    for col, (plan_id, meta) in zip(cols, PLANS.items()):
        with col:
            st.markdown(f"### {meta['name']}")
            st.markdown(f"**{meta['price_display']}**")
            st.write("- " + meta["reports_per_month"])
            st.write("- " + meta["characters_per_month"])
            for feat in meta["features"]:
                st.write(f"- {feat}")

            if st.button(f"Choose {meta['name']}", key=f"choose_{plan_id}"):
                start_checkout(plan_id, email, coupon)

    st.caption(
        "You can upgrade later as your needs grow. "
        "All subscriptions are managed securely via Stripe."
    )


if __name__ == "__main__":
    main()
