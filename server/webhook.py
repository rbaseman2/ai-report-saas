"""
server/webhook.py
FastAPI backend for:
- Stripe checkout session creation (supports promo/coupon codes)
- Stripe webhook handler to keep subscription status accurate
- Subscription status lookup by email
- Summary generation endpoint (stub / hook point)
- Email sending helper (Brevo / Sendinblue API v3)

Notes:
- This file is designed to be drop-in and **not** break existing behavior:
  - Keeps /create-checkout-session, /subscription-status, /generate-summary, /webhook, /health
  - Returns both checkout_url and url for frontend compatibility
  - Keeps coupon box via allow_promotion_codes=True
"""

from __future__ import annotations

import os
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import stripe
import requests
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field

logger = logging.getLogger("ai-report-backend")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI()

# -------------------------------
# CORS (keep permissive while you iterate)
# -------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------
# Environment
# -------------------------------
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()

# Stripe Price IDs per plan (set these in Render + local env)
STRIPE_PRICE_BASIC = os.getenv("STRIPE_PRICE_BASIC", "").strip()
STRIPE_PRICE_PRO = os.getenv("STRIPE_PRICE_PRO", "").strip()
STRIPE_PRICE_ENTERPRISE = os.getenv("STRIPE_PRICE_ENTERPRISE", "").strip()

# URLs used by Checkout
FRONTEND_URL = os.getenv("FRONTEND_URL", "").strip() or "http://localhost:8501"
SUCCESS_URL = os.getenv("STRIPE_SUCCESS_URL", "").strip() or f"{FRONTEND_URL}/?checkout=success"
CANCEL_URL = os.getenv("STRIPE_CANCEL_URL", "").strip() or f"{FRONTEND_URL}/?checkout=cancel"

# Brevo (Sendinblue) transactional email
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "").strip()
BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL", "").strip() or "admin@robaisolutions.com"
BREVO_SENDER_NAME = os.getenv("BREVO_SENDER_NAME", "").strip() or "Rob AI Solutions"

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

# Plan normalization: accept a few aliases to prevent "Invalid plan" surprises
PLAN_ALIASES = {
    "starter": "basic",
    "free": "basic",
    "basic": "basic",
    "pro": "pro",
    "professional": "pro",
    "premium": "pro",
    "enterprise": "enterprise",
    "ent": "enterprise",
}

PLAN_TO_PRICE = {
    "basic": STRIPE_PRICE_BASIC,
    "pro": STRIPE_PRICE_PRO,
    "enterprise": STRIPE_PRICE_ENTERPRISE,
}

# In-memory upload index (id -> path). For production, persist in Postgres.
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/tmp/uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
UPLOAD_INDEX: Dict[str, Dict[str, Any]] = {}


# -------------------------------
# Pydantic models
# -------------------------------
class CreateCheckoutSessionRequest(BaseModel):
    email: EmailStr
    plan: str = Field(..., description="basic | pro | enterprise")


class CreateCheckoutSessionResponse(BaseModel):
    checkout_url: str
    url: str
    session_id: str


class SubscriptionStatusResponse(BaseModel):
    email: EmailStr
    has_customer: bool
    has_active_subscription: bool
    current_plan: Optional[str] = None
    current_plan_for_summaries: Optional[str] = None
    subscription_status: Optional[str] = None
    current_period_end: Optional[int] = None  # unix timestamp
    updated_at_utc: str


class GenerateSummaryRequest(BaseModel):
    upload_id: Optional[str] = None
    # Keep this simple + JSON-friendly. Your Streamlit uploader can POST JSON or multipart.
    email: EmailStr
    plan: Optional[str] = None
    recipient_email: Optional[EmailStr] = None
    # anything else your frontend sends can be added later


# -------------------------------
# Helpers
# -------------------------------
def _require_stripe_config() -> None:
    if not STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=500,
            detail="STRIPE_SECRET_KEY is not set in environment variables.",
        )


def normalize_plan(plan: str) -> str:
    key = (plan or "").strip().lower()
    return PLAN_ALIASES.get(key, key)


