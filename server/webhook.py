import os
import json
import logging
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

import stripe
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-report-backend")


def env(*names: str, required: bool = False) -> Optional[str]:
    for n in names:
        v = os.getenv(n)
        if v and str(v).strip():
            return str(v).strip()
    if required:
        raise RuntimeError(f"Missing required env var(s): {', '.join(names)}")
    return None


# ----------------------------
# Config
# ----------------------------
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", "STRIPE_API_KEY")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET")
FRONTEND_URL = env("FRONTEND_URL") or "http://localhost:8501"

STRIPE_PRICE_BASIC = env("STRIPE_PRICE_BASIC")
STRIPE_PRICE_PRO = env("STRIPE_PRICE_PRO")
STRIPE_PRICE_ENTERPRISE = env("STRIPE_PRICE_ENTERPRISE")

OPENAI_API_KEY = env("OPENAI_API_KEY")
BREVO_API_KEY = env("BREVO_API_KEY")
EMAIL_FROM = env("EMAIL_FROM")  # must be an email you configured/verified in Brevo

PLAN_TO_PRICE = {
    "basic": STRIPE_PRICE_BASIC,
    "pro": STRIPE_PRICE_PRO,
    "enterprise": STRIPE_PRICE_ENTERPRISE,
}

PRICE_TO_PLAN = {
    STRIPE_PRICE_BASIC: "basic",
    STRIPE_PRICE_PRO: "pro",
    STRIPE_PRICE_ENTERPRISE: "enterprise",
}

# Stripe setup
if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY
else:
    logger.warning("Stripe key not configured. Billing endpoints will fail.")


# ----------------------------
# FastAPI app
# ----------------------------
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*", FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"ok": True}


def require_stripe():
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Stripe is not configured")


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def find_customer_by_email(email: str):
    require_stripe()
    email = normalize_email(email)
    if not email:
        return None
    customers = stripe.Customer.list(email=email, limit=1)
    return customers.data[0] if customers and customers.data else None


def best_subscription_for_customer(customer_id: str):
    require_stripe()
    subs = stripe.Subscription.list(
        customer=customer_id,
        status="all",
        limit=10,
        expand=["data.items.data.price"],
    )
    if not subs or not subs.data:
        return None

    preferred = ["active", "trialing", "past_due", "unpaid", "incomplete", "canceled", "incomplete_expired"]
    subs_sorted = sorted(
        subs.data,
        key=lambda s: preferred.index(s.status) if s.status in preferred else 999
    )
    return subs_sorted[0]


def plan_from_subscription(sub) -> Optional[str]:
    try:
        if not sub or not sub.get("items") or not sub["items"].get("data"):
            return None
        item0 = sub["items"]["data"][0]
        price = item0.get("price")
        price_id = price.get("id") if isinstance(price, dict) else price
        return PRICE_TO_PLAN.get(price_id)
    except Exception:
        return None


@app.get("/subscription-status")
def subscription_status(email: str):
    """
    Returns:
      { status: "active|trialing|none|...", plan: "basic|pro|enterprise|None" }
    """
    require_stripe()
    email = normalize_email(email)
    if not email:
        return {"status": "none", "plan": None}

    cust = find_customer_by_email(email)
    if not cust:
        return {"status": "none", "plan": None}

    sub = best_subscription_for_customer(cust.id)
    if not sub:
        return {"status": "none", "plan": None}

    plan = plan_from_subscription(sub)

    return {
        "status": sub.status or "none",
        "plan": plan,
        "customer_id": cust.id,
        "subscription_id": sub.id,
    }


@app.post("/create-checkout-session")
async def create_checkout_session(payload: Dict[str, Any]):
    """
    Expects:
      { "email": "...", "plan": "basic|pro|enterprise" }
    Returns:
      { "url": "...stripe checkout..." }
    """
    require_stripe()

    email = normalize_email(payload.get("email", ""))
    plan = (payload.get("plan") or "").strip().lower()

    if not email:
        raise HTTPException(status_code=400, detail="email is required")
    if plan not in PLAN_TO_PRICE or not PLAN_TO_PRICE[plan]:
        raise HTTPException(status_code=400, detail=f"invalid plan: {plan}")

    price_id = PLAN_TO_PRICE[plan]

    cust = find_customer_by_email(email)
    if not cust:
        cust = stripe.Customer.create(email=email)

    success_url = f"{FRONTEND_URL}/Billing?status=success&session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{FRONTEND_URL}/Billing?status=cancel"

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=cust.id,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,

        # ✅ keeps coupon/promo code box visible on Stripe checkout
        allow_promotion_codes=True,
    )

    logger.info(f"Created checkout session {session.id} plan={plan} email={email}")
    return {"url": session.url, "session_id": session.id}


