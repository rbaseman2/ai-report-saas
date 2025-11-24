import os
from typing import Optional, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import stripe
from openai import OpenAI

# -----------------------------------------------------------------------------
# Environment + Stripe/OpenAI setup
# -----------------------------------------------------------------------------

# Stripe keys
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY")

if not STRIPE_SECRET_KEY:
    raise RuntimeError("Missing STRIPE_SECRET_KEY in environment")

stripe.api_key = STRIPE_SECRET_KEY

# Price IDs (these names match your Render env screenshot)
PRICE_BASIC = os.getenv("PRICE_BASIC")
PRICE_PRO = os.getenv("PRICE_PRO")
PRICE_ENTERPRISE = os.getenv("PRICE_ENTERPRISE")

PLAN_PRICES: Dict[str, Optional[str]] = {
    "basic": PRICE_BASIC,
    "pro": PRICE_PRO,
    "enterprise": PRICE_ENTERPRISE,
}

# URLs
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://ai-report-saas.onrender.com")
CANCEL_URL = os.getenv("CANCEL_URL", FRONTEND_URL + "/Billing")

# OpenAI client
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("Missing OPENAI_API_KEY in environment")

oai_client = OpenAI(api_key=OPENAI_API_KEY)

# -----------------------------------------------------------------------------
# FastAPI app + CORS
# -----------------------------------------------------------------------------

app = FastAPI(title="AI Report Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        FRONTEND_URL,
        FRONTEND_URL.rstrip("/"),
        "*",  # keep this if you want to avoid CORS headaches while testing
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Pydantic models
# -----------------------------------------------------------------------------

class CheckoutRequest(BaseModel):
    plan: str
    email: str


class CheckoutResponse(BaseModel):
    checkout_url: str


class SummarizeRequest(BaseModel):
    text: str
    email: Optional[str] = None
    plan: Optional[str] = None  # "free", "basic", "pro", "enterprise"


class SummarizeResponse(BaseModel):
    summary: str


# -----------------------------------------------------------------------------
# Health/info endpoints
# -----------------------------------------------------------------------------

@app.get("/health")
def health():
    """Simple health check."""
    return {"status": "ok"}


@app.get("/info")
def info():
    """Minimal info endpoint to confirm env wiring (no secrets!)."""
    return {
        "frontend_url": FRONTEND_URL,
        "has_stripe_secret": bool(STRIPE_SECRET_KEY),
        "has_publishable_key": bool(STRIPE_PUBLISHABLE_KEY),
        "has_price_basic": bool(PRICE_BASIC),
        "has_price_pro": bool(PRICE_PRO),
        "has_price_enterprise": bool(PRICE_ENTERPRISE),
    }


# -----------------------------------------------------------------------------
# Checkout session creation
# -----------------------------------------------------------------------------

@app.post("/create-checkout-session", response_model=CheckoutResponse)
async def create_checkout_session(payload: CheckoutRequest):
    """
    Create a Stripe Checkout session for a subscription plan.

    The frontend should POST JSON like:
    {
        "plan": "basic" | "pro" | "enterprise",
        "email": "user@example.com"
    }
    """
    plan = payload.plan.lower()
    email = payload.email.strip()

    if plan not in PLAN_PRICES:
        raise HTTPException(status_code=400, detail=f"Invalid plan '{plan}'")

    price_id = PLAN_PRICES[plan]
    if not price_id:
        # Config error – this should be a 500 so you notice it immediately
        raise HTTPException(
            status_code=500,
            detail=(
                f"Stripe price ID not configured for plan '{plan}'. "
                f"Set PRICE_{plan.upper()} in the backend environment."
            ),
        )

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            line_items=[
                {
                    "price": price_id,
                    "quantity": 1,
                }
            ],
            customer_email=email,
            success_url=f"{FRONTEND_URL}/Billing?status=success&plan={plan}",
            cancel_url=CANCEL_URL,
        )
    except stripe.error.StripeError as e:
        # Anything from Stripe becomes a 502 with a readable message
        raise HTTPException(
            status_code=502,
            detail=f"Stripe error: {str(e)}",
        )

    return CheckoutResponse(checkout_url=session.url)


# -----------------------------------------------------------------------------
# Summarization endpoint used by the Upload_Data page
# -----------------------------------------------------------------------------

BASE_SYSTEM_PROMPT = (
    "You are an AI assistant that turns long business documents, reports, and "
    "meeting notes into clear, concise summaries.\n\n"
    "Write for a non-technical client or business stakeholder. "
    "Use short sections with headings like 'Key Insights', 'Risks', "
    "'Recommended Actions', and 'Opportunities' when appropriate.\n\n"
    "Be specific and actionable. Avoid medical or clinical language. "
    "Do not invent facts that are not supported by the text."
)

@app.post("/summarize", response_model=SummarizeResponse)
async def summarize(req: SummarizeRequest):
    """
    Summarize a long text into a business-friendly summary.

    The frontend typically sends:
    {
        "text": "<very long text>",
        "email": "user@example.com",   # optional
        "plan": "free" | "basic" | "pro" | "enterprise"
    }
    """
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text to summarize is empty.")

    # You can branch on plan here later (longer summaries for paying users, etc.)
    try:
        completion = oai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": BASE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Summarize the following document into a clear, "
                        "client-ready overview with key points, risks, and "
                        "recommended next steps:\n\n" + text
                    ),
                },
            ],
            temperature=0.4,
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"OpenAI summarization failed: {str(e)}",
        )

    summary_text = completion.choices[0].message.content.strip()
    return SummarizeResponse(summary=summary_text)
