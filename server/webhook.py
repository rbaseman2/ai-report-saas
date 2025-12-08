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
    coupon: str | None = None  # optional coupon code

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
            "success_url": SUCCESS_URL + "&session_id={CHECKOUT_SESSION_ID}",
            "cancel_url": CANCEL_URL,
        }

        # Apply coupon if provided
        if data.coupon and data.coupon.strip() != "":
            params["discounts"] = [{"coupon": data.coupon.strip()}]

        session = stripe.checkout.Session.create(**params)

        return {"checkout_url": session.url}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# === Webhook endpoint ===

@app.post("/webhook")
async def webhook_received(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    event_type = event["type"]

    # Subscription created
    if event_type == "customer.subscription.created":
        subscription = event["data"]["object"]
        print("Subscription created:", subscription.get("id"))

    # Subscription updated
    elif event_type == "customer.subscription.updated":
        subscription = event["data"]["object"]
        print("Subscription updated:", subscription.get("id"))

    # Subscription deleted
    elif event_type == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        print("Subscription canceled:", subscription.get("id"))

    return {"status": "success"}
