import os
import json
import logging
from typing import Optional, Dict, Any

import stripe
import httpx
from fastapi import (
    FastAPI,
    Request,
    HTTPException,
    File,
    UploadFile,
    Form,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

# ------------------------------------------------------------------------------
# Environment / config
# ------------------------------------------------------------------------------

FRONTEND_URL = os.getenv("FRONTEND_URL", "https://ai-report-saas.onrender.com")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

STRIPE_PRICE_BASIC = os.getenv("STRIPE_PRICE_BASIC")
STRIPE_PRICE_PRO = os.getenv("STRIPE_PRICE_PRO")
STRIPE_PRICE_ENTERPRISE = os.getenv("STRIPE_PRICE_ENTERPRISE")

SUCCESS_URL = os.getenv("SUCCESS_URL", f"{FRONTEND_URL}/Billing")

BREVO_API_KEY = os.getenv("BREVO_API_KEY")
BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL")
BREVO_SENDER_NAME = os.getenv("BREVO_SENDER_NAME", "AI Report Assistant")

if not STRIPE_SECRET_KEY:
    logging.warning("STRIPE_SECRET_KEY is not set")
else:
    stripe.api_key = STRIPE_SECRET_KEY

# Plan → price mapping (set only for plans you actually sell)
PLAN_TO_PRICE: Dict[str, Optional[str]] = {
    "basic": STRIPE_PRICE_BASIC,
    "pro": STRIPE_PRICE_PRO,
    "enterprise": STRIPE_PRICE_ENTERPRISE,
}

PRICE_TO_PLAN: Dict[str, str] = {
    price_id: plan
    for plan, price_id in PLAN_TO_PRICE.items()
    if price_id
}

# Whatever limits you want to enforce per plan
SUBSCRIPTION_LIMITS: Dict[str, Dict[str, Any]] = {
    "free": {"max_reports_per_month": 5, "max_chars_per_month": 200_000},
    "basic": {"max_reports_per_month": 20, "max_chars_per_month": 400_000},
    "pro": {"max_reports_per_month": 75, "max_chars_per_month": 1_500_000},
    "enterprise": {"max_reports_per_month": 250, "max_chars_per_month": 5_000_000},
}

# ------------------------------------------------------------------------------
# FastAPI app
# ------------------------------------------------------------------------------

app = FastAPI(title="AI Report Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, FRONTEND_URL.rstrip("/")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------------------
# Pydantic models
# ------------------------------------------------------------------------------

class CheckoutRequest(BaseModel):
    plan: str
    email: EmailStr


class SubscriptionStatusResponse(BaseModel):
    plan: str
    status: str
    current_period_end: Optional[int]
    limits: Dict[str, Any]


# ------------------------------------------------------------------------------
# Health check
# ------------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# ------------------------------------------------------------------------------
# Stripe: create checkout session
# ------------------------------------------------------------------------------

@app.post("/create-checkout-session")
async def create_checkout_session(data: CheckoutRequest) -> dict:
    if data.plan not in PLAN_TO_PRICE:
        raise HTTPException(status_code=400, detail="Invalid plan selected.")

    price_id = PLAN_TO_PRICE[data.plan]
    if not price_id:
        raise HTTPException(status_code=400, detail="Plan is not configured with a price ID.")

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            customer_email=data.email,
            success_url=f"{SUCCESS_URL}?status=success&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{FRONTEND_URL}/Billing?status=cancel",
            allow_promotion_codes=True,  # let Stripe handle coupons on the checkout page
        )
        return {"checkout_url": session.url}
    except Exception as e:  # noqa: BLE001
        logging.exception("Error creating checkout session")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ------------------------------------------------------------------------------
# Stripe: subscription status lookup
# ------------------------------------------------------------------------------

@app.get("/subscription-status", response_model=SubscriptionStatusResponse)
async def subscription_status(email: EmailStr) -> SubscriptionStatusResponse:
    """
    Given a customer email, look up the latest Stripe subscription and map it to
    one of our plan names (basic/pro/enterprise). If nothing is found, return
    the 'free' plan.
    """
    if not STRIPE_SECRET_KEY:
        # No Stripe configured → treat as free
        limits = SUBSCRIPTION_LIMITS["free"]
        return SubscriptionStatusResponse(
            plan="free", status="inactive", current_period_end=None, limits=limits
        )

    try:
        customers = stripe.Customer.list(email=email, limit=1)
        if not customers.data:
            limits = SUBSCRIPTION_LIMITS["free"]
            return SubscriptionStatusResponse(
                plan="free", status="inactive", current_period_end=None, limits=limits
            )

        customer = customers.data[0]
        subs = stripe.Subscription.list(customer=customer.id, status="all", limit=1)

        if not subs.data:
            limits = SUBSCRIPTION_LIMITS["free"]
            return SubscriptionStatusResponse(
                plan="free", status="inactive", current_period_end=None, limits=limits
            )

        sub = subs.data[0]

        # First price on the subscription
        price_id = sub["items"]["data"][0]["price"]["id"]
        plan_name = PRICE_TO_PLAN.get(price_id, "unknown")

        limits = SUBSCRIPTION_LIMITS.get(plan_name, SUBSCRIPTION_LIMITS["free"])

        return SubscriptionStatusResponse(
            plan=plan_name,
            status=sub.status,
            current_period_end=sub.current_period_end,
            limits=limits,
        )
    except Exception as e:  # noqa: BLE001
        logging.exception("Error looking up subscription status")
        # Fallback to free if anything goes wrong
        limits = SUBSCRIPTION_LIMITS["free"]
        return SubscriptionStatusResponse(
            plan="free", status="error", current_period_end=None, limits=limits
        )


# ------------------------------------------------------------------------------
# Stripe webhook
# ------------------------------------------------------------------------------

@app.post("/webhook")
async def stripe_webhook(request: Request) -> dict:
    """
    Stripe webhook endpoint.
    Make sure the Stripe dashboard is pointing its webhook to:
    https://<your-backend>/webhook
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not STRIPE_WEBHOOK_SECRET:
        # If not configured, just log and accept
        logging.warning("Stripe webhook secret not configured; skipping verification")
        try:
            event = json.loads(payload.decode("utf-8"))
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="Invalid payload")
    else:
        try:
            event = stripe.Webhook.construct_event(
                payload=payload,
                sig_header=sig_header,
                secret=STRIPE_WEBHOOK_SECRET,
            )
        except stripe.error.SignatureVerificationError:
            logging.exception("Invalid Stripe signature")
            raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event.get("type")
    logging.info("Received Stripe event: %s", event_type)

    # You can expand this with more detailed handling as needed
    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        logging.info("Checkout completed for session %s", session.get("id"))

    elif event_type.startswith("customer.subscription."):
        sub = event["data"]["object"]
        logging.info("Subscription event %s → %s", event_type, sub.get("status"))

    return {"received": True}


# ------------------------------------------------------------------------------
# Summarization helpers
# ------------------------------------------------------------------------------

def generate_summary_text(raw_text: str) -> str:
    """
    Generate a business-friendly summary from the input text using OpenAI.
    If OpenAI is not configured or fails, fall back to a simple truncation.
    """
    if not OPENAI_API_KEY:
        logging.warning("OPENAI_API_KEY not set; returning truncated content")
        return (
            "AI summarization is not configured. "
            "Here is a truncated preview of your content:\n\n"
            + raw_text[:2000]
        )

    try:
        from openai import OpenAI

        client = OpenAI(api_key=OPENAI_API_KEY)

        prompt = (
            "You are an assistant that writes concise, business-friendly summaries. "
            "Summarize the following content for busy professionals, focusing on key "
            "points, risks, opportunities, and recommended next steps. "
            "Use clear headings and bullet points where helpful."
        )

        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": raw_text},
            ],
            temperature=0.4,
        )

        summary = completion.choices[0].message.content.strip()
        return summary
    except Exception as e:  # noqa: BLE001
        logging.exception("OpenAI summarization failed")
        return (
            "We were unable to generate an AI summary at this time.\n\n"
            "Here is a truncated preview of your content:\n\n"
            + raw_text[:2000]
            + f"\n\n(Technical error: {e})"
        )


def summary_text_to_html(summary_text: str) -> str:
    """
    Very small helper to convert plain text summary into simple HTML paragraphs.
    """
    paragraphs = [p.strip() for p in summary_text.split("\n\n") if p.strip()]
    if not paragraphs:
        return "<p>(No content)</p>"
    return "".join(f"<p>{p.replace('\n', '<br>')}</p>" for p in paragraphs)


def send_summary_email(recipient_email: str, summary_html: str, original_filename: str) -> str:
    """
    Send the summary via Brevo (Sendinblue). Returns a status string.
    """
    if not (BREVO_API_KEY and BREVO_SENDER_EMAIL):
        logging.warning("Brevo not configured; skipping email send")
        return "Email not configured"

    subject = f"AI Summary – {original_filename or 'Your Report'}"

    payload = {
        "sender": {"email": BREVO_SENDER_EMAIL, "name": BREVO_SENDER_NAME},
        "to": [{"email": recipient_email}],
        "subject": subject,
        "htmlContent": summary_html,
    }

    try:
        resp = httpx.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "api-key": BREVO_API_KEY,
            },
            json=payload,
            timeout=30.0,
        )
        if resp.status_code >= 400:
            logging.error("Brevo email error %s: %s", resp.status_code, resp.text)
            return "Error sending email"
        return "Email sent"
    except Exception:  # noqa: BLE001
        logging.exception("Brevo email request failed")
        return "Error sending email"


# ------------------------------------------------------------------------------
# /summarize endpoint (used by Upload Data page)
# ------------------------------------------------------------------------------

@app.post("/summarize")
async def summarize(
    file: UploadFile = File(...),
    send_email: bool = Form(False),
    recipient_email: Optional[EmailStr] = Form(None),
) -> dict:
    """
    Accepts a file upload and (optionally) sends the AI summary to the recipient.
    Returns JSON with:
      - summary_html
      - email_status
    """
    # Read file contents
    raw_bytes = await file.read()
    try:
        raw_text = raw_bytes.decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        raw_text = raw_bytes.decode("latin-1", errors="ignore")

    # Generate summary text via OpenAI (or fallback)
    summary_text = generate_summary_text(raw_text)
    summary_html = summary_text_to_html(summary_text)

    # Optionally send email
    email_status = "skipped"
    if send_email and recipient_email:
        email_status = send_summary_email(
            recipient_email=recipient_email,
            summary_html=summary_html,
            original_filename=file.filename or "Uploaded report",
        )

    return {
        "summary_html": summary_html,
        "email_status": email_status,
    }