# ----------------------------
# Summary generation + email
# ----------------------------
def build_prompt(text: str, plan: str) -> str:
    plan = (plan or "basic").lower()
    if plan == "enterprise":
        return (
            "Create an enterprise-grade business summary with sections:\n"
            "1) Executive Summary\n2) Key Findings\n3) Risks\n4) Opportunities\n"
            "5) Recommended Actions (bulleted)\n6) Next Steps\n\n"
            f"Content:\n{text}"
        )
    if plan == "pro":
        return (
            "Create a professional business summary with:\n"
            "1) Summary\n2) Key Insights\n3) Action Items (bulleted)\n\n"
            f"Content:\n{text}"
        )
    return (
        "Create a concise summary (5-8 bullets max) and 3 action items.\n\n"
        f"Content:\n{text}"
    )


def generate_summary_text(text: str, plan: str) -> str:
    """
    Uses OpenAI if OPENAI_API_KEY is present.
    Falls back to a simple local summary if not.
    """
    if not OPENAI_API_KEY:
        # Safe fallback so app still works instead of failing
        trimmed = text.strip().replace("\n", " ")
        return (
            f"(Fallback summary — OPENAI_API_KEY not set)\n\n"
            f"{trimmed[:1200]}{'...' if len(trimmed) > 1200 else ''}"
        )

    # Using OpenAI Responses API via HTTPS (no SDK dependency)
    prompt = build_prompt(text, plan)

    try:
        r = requests.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4.1-mini",
                "input": prompt,
            },
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()

        # responses output_text extraction
        # (handles typical "output_text" convenience if present)
        out_text = data.get("output_text")
        if out_text:
            return out_text.strip()

        # fallback: try to assemble from content blocks
        parts = []
        for item in data.get("output", []):
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    parts.append(c.get("text", ""))
        return "\n".join([p for p in parts if p]).strip() or "(No summary returned)"
    except Exception as e:
        logger.exception("OpenAI summary generation failed")
        return f"(Summary generation failed) {e}"


def send_email_brevo(to_email: str, subject: str, html: str) -> bool:
    if not BREVO_API_KEY or not EMAIL_FROM:
        logger.warning("Brevo not configured (BREVO_API_KEY or EMAIL_FROM missing).")
        return False

    try:
        payload = {
            "sender": {"email": EMAIL_FROM},
            "to": [{"email": to_email}],
            "subject": subject,
            "htmlContent": html,
        }
        resp = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={
                "api-key": BREVO_API_KEY,
                "Content-Type": "application/json",
                "accept": "application/json",
            },
            data=json.dumps(payload),
            timeout=30,
        )
        if resp.status_code >= 200 and resp.status_code < 300:
            return True

        logger.error(f"Brevo send failed: {resp.status_code} {resp.text}")
        return False
    except Exception:
        logger.exception("Brevo send exception")
        return False


@app.post("/generate-summary")
async def generate_summary(request: Request):
    """
    Expects JSON:
      {
        "billing_email": "...",     # used to check subscription plan
        "text": "...",             # extracted text from doc or paste box
        "recipient_email": "...",  # email to send summary to
        "send_email": true/false
      }
    Returns:
      { ok, plan, status, summary, emailed }
    """
    body = await request.json()

    billing_email = normalize_email(body.get("billing_email", ""))
    text = (body.get("text") or "").strip()
    recipient_email = normalize_email(body.get("recipient_email", ""))
    send_email = bool(body.get("send_email", False))

    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    if not billing_email:
        raise HTTPException(status_code=400, detail="billing_email is required")

    # Determine plan from Stripe
    plan = "basic"
    status = "none"
    if STRIPE_SECRET_KEY:
        st = subscription_status(billing_email)
        status = st.get("status") or "none"
        plan = st.get("plan") or "basic"

    summary = generate_summary_text(text, plan)

    emailed = False
    if send_email:
        if not recipient_email:
            raise HTTPException(status_code=400, detail="recipient_email is required when send_email=true")

        subject = f"Your {plan.title()} Summary"
        html = f"""
        <div style="font-family: Arial, sans-serif;">
          <h2>{plan.title()} Summary</h2>
          <p><b>Billing email:</b> {billing_email}</p>
          <hr/>
          <pre style="white-space: pre-wrap; font-family: Arial, sans-serif;">{summary}</pre>
        </div>
        """
        emailed = send_email_brevo(recipient_email, subject, html)

    return {
        "ok": True,
        "status": status,
        "plan": plan,
        "summary": summary,
        "emailed": emailed,
        "recipient_email": recipient_email if send_email else None,
    }


# Optional webhook endpoint (not required for plan checks)
@app.post("/stripe-webhook")
async def stripe_webhook(request: Request):
    require_stripe()
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Stripe webhook secret not configured")

    payload = await request.body()
    sig = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    logger.info(f"Stripe webhook received: {event['type']}")
    return {"received": True}
