import io
import logging
import os
from pathlib import Path
from typing import Literal, Optional

import stripe
from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

# -------- Logging --------
logger = logging.getLogger("ai-report-backend")
logging.basicConfig(level=logging.INFO)

# -------- Environment / Stripe config --------
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

STRIPE_PRICE_BASIC = os.environ.get("STRIPE_PRICE_BASIC")
STRIPE_PRICE_PRO = os.environ.get("STRIPE_PRICE_PRO")
STRIPE_PRICE_ENTERPRISE = os.environ.get("STRIPE_PRICE_ENTERPRISE")

FRONTEND_URL = os.environ.get("FRONTEND_URL", "")
SUCCESS_URL = os.environ.get(
    "SUCCESS_URL",
    f"{FRONTEND_URL.rstrip('/')}/Billing?status=success",
)
CANCEL_URL = os.environ.get(
    "CANCEL_URL",
    f"{FRONTEND_URL.rstrip('/')}/Billing?status=cancelled",
)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

if not STRIPE_SECRET_KEY:
    logger.warning("STRIPE_SECRET_KEY is not set – billing endpoints will fail.")

stripe.api_key = STRIPE_SECRET_KEY

# -------- OpenAI client (optional) --------
try:
    if OPENAI_API_KEY:
        from openai import OpenAI

        openai_client = OpenAI(api_key=OPENAI_API_KEY)
    else:
        openai_client = None
        logger.warning("OPENAI_API_KEY not set – /summarize will return a dummy summary.")
except Exception as e:
    logger.exception("Failed to initialize OpenAI client: %s", e)
    openai_client = None

# -------- FastAPI app --------
app = FastAPI(title="AI Report Backend", version="1.0.0")

# CORS so the Streamlit frontend can call this backend
origins = []
if FRONTEND_URL:
    origins.append(FRONTEND_URL)
else:
    # Fallback – useful while debugging
    origins.append("*")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------- Stripe helpers / models --------

PlanName = Literal["basic", "pro", "enterprise"]


class CheckoutRequest(BaseModel):
    plan: PlanName
    email: EmailStr


class CheckoutResponse(BaseModel):
    checkout_url: str


class SubscriptionStatusResponse(BaseModel):
    status: str
    plan: Optional[PlanName] = None
    current_period_end: Optional[int] = None  # Unix timestamp


class SummarizeResponse(BaseModel):
    summary: str


PLAN_TO_PRICE: dict[PlanName, Optional[str]] = {
    "basic": STRIPE_PRICE_BASIC,
    "pro": STRIPE_PRICE_PRO,
    "enterprise": STRIPE_PRICE_ENTERPRISE,
}

PRICE_TO_PLAN = {
    v: k for k, v in PLAN_TO_PRICE.items() if v is not None
}

# =========================================================
# Health
# =========================================================


@app.get("/health")
async def health():
    return {"status": "ok"}


# =========================================================
# Create checkout session
# =========================================================


@app.post("/create-checkout-session", response_model=CheckoutResponse)
async def create_checkout_session(payload: CheckoutRequest):
    """
    Create a Stripe Checkout Session for a subscription.

    The frontend only sends: { "plan": "basic|pro|enterprise", "email": "user@x.com" }.
    Coupon / promotion codes are handled directly on the Stripe Checkout page.
    """
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Stripe is not configured")

    price_id = PLAN_TO_PRICE.get(payload.plan)
    if not price_id:
        raise HTTPException(status_code=400, detail="Invalid plan selected")

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
            customer_email=payload.email,
            success_url=SUCCESS_URL + "&session_id={CHECKOUT_SESSION_ID}",
            cancel_url=CANCEL_URL,
            allow_promotion_codes=True,  # user can enter coupon on checkout page
        )
        logger.info(
            "Created checkout session %s for plan %s and email %s",
            session.id,
            payload.plan,
            payload.email,
        )
        return CheckoutResponse(checkout_url=session.url)
    except Exception as e:
        logger.exception("Error creating checkout session: %s", e)
        raise HTTPException(status_code=500, detail="Failed to create checkout session")


# =========================================================
# Stripe webhook
# =========================================================


@app.post("/webhook")
async def stripe_webhook(request: Request):
    """
    Stripe webhook endpoint.
    Used mainly so Stripe can notify us that a checkout completed or subscription changed.
    We *don't* store anything in a DB – we query live from Stripe in /subscription-status.
    """
    if not STRIPE_WEBHOOK_SECRET:
        logger.warning("STRIPE_WEBHOOK_SECRET not set – webhook not verified.")
        payload = await request.body()
        data = payload.decode("utf-8")
        logger.info("Received webhook payload (unverified): %s", data)
        return {"received": True}

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except stripe.error.SignatureVerificationError as e:
        logger.warning("Webhook signature verification failed: %s", e)
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        logger.exception("Error parsing Stripe webhook: %s", e)
        raise HTTPException(status_code=400, detail="Invalid payload")

    event_type = event["type"]
    logger.info("Received Stripe event: %s", event_type)

    # You can add custom handling here if you ever want to store state
    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        logger.info(
            "Checkout session completed: id=%s customer_email=%s",
            session.get("id"),
            session.get("customer_details", {}).get("email"),
        )
    elif event_type.startswith("customer.subscription."):
        subscription = event["data"]["object"]
        logger.info(
            "Subscription event %s: id=%s status=%s",
            event_type,
            subscription.get("id"),
            subscription.get("status"),
        )

    return {"received": True}


