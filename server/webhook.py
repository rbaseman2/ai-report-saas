# server/webhook.py
import os
import re
from typing import List, Optional


import stripe
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --- Stripe exceptions (compatible with different layouts) ---
try:
    from stripe.error import StripeError, InvalidRequestError  # type: ignore
except Exception:  # pragma: no cover - older stripe versions
    from stripe._error import StripeError, InvalidRequestError  # type: ignore


# =============================================================================
#  CONFIG
# =============================================================================

stripe.api_key = os.environ["STRIPE_SECRET_KEY"]  # must be set in Render

DATABASE_URL = os.environ["DATABASE_URL"]  # Postgres connection string
FRONTEND_URL = os.getenv("FRONTEND_URL", "").rstrip("/")

PLAN_TO_PRICE = {
    "basic": os.environ.get("PRICE_BASIC"),
    "pro": os.environ.get("PRICE_PRO"),
    "enterprise": os.environ.get("PRICE_ENTERPRISE"),
}

# These should point to your Streamlit Billing page, e.g.
# SUCCESS_URL=https://ai-report-saas.onrender.com/Billing
# CANCEL_URL=https://ai-report-saas.onrender.com/Billing
SUCCESS_URL_BASE = os.environ.get("SUCCESS_URL", "").rstrip("/")
CANCEL_URL_BASE = os.environ.get("CANCEL_URL", "").rstrip("/")

router = APIRouter()


# =============================================================================
#  DB HELPERS
# =============================================================================

def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def init_db():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                stripe_customer_id TEXT,
                stripe_subscription_id TEXT UNIQUE,
                plan TEXT,
                status TEXT,
                current_period_end TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        conn.commit()


def get_or_create_user(email: str) -> int:
    email = email.strip().lower()
    with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        row = cur.fetchone()
        if row:
            return row["id"]
        cur.execute(
            "INSERT INTO users (email) VALUES (%s) RETURNING id",
            (email,),
        )
        user_id = cur.fetchone()["id"]
        conn.commit()
        return user_id


def upsert_subscription(
    user_id: int,
    stripe_customer_id: Optional[str],
    stripe_subscription_id: Optional[str],
    plan: Optional[str],
    status: Optional[str],
    current_period_end: Optional[int],
):
    """
    Upsert on stripe_subscription_id; if missing, just insert a row for the user.
    """
    with get_conn() as conn, conn.cursor() as cur:
        if stripe_subscription_id:
            cur.execute(
                """
                INSERT INTO subscriptions
                    (user_id, stripe_customer_id, stripe_subscription_id, plan, status, current_period_end)
                VALUES (%s, %s, %s, %s, %s, to_timestamp(%s))
                ON CONFLICT (stripe_subscription_id)
                DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    stripe_customer_id = EXCLUDED.stripe_customer_id,
                    plan = EXCLUDED.plan,
                    status = EXCLUDED.status,
                    current_period_end = EXCLUDED.current_period_end;
                """,
                (
                    user_id,
                    stripe_customer_id,
                    stripe_subscription_id,
                    plan,
                    status,
                    current_period_end,
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO subscriptions
                    (user_id, plan, status)
                VALUES (%s, %s, %s);
                """,
                (user_id, plan, status),
            )
        conn.commit()


def user_has_active_subscription(email: str) -> bool:
    if not email:
        return False
    email = email.strip().lower()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.status
            FROM users u
            JOIN subscriptions s ON s.user_id = u.id
            WHERE u.email = %s
            ORDER BY s.created_at DESC
            LIMIT 1;
            """,
            (email,),
        )
        row = cur.fetchone()
        if not row:
            return False
        status = row[0]
        return status in ("active", "trialing")


# =============================================================================
#  Pydantic MODELS
# =============================================================================

class CheckoutBody(BaseModel):
    plan: str
    email: str  # simple identity


class SummarizeBody(BaseModel):
    text: str
    max_sentences: int = 6


# =============================================================================
#  SIMPLE SUMMARIZER (can swap for LLM later)
# =============================================================================

def _simple_summarize(text: str, max_sentences: int = 6) -> List[str]:
    cleaned = re.sub(r"\s+", " ", text.strip())
    raw_sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    sentences = [s.strip() for s in raw_sentences if s.strip()]

    bullets: List[str] = []
    for s in sentences[:max_sentences]:
        if len(s) > 300:
            s = s[:297].rstrip() + "..."
        bullets.append(s)

    if not bullets and cleaned:
        bullets = [cleaned[:200] + ("..." if len(cleaned) > 200 else "")]

    return bullets


# =============================================================================
#  STRIPE CHECKOUT
# =============================================================================

@router.post("/create-checkout-session")
def create_checkout_session(body: CheckoutBody):
    plan_slug = body.plan.strip().lower()
    email = body.email.strip().lower()

    price_id = PLAN_TO_PRICE.get(plan_slug)
    if not price_id:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {body.plan}")

    if not email:
        raise HTTPException(status_code=400, detail="Email is required.")

    if not SUCCESS_URL_BASE or not CANCEL_URL_BASE:
        raise HTTPException(
            status_code=500,
            detail="SUCCESS_URL and/or CANCEL_URL are not configured on the backend.",
        )

    success_url = (
        f"{SUCCESS_URL_BASE}?session_id={{CHECKOUT_SESSION_ID}}&status=success"
    )
    cancel_url = f"{CANCEL_URL_BASE}?status=cancelled"

    print(
        f">>> DEBUG create-checkout-session plan={plan_slug} price_id={price_id} email={email}",
        flush=True,
    )

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            automatic_tax={"enabled": True},
            allow_promotion_codes=True,
            customer_email=email,          # shows in Stripe + helpful for invoices
            client_reference_id=email,     # we use this to map back on success
        )
        return {"url": session.url}
    except InvalidRequestError as e:
        msg = getattr(e, "user_message", str(e))
        raise HTTPException(status_code=400, detail=msg)
    except StripeError as e:
        msg = getattr(e, "user_message", "Stripe error")
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:  # pragma: no cover
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
#  CHECKOUT SUCCESS: verify subscription & persist to DB
# =============================================================================

