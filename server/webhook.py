import os
from typing import Optional

import stripe
from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    UploadFile,
    File,
    Form,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI

# ----- basic app & CORS -------------------------------------------------------

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # front-end is public on Render
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----- Stripe / OpenAI setup --------------------------------------------------

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

PRICE_IDS = {
    "basic": os.getenv("PRICE_BASIC"),
    "pro": os.getenv("PRICE_PRO"),
    "enterprise": os.getenv("PRICE_ENTERPRISE"),
}

FRONTEND_URL = os.getenv(
    "FRONTEND_URL", "https://ai-report-saas.onrender.com"
)

# OpenAI for summarization
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ----- models -----------------------------------------------------------------


class CheckoutRequest(BaseModel):
    plan: str  # "basic" | "pro" | "enterprise"
    email: str


# ----- health -----------------------------------------------------------------


@app.get("/health")
async def health():
    return {"status": "ok"}


# ----- create checkout session ------------------------------------------------


@app.post("/create-checkout-session")
async def create_checkout_session(payload: CheckoutRequest):
    plan = payload.plan.lower()
    email = payload.email.strip()

    if plan not in PRICE_IDS:
        raise HTTPException(status_code=400, detail="Invalid plan")

    price_id = PRICE_IDS[plan]
    if not price_id:
        raise HTTPException(
            status_code=500,
            detail=f"Stripe price ID not configured for plan '{plan}'. "
            f"Set PRICE_{plan.upper()} in the environment.",
        )

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer_email=email,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=(
                f"{FRONTEND_URL}/Billing"
                "?status=success&session_id={{CHECKOUT_SESSION_ID}}"
            ),
            cancel_url=f"{FRONTEND_URL}/Billing?status=cancelled",
            allow_promotion_codes=True,
        )
    except stripe.error.StripeError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Stripe error while creating checkout session: {e.user_message}",
        )

    return {"checkout_url": session.url}


# ----- helper: map Stripe subscription -> plan & limits ----------------------


def _plan_from_price_id(price_id: str) -> str:
    if price_id == PRICE_IDS["basic"]:
        return "basic"
    if price_id == PRICE_IDS["pro"]:
        return "pro"
    if price_id == PRICE_IDS["enterprise"]:
        return "enterprise"
    return "free"


def _limits_for_plan(plan: str) -> dict:
    if plan == "basic":
        return {"max_documents": 5, "max_chars": 200_000}
    if plan == "pro":
        return {"max_documents": 30, "max_chars": 1_000_000}
    if plan == "enterprise":
        # treat as "effectively unlimited" for now
        return {"max_documents": 10_000, "max_chars": 50_000_000}
    # free
    return {"max_documents": 5, "max_chars": 200_000}


# ----- subscription status ----------------------------------------------------


@app.get("/subscription-status")
async def subscription_status(email: str):
    """
    Given an email, look up the customer & active subscription in Stripe
    and return the plan + limits.

    404 means "no active subscription" – the front-end should treat that
    as Free plan without showing an error.
    """
    email = email.strip()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    try:
        customers = stripe.Customer.list(email=email, limit=1).data
        if not customers:
            raise HTTPException(status_code=404, detail="No customer for this email")

        customer = customers[0]
        subs = stripe.Subscription.list(
            customer=customer.id,
            status="active",
            limit=1,
        ).data

        if not subs:
            raise HTTPException(status_code=404, detail="No active subscription")

        sub = subs[0]
        item = sub["items"]["data"][0]
        price_id = item["price"]["id"]
        plan = _plan_from_price_id(price_id)
        limits = _limits_for_plan(plan)

        return {"plan": plan, **limits}
    except HTTPException:
        raise
    except stripe.error.StripeError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Stripe error while checking subscription: {e.user_message}",
        )


# ----- summarization ----------------------------------------------------------


@app.post("/summarize")
async def summarize(
    email: str = Form(...),
    text: Optional[str] = Form(""),
    file: Optional[UploadFile] = File(None),
):
    """
    Summarize uploaded content for the given user.
    This path is what the Upload_Data page calls.
    """

    # 1) build the raw text to summarize
    raw_text = text or ""

    if file is not None:
        # currently handle small text / csv-ish files; PDF support can be
        # added back later if needed.
        file_bytes = await file.read()
        try:
            file_text = file_bytes.decode("utf-8", errors="ignore")
        except Exception:
            raise HTTPException(
                status_code=400,
                detail="Unable to decode uploaded file as text.",
            )
        raw_text += "\n\n" + file_text

    raw_text = raw_text.strip()
    if not raw_text:
        raise HTTPException(status_code=400, detail="No content to summarize.")

    # clip very large inputs to avoid hitting token limits
    MAX_CHARS = 40_000
    if len(raw_text) > MAX_CHARS:
        raw_text = raw_text[:MAX_CHARS] + "\n\n[Truncated for summarization.]"

    prompt = (
        "You are an AI assistant that writes concise, business-friendly summaries. "
        "Summarize the following document into:\n\n"
        "1. 5-7 bullet-point key takeaways\n"
        "2. One short paragraph 'Executive Summary'\n"
        "3. 3-5 suggested next steps or action items.\n\n"
        "Document:\n"
        f"{raw_text}"
    )

    try:
        resp = client.responses.create(
            model="gpt-4o-mini",
            input=prompt,
        )
        # Responses API: take first output block of text
        output = resp.output[0].content[0].text
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error while generating summary: {e}"
        )

    return {"summary": output}
