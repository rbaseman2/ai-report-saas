import os
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import stripe
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
import httpx

# ---------- Configuration ----------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-report-backend")

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://ai-report-saas.onrender.com")

STRIPE_PRICE_BASIC = os.getenv("STRIPE_PRICE_BASIC")
STRIPE_PRICE_PRO = os.getenv("STRIPE_PRICE_PRO")
STRIPE_PRICE_ENTERPRISE = os.getenv("STRIPE_PRICE_ENTERPRISE")

if not STRIPE_SECRET_KEY:
    logger.warning("STRIPE_SECRET_KEY is not set")

stripe.api_key = STRIPE_SECRET_KEY

PLAN_TO_PRICE: Dict[str, Optional[str]] = {
    "basic": STRIPE_PRICE_BASIC,
    "pro": STRIPE_PRICE_PRO,
    "enterprise": STRIPE_PRICE_ENTERPRISE,
}

BREVO_API_KEY = os.getenv("BREVO_API_KEY")
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "no-reply@robalsolutions.com")

# ---------- FastAPI app ----------

app = FastAPI(title="AI Report Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        FRONTEND_URL,
        "https://ai-report-saas.onrender.com",
        "http://localhost:8501",
        "http://localhost:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Pydantic models ----------

class CheckoutRequest(BaseModel):
    email: EmailStr
    plan: str
    coupon: Optional[str] = None


class CheckoutResponse(BaseModel):
    checkout_url: str


class SubscriptionStatusResponse(BaseModel):
    email: EmailStr
    status: str          # "none", "active", "canceled", "past_due", "error", etc.
    plan: Optional[str] = None
    current_period_end: Optional[datetime] = None


# ---------- Utility helpers ----------

def get_price_id_for_plan(plan: str) -> str:
    plan_key = plan.lower()
    price_id = PLAN_TO_PRICE.get(plan_key)
    if not price_id:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown or misconfigured plan '{plan}'. "
                   f"Check STRIPE_PRICE_BASIC/PRO/ENTERPRISE env vars.",
        )
    return price_id


async def send_email_via_brevo(to_email: str, subject: str, html_content: str) -> None:
    """Send email using Brevo transactional API."""
    if not BREVO_API_KEY:
        logger.warning("BREVO_API_KEY not set; skipping email send.")
        return

    payload = {
        "sender": {"email": SENDER_EMAIL, "name": "AI Report"},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_content,
    }

    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json",
    }

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            "https://api.brevo.com/v3/smtp/email",
            json=payload,
            headers=headers,
        )
        try:
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("Brevo email send failed: %s - body=%s", exc, resp.text)


# ---------- Basic health check ----------

@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


# ---------- Stripe subscription endpoints ----------

@app.post("/create-checkout-session", response_model=CheckoutResponse)
async def create_checkout_session(req: CheckoutRequest) -> CheckoutResponse:
    """
    Create a Stripe Checkout session for a subscription.
    Supports promo-code box AND an optional coupon you pass from the billing page.
    """
    logger.info(
        "Creating checkout session for email=%s, plan=%s, coupon=%s",
        req.email,
        req.plan,
        req.coupon,
    )

    # 1) Find or create customer
    customers = stripe.Customer.list(email=req.email, limit=1)
    if customers.data:
        customer_id = customers.data[0].id
    else:
        customer = stripe.Customer.create(email=req.email)
        customer_id = customer.id

    # 2) Determine price id
    price_id = get_price_id_for_plan(req.plan)

    # 3) Base session params
    session_params: Dict[str, Any] = {
        "mode": "subscription",
        "customer": customer_id,
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": (
            f"{FRONTEND_URL}/Billing"
            "?status=success&session_id={{CHECKOUT_SESSION_ID}}"
        ),
        "cancel_url": f"{FRONTEND_URL}/Billing?status=cancel",
        # Show the "have a promo code?" box on the Stripe checkout page
        "allow_promotion_codes": True,
        "subscription_data": {
            "metadata": {
                "plan": req.plan.lower(),
                "billing_email": req.email,
            }
        },
    }

    # 4) Auto-apply a coupon if the user typed one on your Billing page
    # Stripe API requires EITHER allow_promotion_codes OR discounts here,
    # not both at the same time – but allow_promotion_codes is allowed with
    # discounts on the *session* itself, so this combo is valid.
    if req.coupon:
        session_params["discounts"] = [{"coupon": req.coupon}]

    try:
        session = stripe.checkout.Session.create(**session_params)
    except stripe.error.StripeError as e:
        logger.exception("Error creating Stripe checkout session")
        raise HTTPException(status_code=400, detail=str(e))

    logger.info("Created checkout session %s for %s", session.id, req.email)
    return CheckoutResponse(checkout_url=session.url)


