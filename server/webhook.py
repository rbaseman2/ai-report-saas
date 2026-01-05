import os
import stripe
import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# -------------------------------------------------
# App setup
# -------------------------------------------------
app = FastAPI()
logging.basicConfig(level=logging.INFO)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------
# Stripe setup
# -------------------------------------------------
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

PRICE_IDS = {
    "basic": os.getenv("STRIPE_PRICE_BASIC"),
    "pro": os.getenv("STRIPE_PRICE_PRO"),
    "enterprise": os.getenv("STRIPE_PRICE_ENTERPRISE"),
}

# -------------------------------------------------
# Health check
# -------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}

# -------------------------------------------------
# Subscription status
# -------------------------------------------------
@app.get("/subscription-status")
def subscription_status(email: str):
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Stripe key not configured")

    customers = stripe.Customer.list(email=email, limit=1)
    if not customers.data:
        return {"status": "none", "plan": "none"}

    customer_id = customers.data[0].id
    subs = stripe.Subscription.list(
        customer=customer_id,
        status="all",
        limit=1,
        expand=["data.items.data.price"],
    )

    if not subs.data:
        return {"status": "none", "plan": "none"}

    sub = subs.data[0]
    price_id = sub["items"]["data"][0]["price"]["id"]

    plan = "unknown"
    for name, pid in PRICE_IDS.items():
        if pid == price_id:
            plan = name

    return {
        "status": sub.status,
        "plan": plan,
    }

# -------------------------------------------------
# Create Stripe checkout session
# -------------------------------------------------
@app.post("/create-checkout-session")
async def create_checkout_session(payload: dict):
    if not STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=500,
            detail="STRIPE_SECRET_KEY is not set in environment variables."
        )

    email = payload.get("email")
    plan = payload.get("plan")

    if not email or not plan:
        raise HTTPException(status_code=400, detail="email and plan are required")

    price_id = PRICE_IDS.get(plan)
    if not price_id:
        raise HTTPException(status_code=400, detail="Invalid plan")

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer_email=email,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url="https://ai-report-saas.onrender.com/Upload_Data",
        cancel_url="https://ai-report-saas.onrender.com/Billing",
        allow_promotion_codes=True,
    )

    logging.info(f"Checkout session created for {email} ({plan})")

    return {
        "checkout_url": session.url,
        "session_id": session.id,
    }

# -------------------------------------------------
# Stripe webhook (REQUIRED for subscriptions)
# -------------------------------------------------
@app.post("/webhook")
async def stripe_webhook(request: Request):
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Webhook secret not configured")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            STRIPE_WEBHOOK_SECRET,
        )
    except Exception as e:
        logging.error(f"Webhook error: {e}")
        raise HTTPException(status_code=400, detail="Invalid webhook")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        email = session["customer_details"]["email"]
        logging.info(f"Subscription completed for {email}")

        # If you later persist users, do it here

    return {"status": "ok"}

# -------------------------------------------------
# Generate summary (Upload page depends on this)
# -------------------------------------------------
@app.post("/generate-summary")
async def generate_summary(payload: dict):
    upload_id = payload.get("upload_id")
    email = payload.get("email")
    recipient = payload.get("recipient")

    if not upload_id:
        raise HTTPException(status_code=400, detail="upload_id is required")

    # Stub summary (replace with real logic if needed)
    summary_text = "Your business summary has been generated successfully."

    if recipient:
        logging.info(f"Emailing summary to {recipient}")
        # plug in email logic here

    return {
        "status": "success",
        "summary": summary_text,
    }
