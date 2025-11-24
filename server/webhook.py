"""
FastAPI backend for AI Report SaaS

Endpoints:
- GET  /health                     -> simple health check
- POST /summarize                  -> generate business-style summary with OpenAI
- POST /create-checkout-session    -> create Stripe Checkout session for subscription
- POST /stripe/webhook             -> handle Stripe webhook events
- GET  /subscription-status        -> return stored plan for a given email

Storage:
- Very simple JSON file (subscriptions.json) in the same folder as this file.
  This avoids psycopg2 / Postgres issues on Render.
"""

import json
import os
from pathlib import Path
from typing import Dict, Literal, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
import stripe

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # app will raise a clear error if summarization is used


# -----------------------------
# Config
# -----------------------------

# Stripe config from environment
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")

# Support BOTH old and new price ID env names
STRIPE_BASIC_PRICE_ID = os.getenv("STRIPE_BASIC_PRICE_ID") or os.getenv("PRICE_BASIC")
STRIPE_PRO_PRICE_ID = os.getenv("STRIPE_PRO_PRICE_ID") or os.getenv("PRICE_PRO")
STRIPE_ENTERPRISE_PRICE_ID = (
    os.getenv("STRIPE_ENTERPRISE_PRICE_ID") or os.getenv("PRICE_ENTERPRISE")
)

STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# Frontend URLs (used for Checkout success/cancel)
FRONTEND_BILLING_URL = os.getenv(
    "FRONTEND_BILLING_URL",
    "https://ai-report-saas.onrender.com/Billing",
)
FRONTEND_UPLOAD_URL = os.getenv(
    "FRONTEND_UPLOAD_URL",
    "https://ai-report-saas.onrender.com/Upload_Data",
)

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Simple JSON file for subscription storage
BASE_DIR = Path(__file__).resolve().parent
SUBSCRIPTIONS_FILE = BASE_DIR / "subscriptions.json"


def _load_subscriptions() -> Dict[str, Dict]:
    if not SUBSCRIPTIONS_FILE.exists():
        return {}
    try:
        return json.loads(SUBSCRIPTIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_subscriptions(data: Dict[str, Dict]) -> None:
    SUBSCRIPTIONS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _set_subscription(email: str, plan: str, status: str) -> None:
    email = email.lower().strip()
    subs = _load_subscriptions()
    subs[email] = {"plan": plan, "status": status}
    _save_subscriptions(subs)


def _get_subscription(email: str) -> Dict[str, str]:
    email = email.lower().strip()
    subs = _load_subscriptions()
    return subs.get(email, {"plan": "free", "status": "none"})


# Configure Stripe client (only if key present)
if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

# Configure OpenAI client
client: Optional["OpenAI"] = None
if OPENAI_API_KEY and OpenAI is not None:
    client = OpenAI(api_key=OPENAI_API_KEY)

# -----------------------------
# FastAPI app
# -----------------------------

app = FastAPI(title="AI Report SaaS backend")

# Allow CORS from anywhere (safe enough for this small app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------
# Pydantic models
# -----------------------------

class SummarizeRequest(BaseModel):
    text: str
    email: Optional[EmailStr] = None
    plan: Optional[str] = "free"


class SummarizeResponse(BaseModel):
    summary: str


PlanSlug = Literal["basic", "pro", "enterprise"]


class CheckoutRequest(BaseModel):
    plan: PlanSlug
    email: EmailStr


class CheckoutResponse(BaseModel):
    checkout_url: str


# -----------------------------
# Helpers
# -----------------------------

def _map_plan_to_price_id(plan: PlanSlug) -> str:
    if plan == "basic":
        pid = STRIPE_BASIC_PRICE_ID
    elif plan == "pro":
        pid = STRIPE_PRO_PRICE_ID
    else:
        pid = STRIPE_ENTERPRISE_PRICE_ID

    if not pid:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Stripe price ID not configured for plan '{plan}'. "
                f"Set STRIPE_{plan.upper()}_PRICE_ID (or PRICE_{plan.upper()}) "
                f"in the environment."
            ),
        )
    return pid


def _ensure_stripe_configured():
    if not STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=500,
            detail="Stripe is not configured. Set STRIPE_SECRET_KEY in the environment.",
        )


def _ensure_openai_configured():
    if client is None:
        raise HTTPException(
            status_code=500,
            detail=(
                "OpenAI is not configured. Set OPENAI_API_KEY in the environment "
                "and ensure the 'openai' Python package is installed."
            ),
        )


