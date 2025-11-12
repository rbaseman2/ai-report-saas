# server/webhook.py
import os
from functools import lru_cache
from typing import Optional

import stripe
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ---- Stripe exceptions (compatible with different SDK layouts) --------------
try:
    from stripe.error import StripeError, InvalidRequestError  # usual path
except Exception:  # pragma: no cover
    from stripe._error import StripeError, InvalidRequestError  # alt path seen in logs

# ---- Required environment ---------------------------------------------------
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
if not STRIPE_SECRET_KEY:
    raise RuntimeError("STRIPE_SECRET_KEY is not set.")

stripe.api_key = STRIPE_SECRET_KEY

# Where your Streamlit app lives (e.g. https://ai-report-saas.onrender.com)
FRONTEND_URL = (os.getenv("FRONTEND_URL") or "").rstrip("/")

# Price IDs (LIVE) for each plan
PRICE_BASIC = os.getenv("PRICE_BASIC")
PRICE_PRO = os.getenv("PRICE_PRO")
PRICE_ENTERPRISE = os.getenv("PRICE_ENTERPRISE")

# Optional: Stripe webhook signing secret (for /stripe/webhook)
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

# ---- App + CORS -------------------------------------------------------------
app = FastAPI()
router = APIRouter()

# Lock CORS to your Streamlit origin when available; otherwise permissive (*)
allowed_origins = [FRONTEND_URL] if FRONTEND_URL else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Utilities --------------------------------------------------------------
PLAN_TO_PRICE = {
    "basic": PRICE_BASIC,
    "pro": PRICE_PRO,
    "enterprise": PRICE_ENTERPRISE,
}

# UI metadata for plans (price label here is cosmetic; /plans may overwrite with live amount)
PLANS = [
    {
        "slug": "basic",
        "label": "Basic",
        "price": "$9.99",
        "desc": "Core features • Up to 3 reports/mo • Email support",
        "features": [
            "✅ Core features",
            "✅ Up to 3 projects",
            "✅ Email support",
            "✅ Promotion codes accepted",
        ],
    },
    {
        "slug": "pro",
        "label": "Pro",
        "price": "$19.99",
        "desc": "Unlimited reports • Advanced analytics • Priority support",
        "features": [
            "✅ Everything in Basic",
            "✅ Unlimited projects",
            "✅ Priority support",
            "✅ Early feature access",
        ],
    },
    {
        "slug": "enterprise",
        "label": "Enterprise",
        "price": "$49.99",
        "desc": "Custom integrations • SLA uptime • Dedicated support",
        "features": [
            "✅ SSO & advanced controls",
            "✅ Dedicated support",
            "✅ Uptime SLA",
            "✅ Custom onboarding",
        ],
    },
]


def _success_url() -> str:
    # Includes Stripe placeholder; front end reads ?status=success&session_id=...
    base = FRONTEND_URL or ""
    return f"{base}/Billing?status=success&session_id={{CHECKOUT_SESSION_ID}}"


def _cancel_url() -> str:
    base = FRONTEND_URL or ""
    return f"{base}/Billing?status=cancelled"


def _format_amount_from_price(pr: stripe.Price) -> Optional[str]:
    """
    Convert Stripe Price to a human label, handling None unit_amount and non-USD.
    """
    if not pr:
        return None
    unit_raw = pr.get("unit_amount") or pr.get("unit_amount_decimal")
    if unit_raw is None:
        return None
    try:
        unit = float(unit_raw) / 100.0
    except Exception:
        return None
    currency = (pr.get("currency") or "usd").upper()
    # Keep it simple; customize as desired
    return f"${unit:,.2f}" if currency == "USD" else f"{unit:,.2f} {currency}"


# ---- Models -----------------------------------------------------------------
class CheckoutBody(BaseModel):
    plan: str  # "basic" | "pro" | "enterprise"


class PortalBody(BaseModel):
    session_id: Optional[str] = None
    customer_id: Optional[str] = None