# =========================================================
# Subscription status lookup
# =========================================================


@app.get("/subscription-status", response_model=SubscriptionStatusResponse)
async def subscription_status(email: EmailStr):
    """
    Given an email, look up latest Stripe subscription (if any).

    Returns:
        { "status": "none" } if no subscription.
        Otherwise includes "status", "plan", and "current_period_end".
    """
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Stripe is not configured")

    try:
        # Find customer by email
        customers = stripe.Customer.list(email=email, limit=1)
        if not customers.data:
            return SubscriptionStatusResponse(status="none")

        customer = customers.data[0]
        customer_id = customer.id

        # Latest subscription for this customer
        subs = stripe.Subscription.list(
            customer=customer_id,
            status="all",
            limit=1,
        )

        if not subs.data:
            return SubscriptionStatusResponse(status="none")

        sub = subs.data[0]
        sub_dict = sub.to_dict()

        status = sub_dict.get("status", "unknown")

        # Extract price id from first item
        price_id = (
            (sub_dict.get("items") or {})
            .get("data", [{}])[0]
            .get("price", {})
            .get("id")
        )

        plan: Optional[PlanName] = PRICE_TO_PLAN.get(price_id)  # type: ignore

        current_period_end = sub_dict.get("current_period_end")  # may be None

        return SubscriptionStatusResponse(
            status=status,
            plan=plan,
            current_period_end=current_period_end,
        )
    except Exception as e:
        logger.exception("Error looking up subscription status: %s", e)
        # Don't crash the frontend – just say "none"
        return SubscriptionStatusResponse(status="none")


# =========================================================
# Summarization endpoint
# =========================================================


def _extract_text_from_uploaded_file(filename: str, data: bytes) -> str:
    """
    Basic text extractor. Handles txt/md/csv directly, tries PDF via pypdf if available,
    and falls back to raw decode for anything else.
    """
    suffix = Path(filename or "").suffix.lower()

    # Simple text-based files
    if suffix in {".txt", ".md", ".csv"}:
        return data.decode(errors="ignore")

    # Try to handle PDF if pypdf is installed
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(io.BytesIO(data))
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n".join(pages)
        except Exception as e:
            logger.warning("PDF extraction failed (%s), using raw decode.", e)
            return data.decode(errors="ignore")

    # Fallback – attempt to decode
    return data.decode(errors="ignore")


@app.post("/summarize", response_model=SummarizeResponse)
async def summarize(
    email: EmailStr = Form(...),
    text: str = Form(""),
    file: UploadFile = File(None),
):
    """
    Generate a business summary from uploaded file or pasted text.

    - Frontend posts multipart/form-data with:
        - email (who requested / will receive the summary)
        - text (optional plain text)
        - file (optional uploaded file)
    """
    try:
        content = text or ""

        if file is not None:
            file_bytes = await file.read()
            if not file_bytes:
                raise HTTPException(status_code=400, detail="Uploaded file is empty")
            content = _extract_text_from_uploaded_file(file.filename or "", file_bytes)

        if not content.strip():
            raise HTTPException(
                status_code=400,
                detail="No content provided (file or text required)",
            )

        # ---- Summarize with OpenAI if configured ----
        if openai_client is not None:
            prompt = (
                "You are an AI assistant that creates clear, concise, business-ready "
                "summaries from reports and documents.\n\n"
                "Summarize the following content into key insights, risks, and "
                "recommended next steps:\n\n"
                f"{content[:8000]}"
            )

            completion = openai_client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": "You write concise, structured summaries."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=600,
            )

            summary_text = completion.choices[0].message.content.strip()
        else:
            # Fallback if OpenAI isn't configured
            summary_text = (
                "AI summary is currently unavailable; "
                "here is a shortened preview of your content:\n\n"
                + content[:500]
                + ("..." if len(content) > 500 else "")
            )

        # You can plug in your Brevo/email sending here if you want to
        logger.info("Generated summary for %s (length=%d chars)", email, len(summary_text))

        return SummarizeResponse(summary=summary_text)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in /summarize: %s", e)
        raise HTTPException(status_code=500, detail="Failed to generate summary")


# ---------------------------------------------------------
# Optional: run locally with `python server/webhook.py`
# ---------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server.webhook:app", host="0.0.0.0", port=10000, reload=True)
