import os
import logging
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

import stripe

# -------------------------------------------------------------------
# Environment / configuration
# -------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-report-backend")

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://ai-report-saas.onrender.com")

# Price IDs for each plan
STRIPE_PRICE_BASIC = os.environ.get("STRIPE_PRICE_BASIC")
STRIPE_PRICE_PRO = os.environ.get("STRIPE_PRICE_PRO")
STRIPE_PRICE_ENTERPRISE = os.environ.get("STRIPE_PRICE_ENTERPRISE")

if not STRIPE_SECRET_KEY:
    logger.warning("STRIPE_SECRET_KEY is not set; Stripe calls will fail.")

stripe.api_key = STRIPE_SECRET_KEY

PLAN_TO_PRICE: Dict[str, Optional[str]] = {
    "basic": STRIPE_PRICE_BASIC,
    "pro": STRIPE_PRICE_PRO,
    "enterprise": STRIPE_PRICE_ENTERPRISE,
}

# -------------------------------------------------------------------
# FastAPI app
# -------------------------------------------------------------------

app = FastAPI(title="AI Report Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # you can tighten this later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------------
# Pydantic models
# -------------------------------------------------------------------

class CheckoutRequest(BaseModel):
    email: EmailStr
    plan: str
    coupon: Optional[str] = None  # coupon code like "welcome"


class CheckoutResponse(BaseModel):
    checkout_url: str


class SubscriptionStatusResponse(BaseModel):
    email: EmailStr
    has_active_subscription: bool
    status: str
    plan: Optional[str] = None
    current_period_end: Optional[int] = None  # epoch seconds, may be None


class SummarizeRequest(BaseModel):
    text: str
    recipient_email: Optional[EmailStr] = None
    send_email: bool = False


class SummarizeResponse(BaseModel):
    summary: str
    emailed: bool = False


# -------------------------------------------------------------------
# Health check
# -------------------------------------------------------------------

@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


# -------------------------------------------------------------------
# Create checkout session
# -------------------------------------------------------------------

@app.post("/create-checkout-session", response_model=CheckoutResponse)
async def create_checkout_session(req: CheckoutRequest) -> CheckoutResponse:
    logger.info("Creating checkout session for email=%s plan=%s coupon=%s",
                req.email, req.plan, req.coupon)

    price_id = PLAN_TO_PRICE.get(req.plan.lower())
    if not price_id:
        logger.error("Unknown or unconfigured plan: %s", req.plan)
        raise HTTPException(status_code=400, detail="Invalid plan selected")

    try:
        # Find or create customer by email
        customers = stripe.Customer.list(email=req.email, limit=1)
        if customers.data:
            customer_id = customers.data[0].id
        else:
            customer = stripe.Customer.create(email=req.email)
            customer_id = customer.id

        session_params: Dict[str, Any] = {
            "mode": "subscription",
            "customer": customer_id,
            "line_items": [
                {
                    "price": price_id,
                    "quantity": 1,
                }
            ],
            "success_url": f"{FRONTEND_URL}/Billing?status=success&session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{FRONTEND_URL}/Billing?status=cancel",
        }

        # Only add discounts if a coupon is provided
        if req.coupon:
            session_params["discounts"] = [{"coupon": req.coupon}]

        session = stripe.checkout.Session.create(**session_params)

        logger.info(
            "Created checkout session %s for email %s plan %s",
            session.id, req.email, req.plan
        )
        return CheckoutResponse(checkout_url=session.url)
    except stripe.error.StripeError as e:
        logger.exception("Stripe error while creating checkout session: %s", e)
        raise HTTPException(status_code=500, detail="Error creating checkout session")
    except Exception as e:
        logger.exception("Unexpected error while creating checkout session: %s", e)
        raise HTTPException(status_code=500, detail="Unexpected error")


# -------------------------------------------------------------------
# Subscription status lookup
# -------------------------------------------------------------------

@app.get("/subscription-status", response_model=SubscriptionStatusResponse)
async def subscription_status(email: EmailStr) -> SubscriptionStatusResponse:
    """
    Look up the most recent subscription for a customer by email.
    If no active subscription is found, return has_active_subscription=False.
    Never crash if current_period_end or plan info is missing.
    """
    logger.info("Checking subscription status for email=%s", email)

    try:
        customers = stripe.Customer.list(email=email, limit=1)
        if not customers.data:
            logger.info("No customer found for email=%s", email)
            return SubscriptionStatusResponse(
                email=email,
                has_active_subscription=False,
                status="none",
                plan=None,
                current_period_end=None,
            )

        customer_id = customers.data[0].id

        subs = stripe.Subscription.list(
            customer=customer_id,
            status="all",
            limit=1,
            expand=["data.plan.product"],
        )

        if not subs.data:
            logger.info("No subscriptions found for email=%s", email)
            return SubscriptionStatusResponse(
                email=email,
                has_active_subscription=False,
                status="none",
                plan=None,
                current_period_end=None,
            )

        sub = subs.data[0]

        status = getattr(sub, "status", "unknown")
        has_active = status in ("trialing", "active")
        current_period_end = getattr(sub, "current_period_end", None)

        # plan nickname or product name if available
        plan_name: Optional[str] = None
        try:
            if sub.plan and hasattr(sub.plan, "nickname") and sub.plan.nickname:
                plan_name = sub.plan.nickname
            elif sub.plan and hasattr(sub.plan, "product") and hasattr(sub.plan.product, "name"):
                plan_name = sub.plan.product.name
        except Exception:
            plan_name = None

        logger.info(
            "Subscription lookup for email=%s -> status=%s, active=%s, plan=%s",
            email, status, has_active, plan_name
        )

        return SubscriptionStatusResponse(
            email=email,
            has_active_subscription=has_active,
            status=status,
            plan=plan_name,
            current_period_end=current_period_end,
        )

    except stripe.error.StripeError as e:
        logger.exception("Stripe error while checking subscription status: %s", e)
        # On error, surface a safe "none" status to the UI so it doesn't break
        return SubscriptionStatusResponse(
            email=email,
            has_active_subscription=False,
            status="error",
            plan=None,
            current_period_end=None,
        )
    except Exception as e:
        logger.exception("Unexpected error while checking subscription status: %s", e)
        return SubscriptionStatusResponse(
            email=email,
            has_active_subscription=False,
            status="error",
            plan=None,
            current_period_end=None,
        )


# -------------------------------------------------------------------
# Summarization endpoint
# -------------------------------------------------------------------

# Optional: use OpenAI for summaries if OPENAI_API_KEY is set
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if OPENAI_API_KEY:
    try:
        from openai import OpenAI

        openai_client = OpenAI(api_key=OPENAI_API_KEY)
    except Exception as e:
        logger.warning("Failed to initialize OpenAI client: %s", e)
        openai_client = None
else:
    openai_client = None


@app.post("/summarize", response_model=SummarizeResponse)
async def summarize(req: SummarizeRequest) -> SummarizeResponse:
    """
    Generate a concise summary of the uploaded text.
    For now, emailing is not implemented – we just log that request.
    """
    if not openai_client:
        logger.warning("Summarize called but OpenAI is not configured.")
        return SummarizeResponse(
            summary="Summarization service is not configured on the server.",
            emailed=False,
        )

    try:
        completion = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an assistant that writes concise, client-ready business summaries. "
                        "Highlight key findings, risks, and recommended next steps."
                    ),
                },
                {"role": "user", "content": req.text},
            ],
            max_tokens=600,
        )

        summary_text = completion.choices[0].message.content.strip()

        # Email sending is optional / not implemented yet.
        emailed = False
        if req.send_email and req.recipient_email:
            logger.info(
                "Email sending requested for summary to %s, "
                "but email integration is not implemented. Skipping.",
                req.recipient_email,
            )
            emailed = False

        return SummarizeResponse(summary=summary_text, emailed=emailed)

    except Exception as e:
        logger.exception("Error generating summary: %s", e)
        raise HTTPException(status_code=500, detail="Error generating summary")


# -------------------------------------------------------------------
# Stripe webhook endpoint
# -------------------------------------------------------------------

@app.post("/stripe-webhook")
async def stripe_webhook(request: Request) -> Dict[str, Any]:
    """
    Minimal Stripe webhook handler.
    Right now it just verifies the signature and logs the event type.
    You can extend this to update your own entitlements if needed.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not STRIPE_WEBHOOK_SECRET:
        logger.error("STRIPE_WEBHOOK_SECRET is not configured.")
        raise HTTPException(status_code=500, detail="Webhook secret not configured")

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

    logger.info("Received Stripe event: %s", event["type"])

    # Example: you could look for 'checkout.session.completed' here and
    # sync with your own DB / entitlements.
    # For now we just acknowledge receipt.
    return {"received": True}
