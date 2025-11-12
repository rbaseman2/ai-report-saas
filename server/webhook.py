
# server/webhook.py
import os, stripe
from fastapi import APIRouter, HTTPException, FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

# --- Stripe exceptions (layout-safe import) ---
try:
    from stripe.error import StripeError, InvalidRequestError
except Exception:
    from stripe._error import StripeError, InvalidRequestError

router = APIRouter()
stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

# Where your Streamlit app lives, e.g. https://ai-report-saas.onrender.com
FRONTEND_URL = os.getenv("FRONTEND_URL", "").rstrip("/")

PLAN_TO_PRICE = {
    "basic": os.getenv("PRICE_BASIC"),
    "pro": os.getenv("PRICE_PRO"),
    "enterprise": os.getenv("PRICE_ENTERPRISE"),
}

class CheckoutBody(BaseModel):
    plan: str

class PortalBody(BaseModel):
    session_id: str | None = None
    customer_id: str | None = None

def _success_url_with_placeholder() -> str:
    """
    Build a success_url that includes the Stripe placeholder.
    If FRONTEND_URL isn't set, we fall back to just /Billing.
    """
    base = FRONTEND_URL or ""
    return f"{base}/Billing?status=success&session_id={{CHECKOUT_SESSION_ID}}"

def _cancel_url() -> str:
    base = FRONTEND_URL or ""
    return f"{base}/Billing?status=cancelled"

@router.post("/create-checkout-session")
def create_checkout_session(body: CheckoutBody):
    price_id = PLAN_TO_PRICE.get(body.plan)
    if not price_id:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {body.plan}")

    print(f">>> DEBUG stripe_version={getattr(stripe, '__version__', 'unknown')}", flush=True)
    print(f">>> DEBUG plan={body.plan}, price_id={price_id}", flush=True)

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=_success_url_with_placeholder(),
            cancel_url=_cancel_url(),
            automatic_tax={"enabled": True},
            billing_address_collection="required",
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

@router.post("/create-portal-session")
def create_portal_session(body: PortalBody):
    """
    Create a Stripe Billing Portal session so the user can manage their subscription.
    You can pass either `session_id` (Checkout Session) or `customer_id`.
    """
    try:
        if body.customer_id:
            customer_id = body.customer_id
        elif body.session_id:
            chk = stripe.checkout.Session.retrieve(body.session_id)
            customer_id = chk.customer
        else:
            raise HTTPException(status_code=400, detail="Provide session_id or customer_id")

        portal = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=(FRONTEND_URL or "") + "/Billing",
        )
        return {"url": portal.url}

    except InvalidRequestError as e:
        msg = getattr(e, "user_message", str(e))
        print(f">>> STRIPE InvalidRequestError (portal): {msg}", flush=True)
        raise HTTPException(status_code=400, detail=msg)
    except StripeError as e:
        msg = getattr(e, "user_message", "Stripe error")
        print(f">>> STRIPE StripeError (portal): {msg}", flush=True)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        print(f">>> UNEXPECTED ERROR creating portal session: {e}", flush=True)
        raise HTTPException(status_code=500, detail="Portal creation failed")

# ---------- FastAPI app ----------
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    key_mode = "live" if os.getenv("STRIPE_SECRET_KEY", "").startswith("sk_live_") else "test"
    print(f">>> DEBUG STRIPE key mode: {key_mode}", flush=True)
    for k in ("PRICE_BASIC", "PRICE_PRO", "PRICE_ENTERPRISE"):
        v = os.getenv(k)
        print(f">>> DEBUG {k} set: {bool(v)} prefix={v[:12] if v else 'missing'}", flush=True)
    print(f">>> DEBUG FRONTEND_URL: {FRONTEND_URL}", flush=True)
