import os
import logging
from typing import Optional

import stripe
import requests
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

# -------------------------------------------------------------------
# App setup
# -------------------------------------------------------------------

app = FastAPI()
logging.basicConfig(level=logging.INFO)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------------
# Environment variables
# -------------------------------------------------------------------

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY") or os.getenv("STRIPE_API_KEY") or ""
stripe.api_key = STRIPE_SECRET_KEY

STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

SUCCESS_URL = os.getenv("SUCCESS_URL")
CANCEL_URL = os.getenv("CANCEL_URL")

STRIPE_PRICE_BASIC = os.getenv("STRIPE_PRICE_BASIC")
STRIPE_PRICE_PRO = os.getenv("STRIPE_PRICE_PRO")
STRIPE_PRICE_ENTERPRISE = os.getenv("STRIPE_PRICE_ENTERPRISE")

BREVO_API_KEY = os.getenv("BREVO_API_KEY")
BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL", "admin@robaisolutions.com")
BREVO_SENDER_NAME = os.getenv("BREVO_SENDER_NAME", "RobAI Solutions")

PLAN_TO_PRICE = {
    "basic": STRIPE_PRICE_BASIC,
    "pro": STRIPE_PRICE_PRO,
    "enterprise": STRIPE_PRICE_ENTERPRISE,
}

# -------------------------------------------------------------------
# Email helper (Brevo) – USED BY SUMMARY ONLY
# -------------------------------------------------------------------

async def send_email(to_email: str, subject: str, html_content: str):
    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json",
    }
    payload = {
        "sender": {
            "email": BREVO_SENDER_EMAIL,
            "name": BREVO_SENDER_NAME,
        },
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_content,
    }

    response = requests.post(url, json=payload, headers=headers)
    if response.status_code >= 300:
        raise RuntimeError(f"Brevo error: {response.text}")

# -------------------------------------------------------------------
# Models
# -------------------------------------------------------------------

class CheckoutRequest(BaseModel):
    plan: str
    email: EmailStr


class GenerateSummaryRequest(BaseModel):
    email: EmailStr
    recipient_email: EmailStr
    content: str

# -------------------------------------------------------------------
# Health
# -------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}

# -------------------------------------------------------------------
# Checkout (COUPONS ENABLED – UNCHANGED)
# -------------------------------------------------------------------

@app.post("/create-checkout-session")
async def create_checkout_session(req: CheckoutRequest):
    price_id = PLAN_TO_PRICE.get(req.plan)
    if not price_id:
        raise HTTPException(status_code=400, detail="Invalid plan")

    session = stripe.checkout.Session.create(
        mode="subscription",
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{SUCCESS_URL}?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=CANCEL_URL,
        customer_email=req.email,
        allow_promotion_codes=True,  # ✅ coupons preserved
    )

    logging.info(
        f"Checkout session {session.id} created for {req.email} ({req.plan})"
    )

    return {"checkout_url": session.url}

# -------------------------------------------------------------------
# Subscription status (USED BY BILLING PAGE)
# -------------------------------------------------------------------

@app.get("/subscription-status")
async def subscription_status(email: EmailStr):
    customers = stripe.Customer.list(email=email, limit=1)
    if not customers.data:
        return {"active": False, "plan": None}

    customer = customers.data[0]
    subs = stripe.Subscription.list(
        customer=customer.id,
        status="all",
        limit=10,
        expand=["data.items.data.price"],
    )

    for sub in subs.data:
        if sub.status in ("active", "trialing"):
            price_id = sub["items"]["data"][0]["price"]["id"]
            plan = next(
                (k for k, v in PLAN_TO_PRICE.items() if v == price_id),
                "unknown",
            )
            return {
                "active": True,
                "plan": plan,
                "status": sub.status,
            }

    return {"active": False, "plan": None}

# -------------------------------------------------------------------
# Generate summary (EMAIL SEND – EXISTING FLOW)
# -------------------------------------------------------------------

@app.post("/generate-summary")
async def generate_summary(req: GenerateSummaryRequest):
    try:
        summary_html = f"""
        <h2>Your AI Report Summary</h2>
        <p>{req.content}</p>
        """

        await send_email(
            to_email=req.recipient_email,
            subject="Your AI Report Summary",
            html_content=summary_html,
        )

        return {"sent": True}

    except Exception as e:
        logging.exception("Error generating summary")
        raise HTTPException(status_code=500, detail=str(e))