# -----------------------------
# Routes
# -----------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/summarize", response_model=SummarizeResponse)
async def summarize(req: SummarizeRequest):
    """
    Take raw text and return a business-oriented summary.
    """
    _ensure_openai_configured()

    raw_text = req.text.strip()
    if not raw_text:
        raise HTTPException(status_code=400, detail="Text is empty.")

    # Very large docs: trim to something manageable
    max_chars = 16000 if (req.plan or "free") != "free" else 8000
    text = raw_text[:max_chars]

    # Business-oriented prompt
    system_prompt = (
        "You are an AI assistant that creates concise, business-friendly summaries. "
        "Your audience is non-technical clients, managers, or stakeholders. "
        "Summaries should be clear, structured, and easy to drop into an email or slide."
    )

    user_prompt = f"""
Summarize the following content for a business audience.

Write the output in this structure (using markdown):

**Title:** A short, descriptive title

**Key Insights (bullets):**
- 3–8 bullets capturing the main points, decisions, or conclusions.

**Risks / Considerations:**
- 2–6 bullets highlighting risks, dependencies, or open questions.

**Recommended Actions:**
- 3–8 concrete, action-oriented bullets (who should do what, and why).

Source content:
{text}
"""

    try:
        completion = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
        )
        summary_text = completion.choices[0].message.content.strip()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI error: {e}")

    return SummarizeResponse(summary=summary_text)


@app.post("/create-checkout-session", response_model=CheckoutResponse)
async def create_checkout_session(req: CheckoutRequest):
    """
    Create a Stripe Checkout session for a subscription plan.

    The frontend should POST JSON:
        {"plan": "basic" | "pro" | "enterprise", "email": "user@example.com"}
    """
    _ensure_stripe_configured()

    price_id = _map_plan_to_price_id(req.plan)

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            customer_email=req.email,
            line_items=[
                {
                    "price": price_id,
                    "quantity": 1,
                }
            ],
            allow_promotion_codes=True,
            success_url=f"{FRONTEND_BILLING_URL}?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{FRONTEND_BILLING_URL}?canceled=1",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stripe error: {e}")

    # Optimistically store plan as "pending" so status can change from "free"
    _set_subscription(req.email, req.plan, "pending")

    return CheckoutResponse(checkout_url=session.url)


@app.get("/subscription-status")
async def subscription_status(email: EmailStr):
    """
    Return stored subscription info for an email.
    This is intentionally simple and backed by a JSON file.
    """
    info = _get_subscription(str(email))
    return info


@app.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    """
    Handle Stripe webhook events.

    Make sure STRIPE_WEBHOOK_SECRET is set in the environment and that
    your Stripe dashboard is configured to send events to:
        https://your-backend-url/stripe/webhook
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not STRIPE_WEBHOOK_SECRET:
        # If not configured, just log and return 200 so Stripe stops retrying.
        return {"status": "webhook secret not configured, event ignored"}

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Webhook error: {e}")

    event_type = event["type"]

    # Handle a few key subscription events
    if event_type == "checkout.session.completed":
        session_obj = event["data"]["object"]
        email = session_obj.get("customer_details", {}).get("email")
        # We don't get the plan here directly, but if we already saved "pending",
        # just mark it active.
        if email:
            info = _get_subscription(email)
            plan = info.get("plan", "basic")  # default to basic if not present
            _set_subscription(email, plan, "active")

    elif event_type in ("customer.subscription.updated", "customer.subscription.created"):
        sub = event["data"]["object"]
        email = None
        if sub.get("customer"):
            # Try to look up the customer and their email
            try:
                customer = stripe.Customer.retrieve(sub["customer"])
                email = customer.get("email")
            except Exception:
                pass

        if email:
            status = sub.get("status", "active")
            # We won't try to derive the exact plan name here; keep existing.
            existing = _get_subscription(email)
            plan = existing.get("plan", "basic")
            _set_subscription(email, plan, status)

    elif event_type == "customer.subscription.deleted":
        sub = event["data"]["object"]
        email = None
        if sub.get("customer"):
            try:
                customer = stripe.Customer.retrieve(sub["customer"])
                email = customer.get("email")
            except Exception:
                pass

        if email:
            _set_subscription(email, "free", "canceled")

    # For any events we don't explicitly handle:
    return {"status": "success"}
