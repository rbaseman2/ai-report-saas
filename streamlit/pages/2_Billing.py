# streamlit/pages/2_Billing.py
import os
import time
import requests
import streamlit as st

# -----------------------------------------------------------------------------
# PAGE CONFIG
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Billing", page_icon="💳", layout="wide")

# -----------------------------------------------------------------------------
# YOUR BUSINESS SETTINGS (EDIT THESE)
# -----------------------------------------------------------------------------
BUSINESS_NAME = "AI Report"
SUPPORT_EMAIL = "support@yourdomain.com"
BILLING_EMAIL = "billing@yourdomain.com"
REFUND_WINDOW_DAYS = 14
ENTERPRISE_SLA = "99.9% monthly uptime"
TERMS_URL = "https://ai-report-saas.onrender.com/terms"
PRIVACY_URL = "https://ai-report-saas.onrender.com/privacy"

# -----------------------------------------------------------------------------
# BACKEND URL (prefer env var; fallback to secrets if present)
# -----------------------------------------------------------------------------
def _get_backend_url() -> str:
    url = os.getenv("BACKEND_URL", "").rstrip("/")
    if url:
        return url
    try:
        return st.secrets.get("backend_url", "").rstrip("/")
    except Exception:
        return ""

BACKEND_URL = _get_backend_url()

# -----------------------------------------------------------------------------
# HANDLE QUERY PARAMETERS (success/cancel, even if URL malformed)
# -----------------------------------------------------------------------------
qp = st.query_params
status_raw = qp.get("status", [""])[0]
session_id = qp.get("session_id", [""])[0]
status = status_raw.split("?")[0].split("&")[0].lower()

# -----------------------------------------------------------------------------
# BACKEND WAKE-UP HANDLER (Render free tier cold start)
# -----------------------------------------------------------------------------
def _wait_for_backend_up(base_url: str, max_wait_s: int = 75) -> bool:
    if not base_url:
        return False
    health = f"{base_url}/health"
    delays = [0.5, 1, 2, 4, 6, 8, 10, 12, 12, 12]
    start = time.time()
    for d in delays:
        try:
            r = requests.get(health, timeout=3)
            if r.ok:
                return True
        except requests.RequestException:
            pass
        time.sleep(d)
        if time.time() - start > max_wait_s:
            break
    return False

# -----------------------------------------------------------------------------
# STRIPE CHECKOUT + PORTAL ACTIONS
# -----------------------------------------------------------------------------
def start_checkout(plan_slug: str):
    if not BACKEND_URL:
        st.error("BACKEND_URL not configured for this Streamlit service.")
        return

    with st.spinner("Preparing secure checkout..."):
        if not _wait_for_backend_up(BACKEND_URL):
            st.error("Backend still waking up. Please try again in a few seconds.")
            return

    try:
        r = requests.post(
            f"{BACKEND_URL}/create-checkout-session",
            json={"plan": plan_slug},
            timeout=90,
        )
        if r.status_code == 200:
            url = (r.json() or {}).get("url")
            if not url:
                st.error("Backend did not return a checkout URL.")
                return
            st.success("Redirecting to Stripe Checkout…")
            st.markdown(
                f'<meta http-equiv="refresh" content="0; url={url}">'
                f'<p>If you are not redirected, <a href="{url}">click here</a>.</p>',
                unsafe_allow_html=True,
            )
        else:
            msg = (r.json().get("detail") if r.text else r.text) or "Unknown error"
            st.error(f"Checkout failed ({r.status_code}): {msg}")
    except requests.RequestException as e:
        st.error(f"Network error: {e}")

def open_portal(_session_id: str):
    if not BACKEND_URL:
        st.error("BACKEND_URL not configured for this Streamlit service.")
        return

    with st.spinner("Opening subscription portal…"):
        try:
            r = requests.post(
                f"{BACKEND_URL}/create-portal-session",
                json={"session_id": _session_id} if _session_id else {},
                timeout=30,
            )
        except requests.RequestException as e:
            st.error(f"Network error: {e}")
            return

        if r.status_code == 200:
            portal_url = (r.json() or {}).get("url")
            if portal_url:
                st.markdown(
                    f'<meta http-equiv="refresh" content="0; url={portal_url}">',
                    unsafe_allow_html=True,
                )
                st.write(f"[Open Subscription Portal]({portal_url})")
            else:
                st.error("Portal URL not returned by backend.")
        else:
            msg = (r.json().get("detail") if r.text else r.text) or "Unknown error"
            st.error(f"Portal open failed ({r.status_code}): {msg}")

