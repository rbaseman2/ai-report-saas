# server/webhook.py
import os
import stripe
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.responses import JSONResponse

# Load .env if present (optional but handy for local dev)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# --- Required ENV (TEST in local) ---
STRIPE_SECRET_KEY     = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
if not STRIPE_SECRET_KEY or not STRIPE_WEBHOOK_SECRET:
    raise RuntimeError("Missing STRIPE_SECRET_KEY or STRIPE_WEBHOOK_SECRET in environment/.env")

APP_BASE_URL          = os.environ.get("APP_BASE_URL", "http://localhost:8501")
CHECKOUT_SUCCESS_PATH = os.environ.get("CHECKOUT_SUCCESS_PATH", "/Billing?success=1")
CHECKOUT_CANCEL_PATH  = os.environ.get("CHECKOUT_CANCEL_PATH",  "/Billing?canceled=1")
PORTAL_RETURN_PATH    = os.environ.get("PORTAL_RETURN_PATH",    "/Billing?portal_return=1")

stripe.api_key = STRIPE_SECRET_KEY

app = FastAPI(title="AI Report SaaS Backend")

# Allow Streamlit front-end origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[APP_BASE_URL, "http://localhost:8501", "http://127.0.0.1:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Health / Debug ----
@app.get("/health")
def health():
    return {"ok": True}

@app.get("/whoami")
def whoami():
    return {
        "APP_BASE_URL": APP_BASE_URL,
        "CHECKOUT_SUCCESS_PATH": CHECKOUT_SUCCESS_PATH,
        "CHECKOUT_CANCEL_PATH": CHECKOUT_CANCEL_PATH,
        "PORTAL_RETURN_PATH": PORTAL_RETURN_PATH,
    }

# ---------- WEBHOOK ----------
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
        print("✅ checkout.session.completed for",
              (session.get("customer_details") or {}).get("email"))

        # TODO: your entitlement write to data/entitlements.json (you said this already works)

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
            #automatic_tax={"enabled": True},
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
        session = stripe.billing_portal.Session.create(
            customer=customers.data[0].id,
            return_url=f"{APP_BASE_URL}{PORTAL_RETURN_PATH}",
        )
        return JSONResponse({"url": session.url})
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
