"""
FastAPI backend for AI Report SaaS (DB optional)

Endpoints
---------
GET  /health                     -> simple health check
POST /summarize                  -> generate business-friendly summary
POST /create-checkout-session    -> create Stripe Checkout session (plan -> price_id)
POST /stripe/webhook             -> handle Stripe webhooks

Environment variables expected
------------------------------
STRIPE_SECRET_KEY
STRIPE_WEBHOOK_SECRET
PRICE_BASIC
PRICE_PRO
PRICE_ENTERPRISE
SUCCESS_URL          (frontend URL to return after checkout success)
CANCEL_URL           (optional; fallback is FRONTEND_URL + "/Billing")
FRONTEND_URL         (ex: "https://ai-report-saas.onrender.com")
DATABASE_URL         (optional; if missing or psycopg2 missing, DB is disabled)
OPENAI_API_KEY
"""

import json
import os
import logging
from datetime import datetime
from typing import Optional, Literal

import stripe
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from openai import OpenAI

# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------

logger = logging.getLogger("webhook")
logging.basicConfig(level=logging.INFO)

# ----------------------------------------------------------------------
# Optional DB import (psycopg2 may not support Python 3.13 on Render)
# ----------------------------------------------------------------------

HAS_DB = True
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except Exception as exc:  # ImportError or binary ABI error
    HAS_DB = False
    psycopg2 = None
    RealDictCursor = None
    logger.warning(
        "psycopg2 is not available or incompatible (%s). "
        "Subscription DB persistence will be disabled.",
        exc,
    )

# ----------------------------------------------------------------------
# Environment & third-party clients
# ----------------------------------------------------------------------

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
PRICE_BASIC = os.getenv("PRICE_BASIC")
PRICE_PRO = os.getenv("PRICE_PRO")
PRICE_ENTERPRISE = os.getenv("PRICE_ENTERPRISE")
SUCCESS_URL = os.getenv("SUCCESS_URL")
CANCEL_URL = os.getenv("CANCEL_URL")
FRONTEND_URL = os.getenv("FRONTEND_URL", "").rstrip("/")
DATABASE_URL = os.getenv("DATABASE_URL")

if not STRIPE_SECRET_KEY:
    logger.warning("STRIPE_SECRET_KEY is not set")
if not STRIPE_WEBHOOK_SECRET:
    logger.warning("STRIPE_WEBHOOK_SECRET is not set")
if not DATABASE_URL:
    logger.warning("DATABASE_URL is not set (DB persistence disabled)")
if not SUCCESS_URL:
    logger.warning("SUCCESS_URL is not set – checkout success redirect may fail.")

stripe.api_key = STRIPE_SECRET_KEY

# OpenAI client (uses OPENAI_API_KEY env var)
openai_client = OpenAI()

# ----------------------------------------------------------------------
# Database helpers (no-op if HAS_DB is False)
# ----------------------------------------------------------------------


def db_enabled() -> bool:
    return HAS_DB and bool(DATABASE_URL)


def get_db_connection():
    """
    Open a new database connection.

    If DB is not enabled, this raises RuntimeError and callers should
    treat that as "no persistence available".
    """
    if not db_enabled():
        raise RuntimeError("Database is not enabled (no psycopg2 or no DATABASE_URL)")
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def init_db():
    """
    Ensure a minimal subscriptions table exists.

    This is idempotent and safe to run on startup.
    If DB is not enabled, this is a no-op.
    """
    if not db_enabled():
        logger.info("init_db: DB disabled; skipping table creation.")
        return

    try:
        conn = get_db_connection()
    except Exception as exc:
        logger.error(f"init_db: could not connect to DB: {exc}")
        return

    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS subscriptions (
                    email                   TEXT PRIMARY KEY,
                    stripe_customer_id      TEXT,
                    stripe_subscription_id  TEXT,
                    plan                    TEXT,
                    status                  TEXT,
                    created_at              TIMESTAMPTZ DEFAULT NOW(),
                    updated_at              TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )
        logger.info("init_db: subscriptions table ensured.")
    finally:
        conn.close()


