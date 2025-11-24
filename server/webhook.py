# server/webhook.py

import os
import logging
from typing import Literal, Optional, Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
import stripe
from openai import OpenAI

# --------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --------------------------------------------------------------------
# Environment & configuration
# --------------------------------------------------------------------
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
if not STRIPE_SECRET_KEY:
    logger.warning("STRIPE_SECRET_KEY is not set in the environment")

stripe.api_key = STRIPE_SECRET_KEY

FRONTEND_URL = os.getenv("FRONTEND_URL", "https://ai-report-saas.onrender.com")

SUCCESS_URL = os.getenv("SUCCESS_URL") or f"{FRONTEND_URL}/Upload_Data"
CANCEL_URL = os.getenv("CANCEL_URL") or f"{FRONTEND_URL}/Billing"

PRICE_MAP: Dict[str, Optional[str]] = {
    "basic": os.getenv("PRICE_BASIC"),
    "pro": os.getenv("PRICE_PRO"),
    "enterprise": os.getenv("PRICE_ENTERPRISE"),
}

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY is not set in the environment")

openai_client = OpenAI(api_key=OPENAI_API_KEY)

# --------------------------------------------------------------------
# FastAPI app & CORS
# --------------------------------------------------------------------
app = FastAPI(title="AI Report Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        FRONTEND_URL,
        FRONTEND_URL.rstrip("/"),
        "https://ai-report-saas.onrender.com",
        "http://localhost:8501",
        "http://localhost:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------------------------
# Pydantic models
# --------------------------------------------------------------------
class CheckoutRequest(BaseModel):
    plan: Literal["basic", "pro", "enterprise"]
    email: EmailStr


class CheckoutResponse(BaseModel):
    checkout_url: str


class SummaryRequest(BaseModel):
    text: str
    email: Optional[EmailStr] = None
    plan: Optional[Literal["free", "basic", "pro", "enterprise"]] = None


class SummaryResponse(BaseModel):
    summary: str


# --------------------------------------------------------------------
# Utility functions
# --------------------------------------------------------------------
def get_price_id_for_plan(plan: str) -> str:
    price_id = PRICE_MAP.get(plan)
    if not price_id:
        logger.error("Price ID not configured for plan '%s'", plan)
        raise HTTPException(
            status_code=500,
            detail=f"Stripe price ID not configured for plan '{plan}'. "
                   f"Set PRICE_{plan.upper()} in the backend environment.",
        )
    return price_id


# --------------------------------------------------------------------
# Health / debug endpoints
# --------------------------------------------------------------------
@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "frontend_url": FRONTEND_URL}


@app.get("/debug-env")
def debug_env() -> Dict[str, Any]:
    """
    Simple debug endpoint. Safe-ish because it only tells you whether
    keys are present, not their values.
    """
    return {
        "has_stripe_secret": bool(STRIPE_SECRET_KEY),
        "has_openai_key": bool(OPENAI_API_KEY),
        "success_url": SUCCESS_URL,
        "cancel_url": CANCEL_URL,
        "price_basic_set": bool(PRICE_MAP["basic"]),
        "price_pro_set": bool(PRICE_MAP["pro"]),
        "price_enterprise_set": bool(PRICE_MAP["enterprise"]),
    }


# --------------------------------------------------------------------
# Stripe: create checkout session
# --------------------------------------------------------------------
@app.post("/create-checkout-session", response_model=CheckoutResponse)
def create_checkout_session(body: CheckoutRequest) -> CheckoutResponse:
    """
    Create a Stripe Checkout session for a subscription plan.

    The frontend should POST:
    {
        "plan": "basic" | "pro" | "enterprise",
        "email": "user@example.com"
    }
    """
    logger.info("Creating checkout session for plan=%s, email=%s", body.plan, body.email)

    if not STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=500,
            detail="Stripe is not configured. STRIPE_SECRET_KEY is missing.",
        )

    price_id = get_price_id_for_plan(body.plan)

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            customer_email=body.email,
            line_items=[{"price": price_id, "quantity": 1}],
            # This enables coupon / promotion code entry on the Stripe page
            allow_promotion_codes=True,
            success_url=f"{SUCCESS_URL}?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=CANCEL_URL,
        )
        logger.info("Stripe Checkout session created: %s", session.id)
        return CheckoutResponse(checkout_url=session.url)
    except Exception as e:
        logger.exception("Error creating Stripe checkout session")
        raise HTTPException(
            status_code=500,
            detail=f"Stripe error while creating checkout session: {e}",
        )


# --------------------------------------------------------------------
# OpenAI summarization endpoint
# --------------------------------------------------------------------
@app.post("/summarize", response_model=SummaryResponse)
def summarize(body: SummaryRequest) -> SummaryResponse:
    """
    Turn a long document or report into a clear, business-friendly summary.
    """
    if not OPENAI_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY is not configured on the backend.",
        )

    logger.info(
        "Summarizing text for email=%s, plan=%s, length=%d chars",
        body.email,
        body.plan,
        len(body.text),
    )

    # Slightly different depth based on plan (optional)
    depth_hint = {
        "free": "brief, high-level",
        "basic": "clear but concise",
        "pro": "detailed with key risks, decisions, and action items",
        "enterprise": "executive-ready with risks, decisions, owners, and next steps",
    }.get(body.plan or "free", "clear but concise")

    prompt = f"""
You are an expert business analyst. Your job is to turn dense text into a
client-ready executive summary that a non-technical business stakeholder can
quickly skim and understand.

Write a {depth_hint} summary using headings and bullets where helpful.

Focus on:
- Key points and insights
- Risks, constraints, or dependencies
- Decisions made (or decisions still needed)
- Concrete next steps and owners if they are mentioned

Avoid medical language or patient-specific phrasing. Treat this as a business
or professional document.

Source text:
\"\"\"{body.text}\"
\"\"\"
    """.strip()

    try:
        # Uses the new OpenAI client (1.x)
        result = openai_client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            input=prompt,
        )

        # Extract text from the responses API
        output = result.output[0].content[0].text  # type: ignore[attr-defined]
        return SummaryResponse(summary=output.strip())
    except Exception as e:
        logger.exception("Error generating summary with OpenAI")
        raise HTTPException(
            status_code=500,
            detail=f"Error generating summary: {e}",
        )
