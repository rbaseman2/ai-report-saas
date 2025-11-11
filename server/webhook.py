# server/webhook.py
import os
from typing import Optional

import stripe
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from sqlalchemy import text

from .db import engine  # uses DATABASE_URL and creates the SQLAlchemy engine

# --- Stripe setup ---
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
if not STRIPE_SECRET_KEY:
    raise RuntimeError("Missing STRIPE_SECRET_KEY env")
stripe.api_key = STRIPE_SECRET_KEY

# Where to send users after checkout / portal
# For local Streamlit testing this is fine; you can override in Render env later.
FRONTEND_BASE = os.getenv("FRONTEND_BASE", "http://localhost:8501")
SUCCESS_URL = os.getenv("SUCCESS_URL", f"{FRONTEND_BASE}/Billing?success=1")
CANCEL_URL  = os.getenv("CANCEL_URL",  f"{FRONTEND_BASE}/Billing?canceled=1")
PORTAL_RETURN_URL = os.getenv("PORTAL_RETURN_URL", f"{FRONTEND_BASE}/Billing")

app = FastAPI(title="AI Report SaaS Backend")

# CORS (so the Streamlit frontend can call us)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Models ----------
class CheckoutIn(BaseModel):
    price_id: str
    email: EmailStr

class PortalIn(BaseModel):
    email: EmailStr

# ---------- Utilities ----------
def get_or_create_customer_by_email(email: str) -> stripe.Customer:
    """Return existing Stripe customer by email or create one."""
    # Try to reuse an existing customer
    res = stripe.Customer.list(email=email, limit=1)
    if res.data:
        return res.data[0]
    return stripe.Customer.create(email=email)

# ---------- Routes ----------
@app.get("/health")
def health():
    # DB ping; if DB is down this will raise and Render will show a 500
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"ok": True}

@app.post("/create-checkout-session")
def create_checkout_session(payload: CheckoutIn):
    try:
        customer = get_or_create_customer_by_email(payload.email)
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=customer.id,
            line_items=[{"price": payload.price_id, "quantity": 1}],
            success_url=SUCCESS_URL,
            cancel_url=CANCEL_URL,
        )
        return {"url": session.url}
    except stripe.error.StripeError as e:
        # Bubble up Stripe message to the client
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to create checkout") from e

@app.post("/create-portal-session")
def create_portal_session(payload: PortalIn):
    try:
        customer = get_or_create_customer_by_email(payload.email)
        ps = stripe.billing_portal.Session.create(
            customer=customer.id,
            return_url=PORTAL_RETURN_URL,
        )
        return {"url": ps.url}
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to create portal session") from e
