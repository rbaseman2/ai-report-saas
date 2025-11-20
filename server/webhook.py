"""
Backend for AI Report SaaS

Exposes:
- GET  /health
- POST /create-checkout-session
- POST /summarize
- POST /stripe-webhook

Designed to be tolerant of frontend JSON shapes and big inputs.
"""

import os
import json
import logging
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import stripe

# OpenAI (v1 client)
try:
    from openai import OpenAI  # type: ignore
except ImportError:  # if not installed, we fail gracefully at call time
    OpenAI = None  # type: ignore

# Optional DB helpers (your existing db.py). If not available, we just log.
try:
    from .db import get_db_connection  # type: ignore
except Exception:  # noqa: BLE001
    get_db_connection = None  # type: ignore


# -----------------------------------------------------------------------------
# Environment & configuration
# -----------------------------------------------------------------------------

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://ai-report-saas.onrender.com")

# Where Stripe should send the user after checkout
SUCCESS_URL = os.getenv(
    "SUCCESS_URL",
    f"{FRONTEND_URL}/Billing?status=success&session_id={{CHECKOUT_SESSION_ID}}",
)
CANCEL_URL = os.getenv(
    "CANCEL_URL",
    f"{FRONTEND_URL}/Billing?status=cancelled",
)

PRICE_BASIC = os.getenv("PRICE_BASIC")
PRICE_PRO = os.getenv("PRICE_PRO")
PRICE_ENTERPRISE = os.getenv("PRICE_ENTERPRISE")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

logger = logging.getLogger("webhook")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="AI Report Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # if you want to lock this down you can later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------

def get_price_id_for_plan(plan: str) -> str:
    """Map a logical plan name to a Stripe price ID from env."""
    plan_lower = plan.lower()
    if plan_lower in {"basic", "price_basic"} and PRICE_BASIC:
        return PRICE_BASIC
    if plan_lower in {"pro", "price_pro"} and PRICE_PRO:
        return PRICE_PRO
    if plan_lower in {"enterprise", "price_enterprise"} and PRICE_ENTERPRISE:
        return PRICE_ENTERPRISE

    # If caller passed a raw price ID, just return it.
    return plan


def make_openai_client():
    """Return an OpenAI client or raise a helpful error."""
    if OpenAI is None:
        raise HTTPException(
            status_code=500,
            detail="OpenAI client library is not installed on the backend.",
        )
    if not OPENAI_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY is not configured on the backend.",
        )
    # The v1 client reads the key from env by default
    return OpenAI()


def trim_text_for_tier(text: str, tier: str | None) -> str:
    """
    Trim the input text based on plan tier so we don't blow up tokens
    and time out.

    These numbers are conservative and can be tuned:
    - free / basic: ~15k chars
    - pro: ~35k chars
    - enterprise: ~60k chars
    """
    tier_lower = (tier or "").lower()

    if tier_lower in {"enterprise"}:
        max_chars = 60000
    elif tier_lower in {"pro"}:
        max_chars = 35000
    elif tier_lower in {"basic"}:
        max_chars = 15000
    else:
        # default / unknown tier
        max_chars = 15000

    if len(text) <= max_chars:
        return text

    logger.info("Trimming input from %d to %d characters", len(text), max_chars)
    return text[:max_chars]


def safe_get_body(request_json: Dict[str, Any], key: str, default: Any = None) -> Any:
    """Helper for tolerant JSON handling."""
    if key in request_json:
        return request_json[key]
    # Also tolerate different casings / naming e.g. 'plan', 'Plan', 'price_id'
    for k, v in request_json.items():
        if k.lower() == key.lower():
            return v
    return default


# -----------------------------------------------------------------------------
# Models (lightweight, to stay flexible)
# -----------------------------------------------------------------------------

class SummarizeResponse(BaseModel):
    summary: str


class CheckoutSessionResponse(BaseModel):
    checkout_url: str


# -----------------------------------------------------------------------------
# Health endpoint
# -----------------------------------------------------------------------------

@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


# -----------------------------------------------------------------------------
# Checkout session creation
# -----------------------------------------------------------------------------