def resolve_price_id(plan: str) -> str:
    plan_key = normalize_plan(plan)
    if plan_key not in PLAN_TO_PRICE:
        raise HTTPException(status_code=400, detail="Invalid plan")
    price_id = PLAN_TO_PRICE.get(plan_key, "").strip()
    if not price_id:
        raise HTTPException(
            status_code=500,
            detail=f"Missing Stripe price id env var for plan '{plan_key}'. "
                   f"Set STRIPE_PRICE_{plan_key.upper()} in your environment.",
        )
    return price_id


def send_email_brevo(
    *,
    to_email: str,
    subject: str,
    html_content: str,
    text_content: Optional[str] = None,
) -> None:
    """
    Minimal transactional email sender using Brevo API v3.
    Requires BREVO_API_KEY and optional BREVO_SENDER_EMAIL / BREVO_SENDER_NAME.
    """
    if not BREVO_API_KEY:
        raise HTTPException(status_code=500, detail="BREVO_API_KEY is not set.")

    payload: Dict[str, Any] = {
        "sender": {"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_EMAIL},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_content,
    }
    if text_content:
        payload["textContent"] = text_content

    resp = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={
            "accept": "application/json",
            "content-type": "application/json",
            "api-key": BREVO_API_KEY,
        },
        data=json.dumps(payload),
        timeout=30,
    )
    if resp.status_code >= 300:
        logger.error("Brevo send failed: %s %s", resp.status_code, resp.text)
        raise HTTPException(status_code=500, detail="Email send failed")


# -------------------------------
# Routes
# -------------------------------
@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/create-checkout-session", response_model=CreateCheckoutSessionResponse)
def create_checkout_session(payload: CreateCheckoutSessionRequest) -> CreateCheckoutSessionResponse:
    _require_stripe_config()

    plan_key = normalize_plan(payload.plan)
    price_id = resolve_price_id(plan_key)

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer_email=str(payload.email),
            line_items=[{"price": price_id, "quantity": 1}],
            allow_promotion_codes=True,  # <-- keeps coupon/promo box in Stripe Checkout
            success_url=SUCCESS_URL + "&session_id={CHECKOUT_SESSION_ID}",
            cancel_url=CANCEL_URL,
        )
        checkout_url = session.url
        logger.info("Created checkout session %s for %s (%s)", session.id, payload.email, plan_key)
        return CreateCheckoutSessionResponse(checkout_url=checkout_url, url=checkout_url, session_id=session.id)
    except stripe.error.StripeError as e:
        logger.exception("Stripe error creating checkout session")
        raise HTTPException(status_code=500, detail=str(e.user_message or str(e)))


@app.get("/subscription-status", response_model=SubscriptionStatusResponse)
def subscription_status(email: EmailStr) -> SubscriptionStatusResponse:
    _require_stripe_config()

    # Default response (no customer)
    now = datetime.now(timezone.utc).isoformat()
    try:
        customers = stripe.Customer.list(email=str(email), limit=1)
        if not customers.data:
            return SubscriptionStatusResponse(
                email=email,
                has_customer=False,
                has_active_subscription=False,
                updated_at_utc=now,
            )

        customer_id = customers.data[0].id

        # expand price so we can infer plan from price id
        subs = stripe.Subscription.list(
            customer=customer_id,
            status="all",
            limit=10,
            expand=["data.items.data.price"],
        )

        # pick the "best" subscription: active/trialing first, else latest by created
        chosen = None
        for s in subs.data:
            if s.status in ("active", "trialing"):
                chosen = s
                break
        if not chosen and subs.data:
            chosen = sorted(subs.data, key=lambda x: int(getattr(x, "created", 0)), reverse=True)[0]

        if not chosen:
            return SubscriptionStatusResponse(
                email=email,
                has_customer=True,
                has_active_subscription=False,
                updated_at_utc=now,
            )

        # Determine plan by matching the subscription's price id to our env mapping
        price_in_sub = None
        try:
            price_in_sub = chosen["items"]["data"][0]["price"]["id"]
        except Exception:
            price_in_sub = None

        current_plan = None
        if price_in_sub:
            for k, v in PLAN_TO_PRICE.items():
                if v and v == price_in_sub:
                    current_plan = k
                    break

        has_active = chosen.status in ("active", "trialing")
        current_period_end = getattr(chosen, "current_period_end", None)

        return SubscriptionStatusResponse(
            email=email,
            has_customer=True,
            has_active_subscription=has_active,
            current_plan=current_plan,
            current_plan_for_summaries=(current_plan if has_active else None),
            subscription_status=chosen.status,
            current_period_end=int(current_period_end) if current_period_end else None,
            updated_at_utc=now,
        )
    except stripe.error.StripeError as e:
        logger.exception("Stripe error looking up subscription status")
        raise HTTPException(status_code=500, detail=str(e.user_message or str(e)))


