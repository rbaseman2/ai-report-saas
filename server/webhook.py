import os
import stripe
from fastapi import FastAPI, Request, HTTPException

app = FastAPI()

# --------------------------------------------------
# Stripe configuration
# --------------------------------------------------
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

if not STRIPE_SECRET_KEY:
    raise RuntimeError("STRIPE_SECRET_KEY is not set")

stripe.api_key = STRIPE_SECRET_KEY


# --------------------------------------------------
# Health check
# --------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}


# --------------------------------------------------
# Stripe Webhook Endpoint
# --------------------------------------------------
@app.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except ValueError:
        # Invalid payload
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        # Invalid signature
        raise HTTPException(status_code=400, detail="Invalid signature")

    # --------------------------------------------------
    # Handle Stripe events
    # --------------------------------------------------
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]

        customer_email = session.get("customer_details", {}).get("email")
        subscription_id = session.get("subscription")

        print("✅ Checkout completed")
        print("Email:", customer_email)
        print("Subscription ID:", subscription_id)

        # 👉 This is where you would persist subscription info
        # to a DB if/when you add one.

    elif event["type"] == "customer.subscription.updated":
        subscription = event["data"]["object"]
        print("🔄 Subscription updated:", subscription["id"])

    elif event["type"] == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        print("❌ Subscription cancelled:", subscription["id"])

    return {"received": True}
