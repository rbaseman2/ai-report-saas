import json
import logging
import os
from typing import List

import stripe
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from pydantic import BaseModel

# ---------- Logging ----------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- Environment ----------

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
if not STRIPE_SECRET_KEY:
    raise RuntimeError("STRIPE_SECRET_KEY is not set")

stripe.api_key = STRIPE_SECRET_KEY

STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

PRICE_BASIC = os.environ.get("PRICE_BASIC")
PRICE_PRO = os.environ.get("PRICE_PRO")
PRICE_ENTERPRISE = os.environ.get("PRICE_ENTERPRISE")

SUCCESS_URL = os.environ.get("SUCCESS_URL")  # e.g. https://your-app.onrender.com/Billing
CANCEL_URL = os.environ.get("CANCEL_URL", SUCCESS_URL or "")

if not all([PRICE_BASIC, PRICE_PRO, PRICE_ENTERPRISE]):
    logger.warning(
        "One or more Stripe price IDs (PRICE_BASIC/PRO/ENTERPRISE) are not set."
    )

PLAN_TO_PRICE = {
    "basic": PRICE_BASIC,
    "pro": PRICE_PRO,
    "enterprise": PRICE_ENTERPRISE,
}

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Will pick up OPENAI_API_KEY from the environment
client = OpenAI()

# ---------- FastAPI app ----------

app = FastAPI(title="AI Report Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # you can tighten this to your frontend URL if you like
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Pydantic models ----------


class SummarizeRequest(BaseModel):
    text: str
    email: str | None = None


class SummarizeResponse(BaseModel):
    summary: str


class CheckoutRequest(BaseModel):
    email: str
    plan: str  # "basic", "pro", "enterprise"


class CheckoutResponse(BaseModel):
    checkout_url: str


# ---------- Health ----------


@app.get("/health")
async def health():
    return {"status": "ok"}


# ---------- Business summarization ----------

BUSINESS_SYSTEM_PROMPT = (
    "You are an AI assistant that summarizes business documents for non-technical readers. "
    "Your audience might be clients, managers, or stakeholders who need a clear, concise view "
    "of the key points. Focus on:\n"
    "- Main objectives and context\n"
    "- Key insights, decisions, or results\n"
    "- Risks, issues, or concerns (if any)\n"
    "- Recommended next steps or actions\n\n"
    "Write in clear, professional language. Avoid jargon where possible, and keep the tone "
    "neutral and business-friendly."
)

# Rough safety limit for characters per chunk.
# This keeps each OpenAI request within a safe token window.
CHARS_PER_CHUNK = 12000
MAX_CHUNKS = 8  # safety cap so we don't accidentally fire hundreds of requests


def _summarize_chunk(text: str, part_idx: int | None = None, total_parts: int | None = None) -> str:
    """
    Summarize a single chunk of text with the business system prompt.
    """
    user_content = text
    if part_idx is not None and total_parts is not None:
        user_content = (
            f"This is part {part_idx} of {total_parts} of a longer business document.\n\n"
            f"{text}"
        )

    completion = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": BUSINESS_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.3,
        max_tokens=800,
    )

    return (completion.choices[0].message.content or "").strip()


def _chunk_text(text: str, max_chars: int) -> List[str]:
    """
    Split a long string into chunks of at most max_chars characters,
    trying to split on paragraph boundaries where possible.
    """
    if len(text) <= max_chars:
        return [text]

    chunks: List[str] = []
    start = 0
    length = len(text)

    while start < length and len(chunks) < MAX_CHUNKS:
        end = min(start + max_chars, length)

        # Try to back up to the last newline to avoid chopping paragraphs in half
        newline_pos = text.rfind("\n", start, end)
        if newline_pos != -1 and newline_pos > start + max_chars // 2:
            end = newline_pos

        chunks.append(text[start:end])
        start = end

    # If there is still text left beyond MAX_CHUNKS, we ignore it for now.
    # You could also choose to merge it into the last chunk instead.
    return chunks


