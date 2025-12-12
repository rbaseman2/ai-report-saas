# server/webhook.py
"""
FastAPI backend for:
- Stripe subscription checkout
- Subscription status lookup
- Stripe webhook
- AI summary generation (Basic / Pro / Enterprise)
- Optional email delivery via Brevo

Startup (Render):
    uvicorn server.webhook:app --host 0.0.0.0 --port $PORT
"""

import os
import logging
from typing import Optional, Literal

import stripe
import openai
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# -------------------------------------------------------------------
# Logging
# -------------------------------------------------------------------
logger = logging.getLogger("ai-report-backend")
logger.setLevel(logging.INFO)

# -------------------------------------------------------------------
# Environment
# -------------------------------------------------------------------
STRIPE_API_KEY = os.getenv("STRIPE_API_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

STRIPE_PRICE_BASIC = os.getenv("STRIPE_PRICE_BASIC")
STRIPE_PRICE_PRO = os.getenv("STRIPE_PRICE_PRO")
STRIPE_PRICE_ENTERPRISE = os.getenv("STRIPE_PRICE_ENTERPRISE")

FRONTEND_URL = os.getenv("FRONTEND_URL")  # e.g. https://ai-report-saas.onrender.com
CANCEL_URL = os.getenv("CANCEL_URL", FRONTEND_URL)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
EMAIL_FROM = os.getenv("EMAIL_FROM")

if not STRIPE_API_KEY:
    logger.warning("STRIPE_API_KEY is not configured.")
else:
    stripe.api_key = STRIPE_API_KEY

if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY is not configured.")
else:
    openai.api_key = OPENAI_API_KEY

# -------------------------------------------------------------------
# FastAPI app
# -------------------------------------------------------------------
app = FastAPI(title="AI Report Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # lock this down later if you like
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------------
# Pydantic models
# -------------------------------------------------------------------
PlanType = Literal["basic", "pro", "enterprise"]


class CheckoutRequest(BaseModel):
    email: str
    plan: PlanType
    coupon_code: Optional[str] = None  # plain coupon ID from Stripe, e.g. "welcome"


class CheckoutResponse(BaseModel):
    checkout_url: str


class SubscriptionStatusResponse(BaseModel):
    email: str
    status: Literal["none", "active", "incomplete", "past_due", "canceled", "trialing"]
    plan: Optional[PlanType] = None
    current_period_end: Optional[int] = None  # unix timestamp


class SummarizeRequest(BaseModel):
    text: str
    plan: PlanType
    recipient_email: Optional[str] = None


class SummarizeResponse(BaseModel):
    summary: str
    emailed: bool


# -------------------------------------------------------------------
# Utility: map plan -> Stripe price
# -------------------------------------------------------------------
def get_price_for_plan(plan: PlanType) -> str:
    if plan == "basic":
        if not STRIPE_PRICE_BASIC:
            raise HTTPException(status_code=500, detail="Basic price ID not configured")
        return STRIPE_PRICE_BASIC
    if plan == "pro":
        if not STRIPE_PRICE_PRO:
            raise HTTPException(status_code=500, detail="Pro price ID not configured")
        return STRIPE_PRICE_PRO
    if plan == "enterprise":
        if not STRIPE_PRICE_ENTERPRISE:
            raise HTTPException(
                status_code=500, detail="Enterprise price ID not configured"
            )
        return STRIPE_PRICE_ENTERPRISE
    # Should never reach here
    raise HTTPException(status_code=400, detail="Invalid plan")


# -------------------------------------------------------------------
# Health
# -------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok"}


# -------------------------------------------------------------------
# Stripe: Create checkout session
# -------------------------------------------------------------------
@app.post("/create-checkout-session", response_model=CheckoutResponse)
async def create_checkout_session(req: CheckoutRequest):
    if not STRIPE_API_KEY:
        raise HTTPException(status_code=500, detail="Stripe is not configured")

    price_id = get_price_for_plan(req.plan)
    success_url = f"{FRONTEND_URL.rstrip('/')}/Billing?status=success&session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = CANCEL_URL or FRONTEND_URL

    discounts = None
    # If coupon code provided, we apply it as a discount (no allow_promotion_codes)
    if req.coupon_code:
        try:
            # This will raise if coupon is invalid
            stripe.Coupon.retrieve(req.coupon_code)
            discounts = [{"coupon": req.coupon_code}]
        except Exception as e:
            logger.warning(f"Invalid coupon {req.coupon_code}: {e}")
            raise HTTPException(status_code=400, detail="Invalid coupon code")

    try:
        params = {
            "mode": "subscription",
            "customer_email": req.email,
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": success_url,
            "cancel_url": cancel_url,
            "metadata": {"plan": req.plan},
            "subscription_data": {"metadata": {"plan": req.plan}},
        }

        if discounts:
            params["discounts"] = discounts
        # NOTE: we do NOT set allow_promotion_codes here, to avoid Stripe's
        # "only one of allow_promotion_codes or discounts" error.

        session = stripe.checkout.Session.create(**params)
        logger.info(
            f"Created checkout session {session.id} for plan {req.plan} and email {req.email}"
        )
        return CheckoutResponse(checkout_url=session.url)
    except Exception as e:
        logger.exception("Error creating checkout session")
        raise HTTPException(status_code=500, detail=f"Stripe error: {e}")


# -------------------------------------------------------------------
# Stripe: Subscription status lookup
# -------------------------------------------------------------------
@app.get("/subscription-status", response_model=SubscriptionStatusResponse)
async def subscription_status(email: str):
    if not STRIPE_API_KEY:
        raise HTTPException(status_code=500, detail="Stripe is not configured")

    try:
        # 1) Find customer by email
        customers = stripe.Customer.list(email=email, limit=1).data
        if not customers:
            return SubscriptionStatusResponse(email=email, status="none")

        customer = customers[0]

        # 2) Get subscriptions for that customer
        subs = stripe.Subscription.list(
            customer=customer.id, status="all", limit=10
        ).data

        if not subs:
            return SubscriptionStatusResponse(email=email, status="none")

        # Prefer active/trialing
        preferred_status_order = ["active", "trialing", "incomplete", "past_due"]
        best_sub = None

        for desired in preferred_status_order:
            for s in subs:
                if s.status == desired:
                    best_sub = s
                    break
            if best_sub:
                break

        if not best_sub:
            # Just take the first one
            best_sub = subs[0]

        sub_status = best_sub.status
        metadata_plan = (best_sub.metadata or {}).get("plan")
        plan: Optional[PlanType] = None
        if metadata_plan in ("basic", "pro", "enterprise"):
            plan = metadata_plan  # type: ignore[assignment]

        current_period_end = getattr(best_sub, "current_period_end", None)

        return SubscriptionStatusResponse(
            email=email,
            status=sub_status,  # type: ignore[arg-type]
            plan=plan,
            current_period_end=current_period_end,
        )
    except Exception as e:
        logger.exception("Error looking up subscription status")
        # We still return "none" so the UI doesn't crash
        raise HTTPException(
            status_code=500, detail=f"Error looking up subscription status: {e}"
        )


# -------------------------------------------------------------------
# Stripe: Webhook handler
# -------------------------------------------------------------------
@app.post("/stripe-webhook")
async def stripe_webhook(request: Request):
    if not STRIPE_WEBHOOK_SECRET:
        logger.warning("Stripe webhook secret not configured.")
        raise HTTPException(status_code=500, detail="Webhook not configured")

    payload = await request.body()
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        logger.warning(f"Webhook signature verification failed: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    logger.info(f"Received Stripe event: {event_type}")

    # Minimal handling — Stripe remains the source of truth
    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        logger.info(
            f"Checkout completed: session {session.get('id')}, customer {session.get('customer')}"
        )
    elif event_type.startswith("customer.subscription."):
        sub = event["data"]["object"]
        logger.info(
            f"Subscription event {event_type} for customer {sub.get('customer')} "
            f"status {sub.get('status')}"
        )

    return {"received": True}


# -------------------------------------------------------------------
# AI summarization
# -------------------------------------------------------------------
def build_prompt(plan: PlanType, text: str) -> str:
    base_instructions = (
        "You are an expert business and medical-report summarizer. "
        "Write in clear, professional language suitable for executives and clinicians."
    )

    if plan == "basic":
        return (
            f"{base_instructions}\n\n"
            "Task: Provide a concise summary (150–250 words) of the key points in this report.\n\n"
            f"Report:\n{text}"
        )

    if plan == "pro":
        return (
            f"{base_instructions}\n\n"
            "Task: Provide a detailed summary (250–400 words) including:\n"
            "1) Overall findings\n"
            "2) Key metrics or results\n"
            "3) Any risks or concerns\n"
            "4) Recommended next steps (bulleted)\n\n"
            f"Report:\n{text}"
        )

    # Enterprise
    return (
        f"{base_instructions}\n\n"
        "Task: Produce a structured executive summary of the following report.\n"
        "Your answer MUST use these sections and headings:\n\n"
        "1. Overview\n"
        "   - 3–5 bullet points summarizing the overall situation.\n\n"
        "2. Key Findings\n"
        "   - Bullet list of the most important results, clearly labeled.\n\n"
        "3. Risks & Concerns\n"
        "   - Bullet list of any abnormal values, red flags, or follow-up issues.\n\n"
        "4. Recommended Actions\n"
        "   - Clear, actionable recommendations (bullets), focusing on what the reader should do next.\n\n"
        "5. Notes & Context\n"
        "   - Any caveats, limitations, or assumptions.\n\n"
        "Use headings, sub-headings, and bullets. Be explicit and concrete.\n\n"
        f"Report:\n{text}"
    )


async def send_summary_email(recipient: str, subject: str, body: str) -> bool:
    if not BREVO_API_KEY or not EMAIL_FROM:
        logger.warning("Email not configured (BREVO_API_KEY or EMAIL_FROM missing).")
        return False

    url = "https://api.brevo.com/v3/smtp/email"
    payload = {
        "sender": {"email": EMAIL_FROM},
        "to": [{"email": recipient}],
        "subject": subject,
        "textContent": body,
    }
    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(url, json=payload, headers=headers)
        if r.status_code in (200, 201, 202):
            logger.info(f"Summary email sent to {recipient}")
            return True
        else:
            logger.warning(f"Brevo email error {r.status_code}: {r.text}")
            return False
    except Exception as e:
        logger.exception(f"Error sending email via Brevo: {e}")
        return False


@app.post("/summarize", response_model=SummarizeResponse)
async def summarize(req: SummarizeRequest):
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OpenAI is not configured")

    if not req.text.strip():
        raise HTTPException(status_code=400, detail="No text provided to summarize")

    prompt = build_prompt(req.plan, req.text)

    try:
        completion = await openai.ChatCompletion.acreate(
            model="gpt-4o-mini",  # adjust to the model you want
            messages=[
                {
                    "role": "system",
                    "content": "You summarize long reports into clear, structured outputs.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )
        summary = completion.choices[0].message["content"].strip()
    except Exception as e:
        logger.exception("Error calling OpenAI")
        raise HTTPException(status_code=500, detail=f"Error generating summary: {e}")

    emailed = False
    if req.recipient_email:
        emailed = await send_summary_email(
            req.recipient_email, "AI-Generated Business Summary", summary
        )

    return SummarizeResponse(summary=summary, emailed=emailed)