@app.get("/subscription-status", response_model=SubscriptionStatusResponse)
async def subscription_status(email: EmailStr) -> SubscriptionStatusResponse:
    """
    Return high-level subscription status for the given billing email.

    Used by the Billing page banner (“No active subscription found for this email.”).
    """
    logger.info("Looking up subscription status for %s", email)

    try:
        customers = stripe.Customer.list(email=email, limit=1)
        if not customers.data:
            return SubscriptionStatusResponse(email=email, status="none")

        customer = customers.data[0]

        subs = stripe.Subscription.list(customer=customer.id, status="all", limit=1)
        if not subs.data:
            return SubscriptionStatusResponse(email=email, status="none")

        sub = subs.data[0]
        raw_status = getattr(sub, "status", "unknown") or "unknown"

        # Figure out plan from the price id
        items = getattr(sub, "items", None)
        plan_name: Optional[str] = None
        if items and getattr(items, "data", None):
            price = items.data[0].price
            price_id = getattr(price, "id", None)
            if price_id == STRIPE_PRICE_BASIC:
                plan_name = "basic"
            elif price_id == STRIPE_PRICE_PRO:
                plan_name = "pro"
            elif price_id == STRIPE_PRICE_ENTERPRISE:
                plan_name = "enterprise"

        # Some subs may not have current_period_end; guard for that
        cpe_ts = getattr(sub, "current_period_end", None)
        cpe = (
            datetime.fromtimestamp(cpe_ts, tz=timezone.utc)
            if isinstance(cpe_ts, int)
            else None
        )

        return SubscriptionStatusResponse(
            email=email,
            status=raw_status,
            plan=plan_name,
            current_period_end=cpe,
        )
    except stripe.error.StripeError:
        logger.exception("Error looking up subscription status")
        # Frontend treats "error" as “we couldn’t check”
        return SubscriptionStatusResponse(email=email, status="error")


# ---------- Stripe webhook ----------

@app.post("/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events (checkout completed, subscription changes, etc.)."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not STRIPE_WEBHOOK_SECRET:
        logger.warning("STRIPE_WEBHOOK_SECRET is not set; ignoring webhook.")
        return {"received": True}

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except (ValueError, stripe.error.SignatureVerificationError) as e:
        logger.error("Invalid Stripe webhook: %s", e)
        raise HTTPException(status_code=400, detail="Invalid webhook")

    event_type = event["type"]
    logger.info("Received Stripe event: %s", event_type)

    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        logger.info("Checkout session completed: %s", session.get("id"))
    elif event_type == "customer.subscription.updated":
        sub = event["data"]["object"]
        logger.info(
            "Subscription %s updated, status=%s",
            sub.get("id"),
            sub.get("status"),
        )
    elif event_type == "customer.subscription.deleted":
        sub = event["data"]["object"]
        logger.info("Subscription %s deleted", sub.get("id"))

    return {"received": True}


# ---------- /summarize endpoint (used by Upload Data page) ----------

@app.post("/summarize")
async def summarize_report(
    file: UploadFile = File(...),
    recipient_email: Optional[EmailStr] = Form(None),
    send_email: bool = Form(False),
) -> Dict[str, Any]:
    """
    Summarize an uploaded report file.

    NOTE: Right now this returns a placeholder summary so the endpoint exists
    and your Upload Data page stops getting 404s. You can plug your existing
    OpenAI summarization logic back in here.
    """
    contents = await file.read()
    num_bytes = len(contents)

    summary_text = (
        f"This is a placeholder summary for '{file.filename}'. "
        f"The uploaded file contained {num_bytes} bytes. "
        "Replace this with your real OpenAI summarization logic."
    )

    if send_email and recipient_email:
        await send_email_via_brevo(
            to_email=str(recipient_email),
            subject="Your AI report summary",
            html_content=f"<p>{summary_text}</p>",
        )

    return {
        "summary": summary_text,
        "emailed": bool(send_email and recipient_email),
    }
