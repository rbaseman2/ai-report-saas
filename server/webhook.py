# server/webhook.py

import os
import stripe
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

# === Env & Stripe setup ===

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")

SUCCESS_URL = os.environ.get(
    "SUCCESS_URL",
    f"{FRONTEND_URL}/Billing?status=success"
)
CANCEL_URL = os.environ.get(
    "CANCEL_URL",
    f"{FRONTEND_URL}/Billing?status=cancelled"
)

if not STRIPE_SECRET_KEY:
    # On Render this will show in logs if env var is missing
    print("WARNING: STRIPE_SECRET_KEY is not set – Stripe calls will fail.")
else:
    stripe.api_key = STRIPE_SECRET_KEY

# === FastAPI app ===

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        FRONTEND_URL,
        "http://localhost:3000",
        "https://ai-report-saas.onrender.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Models ===

class CheckoutSessionRequest(BaseModel):
    price_id: str
    email: EmailStr
    coupon: str | None = None   # optional coupon code from the frontend


# === Health check ===

@app.get("/health")
async def health():
    return {"status": "ok"}


# === Create Checkout Session ===

@app.post("/create-checkout-session")
async def create_checkout_session(data: CheckoutSessionRequest):
    if not STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=500,
            detail="Stripe secret key not configured on server.",
        )

    try:
        params = {
            "mode": "subscription",
            "customer_email": data.email,
            "line_items": [
                {
                    "price": data.price_id,
                    "quantity": 1,
                }
            ],
            # Add session_id to success URL if you want it:
            "success_url": SUCCESS_URL + "&session_i_
