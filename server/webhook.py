"""
FastAPI backend for Stripe billing + entitlements.

- Creates Checkout Sessions for Basic / Pro / Enterprise plans
- Exposes a small "me" endpoint for the Streamlit app to check subscription status
- (Optionally) logs subscriptions into Postgres via pg8000 if DATABASE_URL is set
"""

import os
from typing import Optional, Dict, Any

import stripe
from fastapi import FastAPI, APIRouter, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pydantic import BaseModel
from openai import OpenAI



# ------------------------------------------------------------------------------
# Optional Postgres via pg8000 (pure-Python, works on Python 3.13+)
# ------------------------------------------------------------------------------

try:
    import pg8000.native as pg
except Exception:  # DB is optional – if pg8000 isn't installed we just skip it
    pg = None

DATABASE_URL = os.getenv("DATABASE_URL")


def _parse_database_url(url: str) -> Dict[str, Any]:
    # Expected format: postgres://user:pass@host:port/dbname
    import urllib.parse as up

    if not url:
        raise RuntimeError("DATABASE_URL is empty")

    up.uses_netloc.append("postgres")
    parsed = up.urlparse(url)

    return dict(
        user=parsed.username,
        password=parsed.password,
        host=parsed.hostname,
        port=parsed.port or 5432,
        database=parsed.path.lstrip("/"),
    )


def _get_conn():
    if not (pg and DATABASE_URL):
        return None
    cfg = _parse_database_url(DATABASE_URL)
    return pg.Connection(**cfg)


