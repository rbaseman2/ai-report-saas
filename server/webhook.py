import os
import logging
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

import stripe

# -------------------------------------------------------------------
# Environment / configuration
# -------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

PRICE_BASIC = os.getenv("PRICE_BASIC")
PRICE_PRO = os.getenv("PRICE_PRO")
PRICE_ENTERPRISE = os.getenv("PRICE_ENTERPRISE")

SUCCESS_URL = os.getenv("SUCCESS_URL", "https://example.com/success")
CANCEL_URL = os.getenv("CANCEL_URL", "https://example.com/cancel")

FRONTEND_URL = os.getenv("FRONTEND_URL", "https://ai-report-saas.onrender.com")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY
else:
    logger.warning("STRIPE_SECRET_KEY is not set – Stripe calls will fail.")

# -------------------------------------------------------------------
# FastAPI app + CORS
# -------------------------------------------------------------------

app = FastAPI(title="AI Report Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:8501", "http://127.0.0.1:8501", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------------
# Pydantic models
# -------------------------------------------------------------------


class SummarizeRequest(BaseModel):
    email: EmailStr                # billing / user email
    text: str                      # content to summarize (already truncated in frontend)
    send_email: bool = False       # whether to email summary to someone
    recipient_email: Optional[EmailStr] = None  # optional recipient


class CheckoutRequest(BaseModel):
    email: EmailStr
    plan: str  # "basic" | "pro" | "enterprise"


# -------------------------------------------------------------------
# Health check
# -------------------------------------------------------------------


@app.get("/health")
async def health():
    """Simple health check endpoint for Render."""
    return {"status": "ok"}


# -------------------------------------------------------------------
# Summarization logic (OpenAI)
# -------------------------------------------------------------------

def generate_summary(text: str) -> str:
    """
    Very simple wrapper around OpenAI to generate a business-style summary.
    Adjust this to match the library you're using (openai / OpenAI client, etc).
    """
    if not OPENAI_API_KEY:
        # In case the key is missing, fail gracefully instead of 500.
        logger.error("OPENAI_API_KEY not set – returning fallback summary.")
        return "Summary service is temporarily unavailable. Please try again later."

    try:
        # Example using the official 'openai' client (you may need to adjust).
        from openai import OpenAI

        client = OpenAI(api_key=OPENAI_API_KEY)

        prompt = (
            "You are an assistant that writes concise, business-friendly summaries. "
            "Summarize the following content for busy professionals, focusing on key "
            "points, risks, opportunities, and recommended actions.\n\n"
            f"CONTENT:\n{text}"
        )

        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You write clear business summaries."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=800,
        )

        return completion.choices[0].message.content.strip()

    except Exception as e:
        logger.exception("Error while calling OpenAI: %s", e)
        return "There was an error generating the summary. Please try again later."


def send_summary_email(to_email: str, body: str, original_email: str):
    """
    Placeholder for sending summary by email.

    Right now this just logs. To actually send email, plug in SMTP,
    SendGrid, Amazon SES, etc. Make sure failures DO NOT raise.
    """
    try:
        logger.info(
            "Pretending to send summary email to %s (triggered by %s).",
            to_email,
            original_email,
        )
        # Example skeleton if you later add SMTP:
        #
        # import smtplib
        # from email.message import EmailMessage
        # msg = EmailMessage()
        # msg["Subject"] = "Your AI-generated summary"
        # msg["From"] = os.getenv("EMAIL_FROM", "no-reply@example.com")
        # msg["To"] = to_email
        # msg.set_content(body)
        #
        # with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
        #     smtp.login(SMTP_USER, SMTP_PASSWORD)
        #     smtp.send_message(msg)
    except Exception as e:
        logger.exception("Failed to send summary email: %s", e)


@app.post("/summarize")
async def summarize(req: SummarizeRequest):
    """
    Generate a business summary from text.

    Expected JSON body (from Upload_Data page):
    {
        "email": "user@example.com",
        "text": "...",
        "send_email": true/false,
        "recipient_email": "client@company.com"
    }
    """
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Text content is required.")

    summary = generate_summary(req.text)

    # Optionally email the summary
    if req.send_email and req.recipient_email:
        send_summary_email(req.recipient_email, summary, req.email)

    return {
        "summary": summary,
        "emailed": bool(req.send_email and req.recipient_email),
    }


