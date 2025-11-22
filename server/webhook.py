# server/webhook.py

import os
import logging
from typing import Optional, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

import stripe
from openai import OpenAI

# ---------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logging.warning("OPENAI_API_KEY is not set – /summarize will fail.")
client = OpenAI(api_key=OPENAI_API_KEY)

# Stripe
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
if not STRIPE_SECRET_KEY:
    logging.warning("STRIPE_SECRET_KEY is not set – /create-checkout-session will fail.")
stripe.api_key = STRIPE_SECRET_KEY

PRICE_BASIC = os.getenv("STRIPE_BASIC_PRICE_ID")      # e.g. price_123
PRICE_PRO = os.getenv("STRIPE_PRO_PRICE_ID")          # e.g. price_456
PRICE_ENTERPRISE = os.getenv("STRIPE_ENTERPRISE_PRICE_ID")  # e.g. price_789

SUCCESS_URL = os.getenv(
    "STRIPE_SUCCESS_URL",
    "https://ai-report-saas.onrender.com/Billing",
)
CANCEL_URL = os.getenv(
    "STRIPE_CANCEL_URL",
    "https://ai-report-saas.onrender.com/Billing",
)

PRICE_MAP = {
    "basic": PRICE_BASIC,
    "pro": PRICE_PRO,
    "enterprise": PRICE_ENTERPRISE,
}

# ---------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------

app = FastAPI(title="AI Report Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # you can tighten this later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------


class SummarizeRequest(BaseModel):
    text: str
    max_words: Optional[int] = 400
    tone: Optional[str] = "professional, clear, concise"
    audience: Optional[str] = "non-technical business stakeholders"
    bullets: Optional[bool] = True


class SummarizeResponse(BaseModel):
    summary: str


PlanType = Literal["basic", "pro", "enterprise"]


class CheckoutRequest(BaseModel):
    plan: PlanType
    email: EmailStr


class CheckoutResponse(BaseModel):
    checkout_url: str


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def build_business_prompt(req: SummarizeRequest) -> str:
    """Prompt that creates a business-oriented summary."""
    style = req.tone or "professional, clear, concise"
    audience = req.audience or "non-technical business stakeholders"
    max_words = req.max_words or 400

    bullets_instruction = """
    - Start with a short 1–2 sentence overview.
    - Then provide a bulleted list of key points, risks, and recommended actions.
    """.strip() if req.bullets else """
    - Write as a short narrative summary, with clear paragraphs.
    """.strip()

    prompt = f"""
You are an AI assistant that converts long, complex business documents into short,
client-ready summaries.

Write a summary that a **{audience}** can quickly skim and understand.

Style:
- {style}
- Focus on decisions, risks, and next steps.
- Avoid jargon when possible.

Output format:
{bullets_instruction}

Limit the answer to **about {max_words} words**.

Here is the source content:

\"\"\"{req.text}\"\"\"
""".strip()

    return prompt


def call_openai(prompt: str) -> str:
    """Call the OpenAI Responses API (gpt-4.1-mini)."""
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured on the server.")

    try:
        response = client.responses.create(
            model="gpt-4.1-mini",
            input=prompt,
            max_output_tokens=800,
        )
        # Responses API structure: response.output[0].content[0].text
        output = response.output[0].content[0].text  # type: ignore[attr-defined]
        return output.strip()
    except Exception as e:
        logger.exception("Error calling OpenAI: %s", e)
        raise


# ---------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/summarize", response_model=SummarizeResponse)
def summarize(req: SummarizeRequest):
    """Generate a business-friendly summary from raw text."""
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="No text provided for summarization.")

    prompt = build_business_prompt(req)

    try:
        summary = call_openai(prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI error: {e}")

    return SummarizeResponse(summary=summary)


@app.post("/create-checkout-session", response_model=CheckoutResponse)
def create_checkout_session(req: CheckoutRequest):
    """
    Create a Stripe Checkout session for a subscription plan.

    Frontend should POST JSON:

        {
            "plan": "basic" | "pro" | "enterprise",
            "email": "user@example.com"
        }
    """
    if not STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=500,
            detail="Stripe is not configured on the server.",
        )

    price_id = PRICE_MAP.get(req.plan)
    if not price_id:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {req.plan}")

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
            customer_email=req.email,
            success_url=(
                f"{SUCCESS_URL}"
                f"?plan={req.plan}&checkout_session_id={{CHECKOUT_SESSION_ID}}"
            ),
            cancel_url=CANCEL_URL,
            allow_promotion_codes=True,
            automatic_tax={"enabled": True},
            metadata={
                "plan": req.plan,
                "email": req.email,
            },
        )
    except stripe.error.StripeError as e:
        logger.exception("Stripe error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("Unexpected error creating checkout session: %s", e)
        raise HTTPException(status_code=500, detail="Failed to create checkout session.")

    if not getattr(session, "url", None):
        raise HTTPException(status_code=500, detail="Stripe did not return a checkout URL.")

    return CheckoutResponse(checkout_url=session.url)


# Optional: placeholder for Stripe webhooks (not strictly needed for checkout to work)
@app.post("/stripe-webhook")
async def stripe_webhook():
    # You can implement event handling here later (invoice.paid, customer.subscription.updated, etc.)
    return {"received": True}