def upsert_subscription(
    email: Optional[str],
    stripe_customer_id: Optional[str],
    stripe_subscription_id: Optional[str],
    plan: Optional[str],
    status: str,
) -> None:
    """
    Insert or update a subscription row.

    If DB is disabled or email missing, this becomes a no-op.
    """
    if not db_enabled():
        logger.info(
            "upsert_subscription called but DB disabled; "
            "email=%s status=%s plan=%s",
            email,
            status,
            plan,
        )
        return

    if not email:
        logger.warning("upsert_subscription: email is required but missing.")
        return

    conn = get_db_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO subscriptions (
                    email, stripe_customer_id, stripe_subscription_id, plan, status
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (email) DO UPDATE
                SET stripe_customer_id = EXCLUDED.stripe_customer_id,
                    stripe_subscription_id = EXCLUDED.stripe_subscription_id,
                    plan = EXCLUDED.plan,
                    status = EXCLUDED.status,
                    updated_at = NOW();
                """,
                (email, stripe_customer_id, stripe_subscription_id, plan, status),
            )
    finally:
        conn.close()


def get_subscription(email: str) -> Optional[dict]:
    """
    Fetch subscription info for a given email.

    If DB is disabled, always returns None.
    """
    if not db_enabled():
        return None

    conn = get_db_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM subscriptions WHERE email = %s;",
                (email,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


# ----------------------------------------------------------------------
# FastAPI app
# ----------------------------------------------------------------------

app = FastAPI(title="AI Report Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Streamlit is on a different origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_event():
    logger.info("Starting up backend...")
    init_db()
    logger.info("Database init complete (or skipped if disabled).")


# ----------------------------------------------------------------------
# Pydantic models
# ----------------------------------------------------------------------


class SummarizeRequest(BaseModel):
    text: str
    email: Optional[EmailStr] = None
    tier: Optional[Literal["free", "basic", "pro", "enterprise"]] = "free"


class SummarizeResponse(BaseModel):
    summary: str
    truncated: bool = False
    tier: str


class CheckoutRequest(BaseModel):
    # plan slug from frontend: "basic" | "pro" | "enterprise"
    plan: Literal["basic", "pro", "enterprise"]
    email: EmailStr


class CheckoutResponse(BaseModel):
    checkout_url: str


# ----------------------------------------------------------------------
# Health check
# ----------------------------------------------------------------------


@app.get("/health")
def health():
    return {
        "status": "ok",
        "time": datetime.utcnow().isoformat() + "Z",
        "db_enabled": db_enabled(),
    }


# ----------------------------------------------------------------------
# Summarization endpoint (business oriented)
# ----------------------------------------------------------------------

MAX_CHARS_FREE = 4000
MAX_CHARS_BASIC = 20000
MAX_CHARS_PRO = 60000
MAX_CHARS_ENTERPRISE = 120000


def _tier_limits(tier: str) -> int:
    tier = (tier or "free").lower()
    if tier == "basic":
        return MAX_CHARS_BASIC
    if tier == "pro":
        return MAX_CHARS_PRO
    if tier == "enterprise":
        return MAX_CHARS_ENTERPRISE
    return MAX_CHARS_FREE


@app.post("/summarize", response_model=SummarizeResponse)
def summarize(req: SummarizeRequest):
    """
    Convert a long report / document into a clear, business-friendly summary.
    """

    tier = (req.tier or "free").lower()
    limit = _tier_limits(tier)

    text = req.text or ""
    truncated = False
    if len(text) > limit:
        text = text[:limit]
        truncated = True

    # Business-oriented prompt
    system_prompt = (
        "You are an expert business analyst and communication specialist. "
        "Given a long business document, report, or set of notes, you produce a "
        "clear, well-structured summary that a non-technical client, executive, "
        "or business stakeholder can quickly understand.\n\n"
        "Rules:\n"
        "• Focus on the most important insights, risks, decisions, and next steps.\n"
        "• Use concise, plain language (no medical or highly technical jargon).\n"
        "• Organize the output with headings and bullet points when helpful.\n"
        "• Make it easy to copy into an email, slide deck, or meeting notes.\n"
        "• If information is missing or unclear, do NOT invent facts; just note it.\n"
    )

    user_prompt = (
        "Summarize the following content for a business audience.\n\n"
        "Goals:\n"
        "1) Capture key insights and takeaways.\n"
        "2) Highlight major risks or issues.\n"
        "3) Call out recommended actions or next steps.\n\n"
        "Content to summarize:\n"
        "---------------------\n"
        f"{text}\n"
        "---------------------\n"
    )

    try:
        completion = openai_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
        )
        summary_text = completion.choices[0].message.content.strip()
    except Exception as exc:
        logger.error(f"/summarize OpenAI error: {exc}")
        raise HTTPException(status_code=500, detail="Failed to generate summary.")

    return SummarizeResponse(summary=summary_text, truncated=truncated, tier=tier)


# ----------------------------------------------------------------------
# Stripe: create Checkout session (plan -> price)
# ----------------------------------------------------------------------


def _plan_to_price(plan: str) -> str:
    """Map plan slug to Stripe price ID using env vars."""
    plan = plan.lower()
    mapping = {
        "basic": PRICE_BASIC,
        "pro": PRICE_PRO,
        "enterprise": PRICE_ENTERPRISE,
    }
    price_id = mapping.get(plan)
    if not price_id:
        raise HTTPException(status_code=400, detail=f"Unknown or unconfigured plan: {plan}")
    return price_id


@app.post("/create-checkout-session", response_model=CheckoutResponse)
def create_checkout_session(payload: CheckoutRequest):
    """
    Create a Stripe Checkout session for a subscription plan.

    The frontend should POST:
    {
        "plan": "basic" | "pro" | "enterprise",
        "email": "user@example.com"
    }
    """

    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Stripe not configured.")

    price_id = _plan_to_price(payload.plan)

    success_url = SUCCESS_URL or f"{FRONTEND_URL}/Billing?status=success"
    cancel_url = CANCEL_URL or f"{FRONTEND_URL}/Billing?status=cancelled"

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            customer_email=payload.email,
            allow_promotion_codes=True,
            success_url=success_url + "&session_id={CHECKOUT_SESSION_ID}",
            cancel_url=cancel_url,
        )
    except Exception as exc:
        logger.error(f"Stripe checkout error: {exc}")
        raise HTTPException(status_code=500, detail="Failed to create checkout session.")

    logger.info(
        f"Created checkout session {session.id} for {payload.email} "
        f"plan {payload.plan} (price {price_id})"
    )
    return CheckoutResponse(checkout_url=session.url)


# ----------------------------------------------------------------------
# Stripe webhook
# ----------------------------------------------------------------------


@app.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    """
    Handle Stripe webhooks to keep local subscription table in sync.
    If DB is disabled, this still runs but only logs events.
    """
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Stripe webhook secret not set.")

    payload = await request.body()
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except stripe.error.SignatureVerificationError as exc:
        logger.error(f"Webhook signature verification failed: {exc}")
        raise HTTPException(status_code=400, detail="Invalid signature.")
    except Exception as exc:
        logger.error(f"Webhook construct_event error: {exc}")
        raise HTTPException(status_code=400, detail="Invalid payload.")

    event_type = event["type"]
    logger.info(f"Received Stripe event: {event_type}")

    try:
        if event_type == "checkout.session.completed":
            session = event["data"]["object"]

            email = session.get("customer_details", {}).get("email") or session.get(
                "customer_email"
            )
            customer_id = session.get("customer")
            subscription_id = session.get("subscription")
            # Assume only one line item with a price
            line_items = stripe.checkout.Session.list_line_items(session["id"], limit=1)
            price_id = None
            if line_items and line_items.data:
                price_id = line_items.data[0].price.id

            upsert_subscription(
                email=email,
                stripe_customer_id=customer_id,
                stripe_subscription_id=subscription_id,
                plan=price_id,
                status="active",
            )
            logger.info(f"checkout.session.completed stored/logged for {email}")

        elif event_type in ("customer.subscription.updated", "customer.subscription.deleted"):
            sub = event["data"]["object"]
            customer_id = sub.get("customer")
            subscription_id = sub.get("id")
            status = sub.get("status", "unknown")

            email = sub.get("metadata", {}).get("email")

            if not email and db_enabled() and customer_id:
                # Fallback: look up any existing row with this customer_id
                conn = get_db_connection()
                try:
                    with conn, conn.cursor() as cur:
                        cur.execute(
                            "SELECT email FROM subscriptions WHERE stripe_customer_id = %s;",
                            (customer_id,),
                        )
                        row = cur.fetchone()
                        if row:
                            email = row["email"]
                finally:
                    conn.close()

            upsert_subscription(
                email=email,
                stripe_customer_id=customer_id,
                stripe_subscription_id=subscription_id,
                plan=None,
                status=status,
            )
            logger.info(
                f"Subscription {subscription_id} for {email} updated to status {status}"
            )

        else:
            logger.info(f"Unhandled Stripe event type: {event_type}")

    except Exception as exc:
        logger.error(f"Error processing Stripe webhook event {event_type}: {exc}")

    return {"received": True}