# -----------------------------------------------------------------------------
# STYLE (simple but polished)
# -----------------------------------------------------------------------------
st.markdown(
    """
    <style>
      .block-container {padding-top: 1.2rem; padding-bottom: 3rem;}
      .pricing-grid {display: grid; grid-template-columns: repeat(3, 1fr); gap: 1.1rem;}
      @media (max-width: 1100px) {.pricing-grid {grid-template-columns: 1fr;}}
      .card {
          background: #0e1117;
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 16px;
          padding: 22px 20px;
          transition: transform .18s ease, box-shadow .18s ease, border .18s ease;
      }
      .card:hover {transform: translateY(-2px); box-shadow: 0 8px 28px rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.14);}
      .plan {font-size: 1.05rem; letter-spacing: .2px; opacity: .95;}
      .price {font-size: 2.05rem; font-weight: 700; margin: 6px 0 2px;}
      .period {font-size: .95rem; opacity: .75;}
      .blurb {opacity:.8; font-size:.95rem; margin-top: 4px;}
      .badge {
          display: inline-block; font-size: .75rem; font-weight: 600;
          padding: 4px 8px; border-radius: 999px; margin-left: 8px;
          background: linear-gradient(135deg,#22c55e33,#22c55e18); border: 1px solid #22c55e66; color: #22c55e;
      }
      .features {margin: 12px 0 0 18px;}
      .features li {margin: .32rem 0;}
      .divider {height:1px;background:rgba(255,255,255,.08);margin:14px 0;}
      .cta .stButton>button {width: 100%;}
      .caption {opacity:.6; font-size:.85rem; margin-top: 12px;}
    </style>
    """,
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# HEADER + STATUS
# -----------------------------------------------------------------------------
st.title("Choose a plan")
st.caption("Simple pricing, powerful AI reporting tools, and the flexibility to upgrade anytime.")

if status == "success" or session_id:
    st.success("✅ Payment successful — your subscription is now active.")
elif status == "cancelled":
    st.info("Checkout was cancelled. You can try again anytime.")

# -----------------------------------------------------------------------------
# FETCH PLANS FROM BACKEND (fallback defaults if offline)
# -----------------------------------------------------------------------------
plans = []
if BACKEND_URL:
    try:
        resp = requests.get(f"{BACKEND_URL}/plans", timeout=15)
        if resp.ok:
            plans = (resp.json() or {}).get("plans", [])
    except requests.RequestException:
        pass

if not plans:
    plans = [
        {
            "slug": "basic",
            "label": "Basic",
            "price": "$9.99",
            "desc": "Core features • Up to 3 reports/mo • Email support",
            "features": [
                "✅ Core AI features",
                "✅ Up to 3 reports/mo",
                "✅ Email support",
                "✅ Promotion codes accepted",
            ],
        },
        {
            "slug": "pro",
            "label": "Pro",
            "price": "$19.99",
            "desc": "Unlimited reports • Advanced analytics • Priority support",
            "features": [
                "✅ Everything in Basic",
                "✅ Unlimited reports",
                "✅ Advanced analytics",
                "✅ Priority support",
            ],
        },
        {
            "slug": "enterprise",
            "label": "Enterprise",
            "price": "$49.99",
            "desc": "Custom integrations • SLA uptime • Dedicated support",
            "features": [
                "✅ SSO & advanced controls",
                "✅ Dedicated support",
                f"✅ {ENTERPRISE_SLA} SLA",
                "✅ Custom onboarding",
            ],
        },
    ]

# -----------------------------------------------------------------------------
# PRICING CARDS
# -----------------------------------------------------------------------------
st.markdown('<div class="pricing-grid">', unsafe_allow_html=True)
for p in plans:
    st.markdown('<div class="card">', unsafe_allow_html=True)

    header = f'<span class="plan">{p.get("label","")}</span>'
    if p.get("badge"):
        header += f'<span class="badge">{p["badge"]}</span>'
    st.markdown(header, unsafe_allow_html=True)

    price = p.get("price", "")
    period = p.get("period", "per month") if price and "Contact" not in price else ""
    st.markdown(f'<div class="price">{price}</div>', unsafe_allow_html=True)
    if period:
        st.markdown(f'<div class="period">{period}</div>', unsafe_allow_html=True)
    if p.get("desc"):
        st.markdown(f'<div class="blurb">{p["desc"]}</div>', unsafe_allow_html=True)

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    feats = p.get("features", [])
    if feats:
        st.markdown('<ul class="features">', unsafe_allow_html=True)
        for f in feats:
            st.markdown(f"<li>{f}</li>", unsafe_allow_html=True)
        st.markdown("</ul>", unsafe_allow_html=True)

    st.markdown('<div class="cta">', unsafe_allow_html=True)
    if p.get("slug") == "enterprise":
        if st.button("Contact sales", key=f"cta_enterprise"):
            st.info(f"Email sales@{BUSINESS_NAME.lower().replace(' ','')}.com and we’ll tailor a plan for you.")
    else:
        if st.button(f"Choose {p.get('label','')}", key=f"cta_{p.get('slug','')}"):
            start_checkout(p.get("slug", "basic"))
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)