@app.post("/webhook")
async def stripe_webhook(request: Request) -> Dict[str, Any]:
    """
    Stripe webhook endpoint. IMPORTANT:
    - In Stripe dashboard, set your webhook URL to:
        https://<your-render-backend>/webhook
    - And set STRIPE_WEBHOOK_SECRET in Render.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not STRIPE_WEBHOOK_SECRET:
        # Don't hard-fail local dev if you haven't configured the secret
        logger.warning("STRIPE_WEBHOOK_SECRET not set; skipping signature verification.")
        return {"received": True, "verified": False}

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Minimal handling: log events that matter
    event_type = event["type"]
    logger.info("Stripe webhook received: %s", event_type)

    # You can expand this to persist to Postgres if/when you want.
    # Examples:
    # - checkout.session.completed
    # - customer.subscription.created/updated/deleted

    return {"received": True, "type": event_type}



@app.post("/upload")
async def upload_file(file: UploadFile = File(...), email: Optional[str] = Form(default=None)) -> Dict[str, Any]:
    """
    Accepts multipart/form-data file upload. Returns an upload_id.
    Billing/summary generation should pass upload_id in JSON to /generate-summary.
    """
    # Read bytes safely
    data = await file.read()
    upload_id = uuid.uuid4().hex
    ext = os.path.splitext(file.filename or "")[1].lower() or ".bin"
    path = os.path.join(UPLOAD_DIR, f"{upload_id}{ext}")
    with open(path, "wb") as f:
        f.write(data)

    UPLOAD_INDEX[upload_id] = {
        "path": path,
        "filename": file.filename,
        "content_type": file.content_type,
        "email": email,
        "size": len(data),
        "uploaded_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    logger.info("Uploaded file %s (%s bytes) -> %s", file.filename, len(data), upload_id)
    return {"upload_id": upload_id, "filename": file.filename, "size": len(data)}


@app.post("/generate-summary")
async def generate_summary(request: Request) -> Dict[str, Any]:
    """
    Keep this endpoint stable. Your Streamlit UI can send either:
    - JSON (application/json)
    - multipart/form-data (file upload)
    Here we safely handle JSON first; if it's not JSON, return a clear error.
    """
    content_type = request.headers.get("content-type", "")
    if "application/json" not in content_type:
        raise HTTPException(status_code=422, detail="Expected application/json for now. (multipart upload not wired here)")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Basic validation
    try:
        data = GenerateSummaryRequest(**body)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    # TODO: call OpenAI and produce summary based on stored upload / text.
    # For now, return a placeholder to keep your billing flow working.
    if data.upload_id and data.upload_id in UPLOAD_INDEX:
        meta = UPLOAD_INDEX[data.upload_id]
        summary_text = f"Summary generated for {data.email} using '{meta.get('filename')}' (plan={data.plan or 'unknown'})."
    else:
        summary_text = f"Summary generated for {data.email} (plan={data.plan or 'unknown'})."

    # Email if requested
    if data.recipient_email:
        send_email_brevo(
            to_email=str(data.recipient_email),
            subject="Your AI Report Summary",
            html_content=f"<p>{summary_text}</p>",
            text_content=summary_text,
        )

    return {"ok": True, "summary": summary_text, "emailed_to": str(data.recipient_email) if data.recipient_email else None}