def ensure_schema() -> None:
    """
    Create a tiny table to remember user subscriptions.
    If there's no DATABASE_URL or no pg8000, this is a no-op.
    """
    conn = _get_conn()
    if not conn:
        print(">>> INFO: Subscription DB disabled (no DATABASE_URL or pg8000).", flush=True)
        return

    conn.run(
        """
        CREATE TABLE IF NOT EXISTS user_subscriptions (
            id                 BIGSERIAL PRIMARY KEY,
            email              TEXT NOT NULL,
            stripe_customer_id TEXT,
            plan               TEXT,
            active             BOOLEAN NOT NULL DEFAULT TRUE,
            last_checkout_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    print(">>> DEBUG: user_subscriptions table ready.", flush=True)


def record_subscription(email: str, customer_id: str, plan: str, active: bool) -> None:
    """
    Store one row per checkout. For now we just INSERT and when we read
    we take the latest row for that email.
    """
    conn = _get_conn()
    if not conn:
        return

    conn.run(
        """
        INSERT INTO user_subscriptions (email, stripe_customer_id, plan, active)
        VALUES (:email, :cid, :plan, :active);
        """,
        email=email,
        cid=customer_id,
        plan=plan,
        active=active,
    )


def get_latest_subscription(email: str) -> Optional[Dict[str, Any]]:
    """
    Return the latest subscription row for this email, or None.
    """
    conn = _get_conn()
    if not conn:
        return None

    rows = conn.run(
        """
        SELECT email, stripe_customer_id, plan, active, last_checkout_at
        FROM user_subscriptions
        WHERE lower(email) = lower(:email)
        ORDER BY last_checkout_at DESC
        LIMIT 1;
        """,
        email=email,
    )

    if not rows:
        return None

    rec = rows[0]
    return {
        "email": rec[0],
        "stripe_customer_id": rec[1],
        "plan": rec[2],
        "active": bool(rec[3]),
        "last_checkout_at": rec[4],
    }


# ------------------------------------------------------------------------------
# Stripe configuration
# ------------------------------------------------------------------------------

stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

PLAN_TO_PRICE = {
    "basic": os.environ.get("PRICE_BASIC"),
    "pro": os.environ.get("PRICE_PRO"),
    "enterprise": os.environ.get("PRICE_ENTERPRISE"),
}

FRONTEND_URL = os.getenv("FRONTEND_URL", "").rstrip("/")
SUCCESS_URL = os.getenv("SUCCESS_URL") or (FRONTEND_URL + "/Billing")
CANCEL_URL = os.getenv("CANCEL_URL") or (FRONTEND_URL + "/Billing")

WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

router = APIRouter()


class CheckoutBody(BaseModel):
    plan: str  # "basic" | "pro" | "enterprise"


# ------------------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------------------

@router.post("/create-checkout-session")
def create_checkout_session(body: CheckoutBody):
    price_id = PLAN_TO_PRICE.get(body.plan)
    if not price_id:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {body.plan}")

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            allow_promotion_codes=True,
            success_url=SUCCESS_URL + "?session_id={CHECKOUT_SESSION_ID}&status=success",
            cancel_url=CANCEL_URL + "?status=cancelled",
            automatic_tax={"enabled": True},
            billing_address_collection="required",
        )
        return {"url": session.url}
    except stripe.error.StripeError as e:
        msg = getattr(e, "user_message", str(e))
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:  # pragma: no cover
        print(f">>> UNEXPECTED ERROR creating checkout session: {e}", flush=True)
        raise HTTPException(status_code=500, detail="Checkout creation failed")


@router.post("/webhook")
async def stripe_webhook(request: Request):
    # If no webhook secret is configured, abort early
    if not WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Webhook endpoint not configured")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload, sig_header=sig_header, secret=WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        customer_id = session.get("customer")
        email = (session.get("customer_details") or {}).get("email")
        plan = None

        # Try to infer plan from the first line item
        try:
            line_items = stripe.checkout.Session.list_line_items(session["id"], limit=1)
            if line_items["data"]:
                price = line_items["data"][0]["price"]
                plan = price.get("nickname") or price.get("id")
        except Exception:
            pass

        if email and customer_id:
            try:
                record_subscription(
                    email=email,
                    customer_id=customer_id,
                    plan=plan or "unknown",
                    active=True,
                )
            except Exception as e:  # pragma: no cover
                print(f">>> WARNING: failed to record subscription: {e}", flush=True)

    return {"received": True}

# ---------- AI summarization ----------

client = OpenAI()  # uses OPENAI_API_KEY from environment


class SummarizeRequest(BaseModel):
    text: str


class SummarizeResponse(BaseModel):
    summary: str
    input_chars: int
    model: str


@router.post("/summarize", response_model=SummarizeResponse)
async def summarize(req: SummarizeRequest):
    """
    Take raw text from the Streamlit app and return a patient-friendly summary.
    """
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="No text provided for summarization.")

    # Simple safety/size guard – trim if someone uploads a novel 🙂
    max_chars = 16_000
    if len(text) > max_chars:
        text = text[:max_chars]

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.3,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a clinical assistant that rewrites long, technical consultation notes "
                        "into a short, clear summary for patients. Use plain language at about an 8th "
                        "grade reading level. Keep it factual and avoid adding new information."
                    ),
                },
                {
                    "role": "user",
                    "content": text,
                },
            ],
        )
    except Exception as e:
        # Surface a clean error back to Streamlit
        raise HTTPException(status_code=500, detail=f"OpenAI error: {e}") from e

    summary = resp.choices[0].message.content.strip()
    return SummarizeResponse(
        summary=summary,
        input_chars=len(text),
        model=resp.model,
    )


def _stripe_lookup(email: str) -> Dict[str, Any]:
    """
    Fallback lookup directly against Stripe in case the DB is empty/disabled.
    """
    customers = stripe.Customer.list(email=email, limit=1).data
    if not customers:
        return {"has_active_subscription": False, "plan": None}

    cust = customers[0]
    subs = stripe.Subscription.list(customer=cust.id, status="active", limit=1).data
    if not subs:
        return {"has_active_subscription": False, "plan": None}

    sub = subs[0]
    price = sub["items"]["data"][0]["price"]
    plan = price.get("nickname") or price.get("id")
    return {"has_active_subscription": True, "plan": plan}


@router.get("/me")
def me(email: str = Query(..., description="User email to check entitlements for")):
    """
    Small helper endpoint used by the Streamlit app.

    Returns:
        {
          "email": "...",
          "has_active_subscription": bool,
          "plan": str | None
        }
    """
    email = email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    # 1) Try DB
    sub = None
    try:
        sub = get_latest_subscription(email)
    except Exception as e:  # pragma: no cover
        print(f">>> WARNING: DB lookup failed, falling back to Stripe: {e}", flush=True)

    if sub:
        return {
            "email": email,
            "has_active_subscription": bool(sub["active"]),
            "plan": sub["plan"],
        }

    # 2) Fallback to Stripe
    res = _stripe_lookup(email)
    return {
        "email": email,
        **res,
    }


@router.get("/health")
def health():
    return {"ok": True}


# ------------------------------------------------------------------------------
# FastAPI app wiring
# ------------------------------------------------------------------------------

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # You can restrict this to your Streamlit domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.on_event("startup")
def _startup():
    print(">>> DEBUG using webhook file: server/webhook.py", flush=True)
    try:
        ensure_schema()
    except Exception as e:  # pragma: no cover
        print(f">>> WARNING: ensure_schema failed: {e}", flush=True)