st.markdown("---")
st.caption(
    "💡 Promotion codes are accepted on the Stripe checkout page. Prices shown are in USD. "
    "You can upgrade, downgrade, or cancel anytime."
)

# -----------------------------------------------------------------------------
# MANAGE SUBSCRIPTION BUTTON (after success)
# -----------------------------------------------------------------------------
if status == "success" or session_id:
    st.button("Manage subscription", type="primary", on_click=open_portal, args=(session_id,))

# -----------------------------------------------------------------------------
# PRICING FAQ (policy-aligned)
# -----------------------------------------------------------------------------
st.subheader("Pricing FAQ")

with st.expander("Can I use a promotion code?"):
    st.write(
        "Yes. On the Stripe Checkout page, click **Add promotion code** and enter a valid code. "
        "For launches or testing, create codes in your Stripe Dashboard."
    )

with st.expander("What’s included in each plan?"):
    st.write(
        "- **Basic** — Core AI features, up to 3 reports per month, and standard email support.\n"
        "- **Pro** — Everything in Basic plus unlimited reports, advanced analytics, and priority support.\n"
        f"- **Enterprise** — Tailored for teams: SSO, advanced controls, dedicated support, {ENTERPRISE_SLA} SLA, and custom onboarding."
    )

with st.expander("How do upgrades or downgrades work?"):
    st.write(
        "You can change plans anytime from the **Manage subscription** button above (Stripe Billing Portal). "
        "Stripe automatically prorates the difference on your next invoice."
    )

with st.expander("Do you offer refunds?"):
    st.write(
        f"If {BUSINESS_NAME} isn’t the right fit, contact us within **{REFUND_WINDOW_DAYS} days** at "
        f"**{SUPPORT_EMAIL}**. We’ll review requests on a case-by-case basis per our Terms."
    )

with st.expander("Do you charge sales tax or VAT?"):
    st.write(
        "Taxes are calculated automatically in Checkout based on your billing address and local tax rules. "
        "You’ll see the exact amount before confirming payment."
    )

with st.expander("Can I get invoices or receipts for accounting?"):
    st.write(
        "Yes. Receipts are automatically emailed after payment. You can also download past invoices from "
        "the **Manage subscription** portal. For billing questions, contact "
        f"**{BILLING_EMAIL}**."
    )

with st.expander("Where can I read your Terms and Privacy Policy?"):
    st.write(
        f"• Terms of Service: {TERMS_URL}\n\n"
        f"• Privacy Policy: {PRIVACY_URL}"
    )

# -----------------------------------------------------------------------------
# FOOTER
# -----------------------------------------------------------------------------
if BACKEND_URL:
    st.caption(f"Using backend: {BACKEND_URL}")
