import os
import sqlite3
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import stripe
from openai import OpenAI

# ------------- ENV / CONFIG ------------ #

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

PRICE_BASIC = os.getenv("PRICE_BASIC")
PRICE_PRO = os.getenv("PRICE_PRO")
PRICE_ENTERPRISE = os.getenv("PRICE_ENTERPRISE")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

DB_PATH = os.getenv("SUBSCRIPTION_DB_PATH", "subscriptions.db")

PLAN_BY_PRICE = {
    PRICE_BASIC: "basic",
    PRICE_PRO: "pro",
    PRICE_ENTERPRISE: "enterprise",
}

# ------------- DB SETUP ------------ #


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS subscriptions (
            email TEXT PRIMARY KEY,
            plan TEXT NOT NULL,
            status TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def upsert_subscription(email: str, plan: str, status: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO subscriptions(email, plan, status)
        VALUES (?, ?, ?)
        ON CONFLICT(email) DO UPDATE SET
            plan=excluded.plan,
            status=excluded.status
        """,
        (email, plan, status),
    )
    conn.commit()
    conn.close()


def get_subscription(email: str) -> Optional[dict]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT email, plan, status FROM subscriptions WHERE email = ?", (email,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {"email": row[0], "plan": row[1], "status": row[2]}


init_db()

# ------------- FASTAPI APP ------------ #

app = FastAPI(title="AI Report Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later if you want
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------- MODELS ------------ #

class CheckoutRequest(BaseModel):
    email: str
    plan: str  # 'basic' | 'pro' | 'enterprise'


class SummarizeRequest(BaseModel):
    email: str
    text: str


# ------------- ROUTES ------------ #

@app.get("/health")
def health():
    return {"ok": True}


@app.get("/subscription-status")
def subscription_status(email: str):
    """
    Return subscription info for a given email.
    If none found, treat as free.
    """
    sub = get_subscription(email)
    if not sub:
        return {"email": email, "plan": "free", "active": False}

    active = sub["status"] == "active"
    return {"email": email, "plan": sub["plan"], "active": active}


@app.post("/create-checkout-session")
def create_checkout_session(payload: CheckoutRequest):
    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="Stripe is not configured.")

    plan = payload.plan.lower()
    price_id = None

    if plan == "basic":
        price_id = PRICE_BASIC
    elif plan == "pro":
        price_id = PRICE_PRO
    elif plan == "enterprise":
        price_id = PRICE_ENTERPRISE

    if not price_id:
        raise HTTPException(status_code=400, detail="Invalid plan selected.")

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
            success_url=os.getenv("SUCCESS_URL", "") + "?status=success",
            cancel_url=os.getenv("CANCEL_URL", "") + "?status=cancel",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {"checkout_url": session.url}


@app.post("/webhook")
async def stripe_webhook(request: Request):
    """
    Stripe webhook to mark subscriptions as active/cancelled.
    """
    if not WEBHOOK_SECRET:
        # If you haven't configured the secret, ignore verification
        payload = await request.body()
        event = stripe.Event.construct_from(request.json(), stripe.api_key)
    else:
        payload = await request.body()
        sig_header = request.headers.get("stripe-signature", "")
        try:
            event = stripe.Webhook.construct_event(
                payload=payload, sig_header=sig_header, secret=WEBHOOK_SECRET
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    event_type = event["type"]
    data = event["data"]["object"]

    email = data.get("customer_email") or data.get("customer_details", {}).get("email")
    status = None
    plan = None

    if event_type == "checkout.session.completed":
        # Subscription will be created; treat as active once checkout completes.
        price_id = None
        if data.get("subscription"):
            sub = stripe.Subscription.retrieve(data["subscription"])
            if sub["items"]["data"]:
                price_id = sub["items"]["data"][0]["price"]["id"]
        elif data.get("line_items"):
            # Optional fallback
            pass

        plan = PLAN_BY_PRICE.get(price_id, "basic")
        status = "active"

    elif event_type in ("customer.subscription.deleted", "customer.subscription.canceled"):
        # Mark as inactive
        price_id = data["items"]["data"][0]["price"]["id"]
        plan = PLAN_BY_PRICE.get(price_id, "basic")
        status = "canceled"

    if email and plan and status:
        upsert_subscription(email=email, plan=plan, status=status)

    return {"received": True}


# ------------- SUMMARIZATION ------------ #

SYSTEM_PROMPT = """
You are an expert business communicator.

A user will send you long, sometimes messy text: reports, emails, meeting notes,
technical documentation, or research.

Your job is to:
- Extract the key points and explain them in clear, simple language.
- Focus on what a non-technical client, manager, or business stakeholder needs to know.
- Highlight important decisions, risks, and next steps.
- Avoid medical or clinical framing. This is general business content.

Write the summary in short paragraphs and bullet points, using a neutral, professional tone.
Do not invent facts that are not supported by the input.
"""


@app.post("/summarize")
def summarize(payload: SummarizeRequest):
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OpenAI API key is not configured.")

    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="No text provided for summarization.")

    try:
        completion = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0.2,
        )
        summary = completion.choices[0].message.content.strip()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {"summary": summary}

