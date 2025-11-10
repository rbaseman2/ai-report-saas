# server/webhook.py
import os
import stripe
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.responses import JSONResponse
from sqlalchemy import text  # ✅ needed for SQLAlchemy 2.x
from .db import engine       # ✅ import your DB engine

# --- Load environment variables ---
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# --- Environment variables ---
STRIPE_SECRET_KEY     = os.environ["STRIPE_SECRET_KEY"]
STRIPE_WEBHOOK_SECRET = os.environ["STRIPE_WEBHOOK_SECRET"]
APP_BASE_URL          = os.environ.get("APP_BASE_URL", "http://localhost:8501")
CHECKOUT_SUCCESS_PATH = os.environ.get("CHECKOUT_SUCCESS_PATH", "/Billing?success=1")
CHECKOUT_CANCEL_PATH  = os.environ.get("CHECKOUT_CANCEL_PATH",  "/Billing?canceled=1")
PORTAL_RETURN_PATH    = os.environ.get("PORTAL_RETURN_PATH",    "/Billing?portal_return=1")

stripe.api_key = STRIPE_SECRET_KEY

# --- FastAPI app setup ---
app = FastAPI(title="AI Report SaaS Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[APP_BASE_URL, "http://localhost:8501", "http://127.0.0.1:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- STARTUP EVENT ----------
@app.on_event("startup")
def startup_event():
    """Check DB connection on startup."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))  # ✅ fixed for SQLAlchemy 2.x
        print("✅ Database connection successful")
    except Exception as e:
        print("❌ Database connection failed:", e)

# ---------- HEALTH CHECK ----------
@app.get("/health")
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ---------- STRIPE WEBHOOK ----------
@app.post("/webhook", tags=["Stripe"])
async def webhook(req: Request):
    payload = await req.body()
    sig = req.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(
            payload=payload, sig_header=sig, secret=STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Webhook error: {e}")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        print("✅ checkout.session.completed for", session.get("customer_details", {}).get("email"))
        # You can add logic here to write to your entitlements table.

    return {"ok": True}

# ---------- CHECKOUT ----------
class CheckoutReq(BaseModel):
    price_id: str
    email: str

@app.post("/create-checkout-session", tags=["Stripe"])
def create_checkout_session(req: CheckoutReq):
    try:
        customers = stripe.Customer.list(email=req.email, limit=1)
        customer = customers.data[0] if customers.data else stripe.Customer.create(email=req.email)

        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=customer.id,
            line_items=[{"price": req.price_id, "quantity": 1}],
            success_url=f"{APP_BASE_URL}{CHECKOUT_SUCCESS_PATH}",
            cancel_url=f"{APP_BASE_URL}{CHECKOUT_CANCEL_PATH}",
            allow_promotion_codes=True,
            billing_address_collection="auto",
            automatic_tax={"enabled": True},
        )
        return JSONResponse({"url": session.url})
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ---------- CUSTOMER PORTAL ----------
class PortalReq(BaseModel):
    email: str

@app.post("/create-portal-session", tags=["Stripe"])
def create_portal_session(req: PortalReq):
    try:
        customers = stripe.Customer.list(email=req.email, limit=1)
        if not customers.data:
            raise HTTPException(status_code=404, detail="No Stripe customer for that email.")
        customer = customers.data[0]
        session = stripe.billing_portal.Session.create(
            customer=customer.id,
            return_url=f"{APP_BASE_URL}{PORTAL_RETURN_PATH}",
        )
        return JSONResponse({"url": session.url})
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