@router.get("/checkout-success")
def checkout_success(session_id: str):
    try:
        session = stripe.checkout.Session.retrieve(
            session_id,
            expand=["subscription", "customer", "customer_details"],
        )
    except StripeError as e:
        msg = getattr(e, "user_message", str(e))
        raise HTTPException(status_code=400, detail=msg)

    # Recover email
    email = (
        session.get("client_reference_id")
        or (session.get("customer_details") or {}).get("email")
        or ""
    )
    email = (email or "").strip().lower()
    if not email:
        return {
            "ok": False,
            "has_active_subscription": False,
            "portal_url": None,
            "reason": "no_email",
        }

    sub = session.get("subscription")
    stripe_customer_id = session.get("customer")
    stripe_subscription_id = None
    plan_id = None
    status = None
    current_period_end = None

    if isinstance(sub, dict):
        stripe_subscription_id = sub.get("id")
        status = sub.get("status")
        current_period_end = sub.get("current_period_end")  # epoch seconds
        # Try to get the Stripe price ID for plan mapping
        items = (sub.get("items") or {}).get("data") or []
        if items:
            plan_id = ((items[0].get("price") or {}).get("id")) or None

    # Map Stripe price ID back to plan slug, if possible
    plan_slug = None
    if plan_id:
        for slug, pid in PLAN_TO_PRICE.items():
            if pid == plan_id:
                plan_slug = slug
                break

    # Persist to DB
    user_id = get_or_create_user(email)
    upsert_subscription(
        user_id=user_id,
        stripe_customer_id=stripe_customer_id,
        stripe_subscription_id=stripe_subscription_id,
        plan=plan_slug or plan_id,
        status=status,
        current_period_end=current_period_end,
    )

    active = status in ("active", "trialing")

    # Billing portal
    portal_url = None
    try:
        if stripe_customer_id and (FRONTEND_URL or SUCCESS_URL_BASE or CANCEL_URL_BASE):
            return_url = FRONTEND_URL or SUCCESS_URL_BASE or CANCEL_URL_BASE
            portal_session = stripe.billing_portal.Session.create(
                customer=stripe_customer_id,
                return_url=return_url,
            )
            portal_url = portal_session.url
    except StripeError:
        portal_url = None

    return {
        "ok": True,
        "has_active_subscription": bool(active),
        "portal_url": portal_url,
        "email": email,
        "plan": plan_slug or plan_id,
    }


# =============================================================================
#  /me – per-email entitlements
# =============================================================================

@router.get("/me")
def me(email: Optional[str] = None, request: Request = None):
    """
    Entitlement endpoint.

    Streamlit will call /me?email=you@domain.com.
    You can also support x-user-email header later if you add auth.
    """
    if not email and request:
        email = request.headers.get("x-user-email", "")

    email = (email or "").strip().lower()
    has_sub = user_has_active_subscription(email) if email else False
    return {"email": email, "has_active_subscription": has_sub}


# =============================================================================
#  /summarize – used by Upload Data page
# =============================================================================

@router.post("/summarize")
def summarize(body: SummarizeBody):
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Text is required.")
    bullets = _simple_summarize(body.text, max_sentences=body.max_sentences)
    return {"tldr": bullets}


# =============================================================================
#  APP + CORS + HEALTH
# =============================================================================

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"ok": True}


@app.on_event("startup")
def _startup():
    print(">>> Initializing DB schema…", flush=True)
    init_db()
    print(">>> DB ready.", flush=True)

    key_mode = (
        "live"
        if os.environ.get("STRIPE_SECRET_KEY", "").startswith("sk_live_")
        else "test"
    )
    print(f">>> DEBUG STRIPE key mode: {key_mode}", flush=True)
    for k in ("PRICE_BASIC", "PRICE_PRO", "PRICE_ENTERPRISE"):
        v = os.environ.get(k)
        print(
            f">>> DEBUG {k} set: {bool(v)} prefix={v[:12] if v else 'missing'}",
            flush=True,
        )
    print(f">>> DEBUG FRONTEND_URL={FRONTEND_URL}", flush=True)
    print(f">>> DEBUG SUCCESS_URL_BASE={SUCCESS_URL_BASE}", flush=True)
    print(f">>> DEBUG CANCEL_URL_BASE={CANCEL_URL_BASE}", flush=True)


app.include_router(router)