@app.post("/create-checkout-session", response_model=CheckoutSessionResponse)
async def create_checkout_session(request: Request) -> CheckoutSessionResponse:
    """
    Create a Stripe Checkout session.

    Expects JSON with at least:
    - 'plan' OR 'price_id' (e.g. 'basic', 'pro', 'enterprise' OR a direct price id)
    Optional:
    - 'email' to prefill customer_email
    """
    if not STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=500,
            detail="Stripe secret key is not configured on the backend.",
        )

    try:
        payload = await request.json()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to parse JSON for checkout session")
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")

    logger.info("Received request for checkout session: %s", payload)

    # Tolerant extraction of values
    plan = safe_get_body(payload, "plan") or safe_get_body(payload, "price_id")
    email = safe_get_body(payload, "email") or safe_get_body(payload, "customer_email")

    if not plan:
        raise HTTPException(
            status_code=400,
            detail="Missing 'plan' or 'price_id' in request body.",
        )

    price_id = get_price_id_for_plan(str(plan))

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[
                {
                    "price": price_id,
                    "quantity": 1,
                }
            ],
            success_url=SUCCESS_URL,
            cancel_url=CANCEL_URL,
            customer_email=email,
            allow_promotion_codes=True,  # enables coupon / promo box
            metadata={
                "app": "ai-report-saas",
                "plan": str(plan),
                "email": email or "",
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Stripe checkout session creation failed")
        raise HTTPException(
            status_code=500,
            detail=f"Stripe error while creating checkout session: {exc}",
        )

    if not getattr(session, "url", None):
        logger.error("Stripe session created without URL: %s", session)
        raise HTTPException(
            status_code=500,
            detail="Stripe did not return a checkout URL.",
        )

    return CheckoutSessionResponse(checkout_url=session.url)


# -----------------------------------------------------------------------------
# Summarization endpoint
# -----------------------------------------------------------------------------

@app.post("/summarize", response_model=SummarizeResponse)
async def summarize(request: Request) -> SummarizeResponse:
    """
    Summarize a long business document into a client-friendly summary.

    Expected JSON (we are tolerant to variations):
    - 'text' or 'content' (string)   -> required
    - 'tier' (e.g. 'basic', 'pro', 'enterprise') -> optional
    - 'email' or 'user_email'       -> optional, for logging/audit only
    - 'max_chars'                   -> optional override for trimming
    """
    try:
        payload: Dict[str, Any] = await request.json()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to parse JSON for summarization")
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")

    logger.info("Summarize request received with keys: %s", list(payload.keys()))

    raw_text = safe_get_body(payload, "text") or safe_get_body(payload, "content")
    if not raw_text or not isinstance(raw_text, str):
        raise HTTPException(
            status_code=400,
            detail="Request must include a 'text' field (string) to summarize.",
        )

    tier = safe_get_body(payload, "tier") or safe_get_body(payload, "plan") or "basic"
    email = safe_get_body(payload, "email") or safe_get_body(payload, "user_email")

    # Optional explicit max_chars from the frontend
    explicit_max_chars = safe_get_body(payload, "max_chars")
    if isinstance(explicit_max_chars, int) and explicit_max_chars > 0:
        trimmed_text = raw_text[:explicit_max_chars]
    else:
        trimmed_text = trim_text_for_tier(raw_text, tier)

    client = make_openai_client()

    system_prompt = (
        "You are an AI assistant that summarizes long business documents "
        "for non-technical clients and stakeholders.\n\n"
        "Goals:\n"
        "- Extract the key points, decisions, risks, and next steps.\n"
        "- Use clear, concise, professional language.\n"
        "- Avoid jargon where possible and briefly explain any necessary terms.\n"
        "- Write in bullet points or short paragraphs that can be pasted into "
        "an email, slide deck, or executive summary."
    )

    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        "Summarize the following document for a business client or "
                        "stakeholder. Focus on the most important insights, risks, "
                        "and recommended actions.\n\n"
                        f"{trimmed_text}"
                    ),
                },
            ],
            temperature=0.3,
            max_tokens=800,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("OpenAI summarization failed")
        raise HTTPException(
            status_code=500,
            detail=f"Error while calling OpenAI for summarization: {exc}",
        )

    try:
        summary_text = completion.choices[0].message.content.strip()
    except Exception:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail="OpenAI response did not contain a summary.",
        )

    logger.info(
        "Summary generated for tier=%s, email=%s, input_len=%d, output_len=%d",
        tier,
        email,
        len(trimmed_text),
        len(summary_text),
    )

    return SummarizeResponse(summary=summary_text)


# -----------------------------------------------------------------------------
# Stripe webhook
# -----------------------------------------------------------------------------

@app.post("/stripe-webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="stripe-signature"),
):
    """
    Handle Stripe webhooks for subscription lifecycle events.
    """
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=500,
            detail="STRIPE_WEBHOOK_SECRET is not configured on the backend.",
        )

    payload = await request.body()
    sig_header = stripe_signature

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to verify Stripe webhook")
        raise HTTPException(status_code=400, detail=f"Invalid payload: {exc}")

    event_type = event["type"]
    logger.info("Received Stripe event: %s", event_type)

    # You can expand / customize this logic as needed.
    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        customer_email = session.get("customer_details", {}).get("email") or session.get(
            "customer_email"
        )
        plan = session.get("metadata", {}).get("plan")
        logger.info(
            "Checkout session completed: email=%s, plan=%s, session_id=%s",
            customer_email,
            plan,
            session.get("id"),
        )
        # Optional: persist to DB
        if get_db_connection:
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO subscriptions (email, plan, status)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (email) DO UPDATE
                    SET plan = EXCLUDED.plan,
                        status = EXCLUDED.status,
                        updated_at = NOW()
                    """,
                    (customer_email, plan, "active"),
                )
                conn.commit()
                cur.close()
                conn.close()
            except Exception as exc:  # noqa: BLE001
                logger.exception("DB error while updating subscription: %s", exc)

    elif event_type in {"customer.subscription.updated", "customer.subscription.deleted"}:
        sub = event["data"]["object"]
        status = sub.get("status")
        customer_email = (sub.get("metadata") or {}).get("email")
        logger.info(
            "Subscription changed: email=%s, status=%s, id=%s",
            customer_email,
            status,
            sub.get("id"),
        )
        if get_db_connection and customer_email:
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO subscriptions (email, plan, status)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (email) DO UPDATE
                    SET status = EXCLUDED.status,
                        updated_at = NOW()
                    """,
                    (customer_email, None, status),
                )
                conn.commit()
                cur.close()
                conn.close()
            except Exception as exc:  # noqa: BLE001
                logger.exception("DB error while updating subscription status: %s", exc)

    # You can add more event_type handlers here if needed.

    return {"received": True}