@app.post("/summarize", response_model=SummarizeResponse)
async def summarize(body: SummarizeRequest):
    """
    Summarize a business document. For large inputs, we:
      1) Split the text into chunks.
      2) Summarize each chunk.
      3) Ask the model to combine those partial summaries into one final summary.
    """
    raw_text = body.text or ""
    text = raw_text.strip()

    if not text:
        raise HTTPException(status_code=400, detail="Text is empty")

    try:
        # 1) Split into chunks if needed
        chunks = _chunk_text(text, CHARS_PER_CHUNK)
        logger.info("Summarizing document with %d chunk(s)", len(chunks))

        # 2) If it's short enough, just do a single call
        if len(chunks) == 1:
            summary = _summarize_chunk(chunks[0])
            return SummarizeResponse(summary=summary)

        # 3) Otherwise summarize each chunk separately
        partial_summaries: List[str] = []
        total_parts = len(chunks)

        for idx, chunk in enumerate(chunks, start=1):
            part_summary = _summarize_chunk(chunk, part_idx=idx, total_parts=total_parts)
            partial_summaries.append(f"Part {idx} summary:\n{part_summary}")

        # 4) Combine partial summaries into one concise business summary
        combine_system_prompt = (
            "You are an expert business analyst. You will be given summaries of parts of a larger "
            "business document. Combine them into a single, clear summary that a non-technical client "
            "or business stakeholder can quickly understand.\n\n"
            "Your output should be 8–12 short bullet points under clear headings if appropriate. "
            "Avoid repeating the same information."
        )

        combined_input = "\n\n".join(partial_summaries)

        completion = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": combine_system_prompt},
                {"role": "user", "content": combined_input},
            ],
            temperature=0.3,
            max_tokens=900,
        )

        final_summary = (completion.choices[0].message.content or "").strip()
        return SummarizeResponse(summary=final_summary)

    except Exception as exc:
        logger.exception("Error during OpenAI summarization")
        # Surface a friendly message; log has the details.
        raise HTTPException(
            status_code=500,
            detail="Backend summarization error. Please check the server logs for details.",
        ) from exc


# ---------- Stripe checkout ----------


@app.post("/create-checkout-session", response_model=CheckoutResponse)
async def create_checkout_session(body: CheckoutRequest):
    plan = body.plan.lower()
    price_id = PLAN_TO_PRICE.get(plan)

    if not price_id:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {body.plan}")

    if not SUCCESS_URL:
        raise HTTPException(
            status_code=500,
            detail="SUCCESS_URL is not configured in the backend environment.",
        )

    try:
        # Stripe Checkout for subscriptions
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer_email=body.email,
            line_items=[
                {
                    "price": price_id,
                    "quantity": 1,
                }
            ],
            success_url=f"{SUCCESS_URL}?status=success&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{CANCEL_URL}?status=cancelled" if CANCEL_URL else SUCCESS_URL,
            allow_promotion_codes=True,  # enables coupon / promo code field
            billing_address_collection="auto",
        )

        logger.info(
            "Created checkout session %s for %s (%s)", session.id, body.email, plan
        )
        return CheckoutResponse(checkout_url=session.url)
    except Exception as exc:
        logger.exception("Error creating Stripe Checkout session")
        raise HTTPException(status_code=500, detail=str(exc))


# ---------- Stripe webhook ----------


@app.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
):
    """
    Basic Stripe webhook handler.
    Right now this just verifies the signature (if configured) and logs the event.
    You can extend this later to store subscription status in a database.
    """
    payload = await request.body()

    try:
        if STRIPE_WEBHOOK_SECRET and stripe_signature:
            event = stripe.Webhook.construct_event(
                payload=payload,
                sig_header=stripe_signature,
                secret=STRIPE_WEBHOOK_SECRET,
            )
        else:
            # No verification – for local testing only
            event = json.loads(payload.decode("utf-8"))
    except Exception as exc:
        logger.exception("Failed to parse Stripe webhook")
        raise HTTPException(status_code=400, detail=f"Webhook error: {exc}")

    event_type = event.get("type")
    logger.info("Received Stripe event: %s", event_type)

    # Example places to extend logic:
    # - checkout.session.completed
    # - customer.subscription.updated
    # - customer.subscription.deleted

    return {"received": True}