# -------------------------------------------------------------------
# Stripe: Checkout Session with coupons
# -------------------------------------------------------------------


def price_for_plan(plan: str) -> str:
    plan = plan.lower()
    if plan == "basic":
        return PRICE_BASIC
    if plan == "pro":
        return PRICE_PRO
    if plan == "enterprise":
        return PRICE_ENTERPRISE
    return None


@app.post("/create-checkout-session")
async def create_checkout_session(data: CheckoutRequest):
    if not STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=500,
            detail="Stripe is not configured on the server.",
        )

    price_id = price_for_plan(data.plan)
    if not price_id:
        raise HTTPException(status_code=400, detail="Invalid plan requested.")

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            customer_email=str(data.email),
            success_url=f"{SUCCESS_URL}?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=CANCEL_URL,
            allow_promotion_codes=True,  # enables coupon / promo code box
            metadata={
                "plan": data.plan,
                "billing_email": str(data.email),
            },
        )
        return {"checkout_url": session.url}
    except Exception as e:
        logger.exception("Error creating checkout session: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Error creating checkout session: {e}",
        )


# -------------------------------------------------------------------
# Stripe: Subscription status (used by Billing page)
# -------------------------------------------------------------------


@app.get("/subscription-status")
async def subscription_status(email: EmailStr):
    """
    Returns the user's current plan & limits based on active Stripe subscription.

    Always returns a JSON payload – NEVER throws 500 so the Billing page
    won't break even if Stripe is misconfigured.
    """
    logger.info("Checking subscription status for email=%s", email)

    # default "free" limits
    free_limits = {"max_documents": 5, "max_chars": 200000}

    if not STRIPE_SECRET_KEY:
        return {
            "active": False,
            "plan": "free",
            "limits": free_limits,
            "error": "Stripe not configured on server.",
        }

    try:
        # 1) Find customer by email
        customers = stripe.Customer.list(email=email).data
        if not customers:
            return {
                "active": False,
                "plan": "free",
                "limits": free_limits,
            }

        customer = customers[0]

        # 2) Get active subscription(s)
        subs = stripe.Subscription.list(
            customer=customer.id,
            status="active",
        ).data

        if not subs:
            return {
                "active": False,
                "plan": "free",
                "limits": free_limits,
            }

        sub = subs[0]

        # 3) Map price -> internal plan name
        price_id = sub["items"]["data"][0]["price"]["id"]

        price_plan_map = {
            PRICE_BASIC: "basic",
            PRICE_PRO: "pro",
            PRICE_ENTERPRISE: "enterprise",
        }

        plan = price_plan_map.get(price_id, "free")

        limits_by_plan = {
            "basic": {"max_documents": 20, "max_chars": 400000},
            "pro": {"max_documents": 75, "max_chars": 1500000},
            "enterprise": {"max_documents": 250, "max_chars": 5000000},
            "free": free_limits,
        }

        limits = limits_by_plan.get(plan, free_limits)

        return {
            "active": True,
            "plan": plan,
            "limits": limits,
        }

    except stripe.error.StripeError as e:
        logger.exception("Stripe error in /subscription-status: %s", e)
        return {
            "active": False,
            "plan": "free",
            "limits": free_limits,
            "error": str(e),
        }
    except Exception as e:
        logger.exception("Unexpected error in /subscription-status: %s", e)
        return {
            "active": False,
            "plan": "free",
            "limits": free_limits,
            "error": f"Unexpected error: {e}",
        }


# -------------------------------------------------------------------
# Stripe Webhook endpoint (optional, for future use)
# -------------------------------------------------------------------


@app.post("/stripe-webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events (currently logs only)."""
    if not STRIPE_WEBHOOK_SECRET:
        # For now just log and return 200 so Stripe doesn’t keep retrying.
        logger.warning("STRIPE_WEBHOOK_SECRET is not set; ignoring webhook signature.")
        payload = await request.body()
        logger.info("Webhook payload (unsigned): %s", payload.decode("utf-8"))
        return {"received": True}

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except ValueError as e:
        logger.error("Invalid payload: %s", e)
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        logger.error("Invalid signature: %s", e)
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Basic logging – you can expand this for real entitlement logic.
    logger.info("Received Stripe event: %s", event["type"])

    return {"received": True}