# ---- Routes -----------------------------------------------------------------
@app.get("/health")
def health():
    return {"ok": True}


@lru_cache(maxsize=1)
def _plans_with_live_amounts():
    """
    Return PLANS, but override 'price' label from live Stripe Prices when possible.
    Cached to reduce dashboard/API round-trips; cleared on startup.
    """
    out = []
    for p in PLANS:
        label_price = p.get("price") or ""
        price_id = PLAN_TO_PRICE.get(p["slug"])
        if price_id:
            try:
                pr = stripe.Price.retrieve(price_id)
                live_label = _format_amount_from_price(pr)
                if live_label:
                    label_price = live_label
            except Exception:
                # Fallback to the static label if retrieval fails
                pass
        out.append({**p, "price": label_price})
    return out


@router.get("/plans")
def get_plans():
    return {"plans": _plans_with_live_amounts()}


@router.post("/create-checkout-session")
def create_checkout_session(body: CheckoutBody):
    price_id = PLAN_TO_PRICE.get(body.plan)
    if not price_id:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {body.plan}")

    # Helpful debug logs
    print(f">>> DEBUG stripe_version={getattr(stripe, '__version__', 'unknown')}", flush=True)
    print(f">>> DEBUG plan={body.plan}, price_id={price_id}", flush=True)
    if not FRONTEND_URL:
        print(">>> WARN: FRONTEND_URL not set; success/cancel URLs will be relative.", flush=True)

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=_success_url(),
            cancel_url=_cancel_url(),
            automatic_tax={"enabled": True},
            billing_address_collection="required",
            allow_promotion_codes=True,  # let users apply live promo codes (e.g., 100% off for testing)
            subscription_data={"metadata": {"plan": body.plan}},
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
    Create a Stripe Billing Portal session so customers can manage subscriptions.
    Accepts either a Checkout `session_id` or a `customer_id`.
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


# Optional: Webhook for post-purchase automation (entitlements, etc.)
@app.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    if not WEBHOOK_SECRET:
        raise HTTPException(status_code=501, detail="Webhook not configured (missing STRIPE_WEBHOOK_SECRET).")
    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    try:
        event = stripe.Webhook.construct_event(payload, sig, WEBHOOK_SECRET)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Webhook signature verification failed: {e}")

    et = event["type"]
    obj = event["data"]["object"]

    if et == "checkout.session.completed":
        # TODO: persist obj['customer'], obj['subscription'], mark plan active for your user
        print(">>> WEBHOOK checkout.session.completed", obj.get("id"), flush=True)

    if et in ("customer.subscription.updated", "customer.subscription.deleted"):
        # TODO: update/cancel entitlements based on obj['status']
        print(f">>> WEBHOOK {et} status={obj.get('status')} id={obj.get('id')}", flush=True)

    return {"received": True}


# ---- Wire router + startup logs --------------------------------------------
app.include_router(router)


@app.on_event("startup")
def _startup_logs():
    # Clear price cache each deploy/restart
    _plans_with_live_amounts.cache_clear()

    key_mode = "live" if STRIPE_SECRET_KEY.startswith("sk_live_") else "test"
    print(f">>> DEBUG using webhook file: {__file__}", flush=True)
    print(f">>> DEBUG STRIPE key mode: {key_mode}", flush=True)
    for k, v in {
        "PRICE_BASIC": PRICE_BASIC,
        "PRICE_PRO": PRICE_PRO,
        "PRICE_ENTERPRISE": PRICE_ENTERPRISE,
        "FRONTEND_URL": FRONTEND_URL,
        "STRIPE_WEBHOOK_SECRET_set": bool(WEBHOOK_SECRET),
        "CORS_allowed_origins": allowed_origins,
    }.items():
        prefix = (v[:14] if isinstance(v, str) and v else str(v))
        print(f">>> DEBUG {k}: {prefix}", flush=True)
