# server/webhook.py
import os
import stripe
from fastapi import APIRouter, HTTPException, FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

# --- Stripe exceptions (support both layouts your env has shown) ---
try:
    from stripe.error import StripeError, InvalidRequestError
except Exception:
    from stripe._error import StripeError, InvalidRequestError

router = APIRouter()
stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

# --- Plan → Price mapping (server-authoritative; never accept price from client) ---
PLAN_TO_PRICE = {
    "basic": os.environ.get("PRICE_BASIC"),
    "pro": os.environ.get("PRICE_PRO"),
    "enterprise": os.environ.get("PRICE_ENTERPRISE"),
}

class Body(BaseModel):
    plan: str  # "basic" | "pro" | "enterprise"

@router.post("/create-checkout-session")
def create_checkout_session(body: Body):
    # Resolve plan to price id
    price_id = PLAN_TO_PRICE.get(body.plan)
    if not price_id:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {body.plan}")

    # Load redirect URLs (fail fast with clear message)
    SUCCESS_URL = os.environ.get("SUCCESS_URL")
    CANCEL_URL = os.environ.get("CANCEL_URL")
    if not SUCCESS_URL or not CANCEL_URL:
        raise HTTPException(
            status_code=500,
            detail="SUCCESS_URL and CANCEL_URL must be set to full https URLs"
        )

    # Debug
    print(f">>> DEBUG stripe_version={getattr(stripe, '__version__', 'unknown')}", flush=True)
    print(f">>> DEBUG plan={body.plan}, price_id={price_id}", flush=True)

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            allow_promotion_codes=True,                # show promo code box
            success_url=SUCCESS_URL + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=CANCEL_URL,
            automatic_tax={"enabled": True},
            billing_address_collection="required",     # optional: helps tax
            customer_creation="always",                # optional: ensures Customer
        )
        return {"url": session.url}

    except InvalidRequestError as e:
        msg = getattr(e, "user_message", str(e))
        print(f">>> STRIPE InvalidRequestError: {msg}", flush=True)
        raise HTTPException(status_code=400, detail=msg)
    except StripeError as e:
        msg = getattr(e, "user_message", "Stripe error")
        print(f">>> STRIPE StripeError: {msg}", flush=True)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        print(f">>> UNEXPECTED ERROR creating checkout session: {e}", flush=True)
        raise HTTPException(status_code=500, detail="Checkout creation failed")

# ---------- FastAPI app wiring ----------
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to your Streamlit origin in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"ok": True}

app.include_router(router)

@app.on_event("startup")
def _startup_logs():
    key_mode = "live" if os.environ.get("STRIPE_SECRET_KEY", "").startswith("sk_live_") else "test"
    print(f">>> DEBUG STRIPE key mode: {key_mode}", flush=True)
    for k in ("PRICE_BASIC", "PRICE_PRO", "PRICE_ENTERPRISE", "SUCCESS_URL", "CANCEL_URL"):
        v = os.environ.get(k)
        print(f">>> DEBUG {k} set: {bool(v)} prefix={v[:12] if v else 'missing'}", flush=True)
