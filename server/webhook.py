# server/webhook.py
from __future__ import annotations

import os
import logging
from datetime import datetime, timezone
from typing import Optional

import stripe
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .models import User, Subscription, Summary

logger = logging.getLogger("ai-report-backend")
logging.basicConfig(level=logging.INFO)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# ENV
# ----------------------------
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()

STRIPE_PRICE_BASIC = os.getenv("STRIPE_PRICE_BASIC", "").strip()
STRIPE_PRICE_PRO = os.getenv("STRIPE_PRICE_PRO", "").strip()
STRIPE_PRICE_ENTERPRISE = os.getenv("STRIPE_PRICE_ENTERPRISE", "").strip()

SUCCESS_URL = os.getenv("SUCCESS_URL", "").strip()
CANCEL_URL = os.getenv("CANCEL_URL", "").strip()

stripe.api_key = STRIPE_SECRET_KEY

# Plan <-> Price mappings
PLAN_TO_PRICE = {
    "basic": STRIPE_PRICE_BASIC,
    "pro": STRIPE_PRICE_PRO,
    "enterprise": STRIPE_PRICE_ENTERPRISE,
}

PRICE_TO_PLAN = {
    STRIPE_PRICE_BASIC: "basic",
    STRIPE_PRICE_PRO: "pro",
    STRIPE_PRICE_ENTERPRISE: "enterprise",
}


# ----------------------------
# Helpers
# ----------------------------
def to_dt_from_unix(ts: Optional[int]) -> Optional[datetime]:
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc)


async def get_or_create_user(session: AsyncSession, email: str) -> User:
    email_norm = email.strip().lower()
    res = await session.execute(select(User).where(User.email == email_norm))
    user = res.scalar_one_or_none()
    if user:
        return user

    user = User(email=email_norm)
    session.add(user)
    await session.flush()
    return user


async def upsert_subscription(
    session: AsyncSession,
    *,
    email: str,
    customer_id: Optional[str],
    subscription_id: Optional[str],
    price_id: Optional[str],
    status: Optional[str],
    current_period_end: Optional[datetime],
):
    """
    Single safe helper used by Stripe webhooks.
    Upserts the subscription row keyed by subscription_id.
    """
    if not email:
        return

    user = await get_or_create_user(session, email)

    # subscription_id can be None in edge cases; handle gracefully
    sub_id = str(subscription_id) if subscription_id else None

    row = None
    if sub_id:
        res = await session.execute(
            select(Subscription).where(Subscription.subscription_id == sub_id)
        )
        row = res.scalar_one_or_none()

    if not row:
        row = Subscription(
            email=str(email).strip().lower(),
            customer_id=str(customer_id) if customer_id else None,
            subscription_id=sub_id,
            price_id=price_id,
            status=status,
            current_period_end=current_period_end,
            user_id=str(user.id),
        )
        session.add(row)
    else:
        row.email = str(email).strip().lower()
        row.customer_id = str(customer_id) if customer_id else row.customer_id
        row.price_id = price_id or row.price_id
        row.status = status or row.status
        row.current_period_end = current_period_end or row.current_period_end
        row.user_id = str(user.id)

    await session.commit()


# ✅ Single helper you asked for (used by subscription-status and anywhere else later)
async def get_latest_subscription_for_email(
    session: AsyncSession, email: str
) -> Optional[Subscription]:
    """
    Returns the newest Subscription row for this user (by DB id desc),
    or None if the user/subscription doesn't exist.
    """
    email_norm = email.strip().lower()

    res = await session.execute(select(User).where(User.email == email_norm))
    user = res.scalar_one_or_none()
    if not user:
        return None

    res = await session.execute(
        select(Subscription)
        .where(Subscription.user_id == str(user.id))
        .order_by(Subscription.id.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


def plan_from_price_id(price_id: Optional[str]) -> str:
    if not price_id:
        return "none"
    return PRICE_TO_PLAN.get(price_id, "none")


def is_active_status(status: Optional[str]) -> bool:
    # treat trialing as active for gating access
    return (status or "").lower() in ("active", "trialing")


def extract_email_from_checkout_session(obj: dict) -> Optional[str]:
    # Stripe may put email in different places depending on flow
    email = obj.get("customer_email")
    if email:
        return str(email).strip().lower()

    customer_details = obj.get("customer_details") or {}
    email2 = customer_details.get("email")
    if email2:
        return str(email2).strip().lower()

    return None


# ----------------------------
# API Models
# ----------------------------
class CheckoutRequest(BaseModel):
    email: EmailStr
    plan: str = Field(..., description="basic|pro|enterprise")


class CheckoutResponse(BaseModel):
    url: str
    session_id: str


class GenerateSummaryRequest(BaseModel):
    email: EmailStr
    input_type: str
    input_name: Optional[str] = None
    text: str
    summary_text: str
    tokens_used: int = 0


# ----------------------------
# Routes
# ----------------------------
@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/create-checkout-session", response_model=CheckoutResponse)
async def create_checkout_session(
    payload: CheckoutRequest,
    session: AsyncSession = Depends(get_session),
):
    plan = payload.plan.strip().lower()
    price_id = PLAN_TO_PRICE.get(plan)

    if not price_id:
        raise HTTPException(status_code=400, detail="Invalid plan. Use basic|pro|enterprise")

    # Ensure user exists in DB
    user = await get_or_create_user(session, str(payload.email))
    await session.commit()

    # ✅ Coupon box on hosted checkout
    checkout = stripe.checkout.Session.create(
        mode="subscription",
        customer_email=str(payload.email),
        allow_promotion_codes=True,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=SUCCESS_URL,
        cancel_url=CANCEL_URL,
        metadata={"user_id": str(user.id), "plan": plan},
    )

    logger.info(
        "Created checkout session %s for plan %s and email %s",
        checkout.id,
        plan,
        str(payload.email),
    )

    return CheckoutResponse(url=checkout.url, session_id=checkout.id)


@app.post("/stripe-webhook")
async def stripe_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Missing STRIPE_WEBHOOK_SECRET")

    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    if not sig:
        raise HTTPException(status_code=400, detail="Missing stripe-signature header")

    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception:
        logger.exception("Stripe webhook signature verification failed")
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}

    # ----------------------------
    # checkout.session.completed
    # ----------------------------
    if event_type == "checkout.session.completed":
        email = extract_email_from_checkout_session(obj)
        subscription_id = obj.get("subscription")
        customer_id = obj.get("customer")

        if not email:
            logger.warning("checkout.session.completed missing email; ignoring")
            return {"received": True}

        # Pull subscription details to capture price/status/period_end
        price_id = None
        status = None
        current_period_end = None

        try:
            if subscription_id:
                sub = stripe.Subscription.retrieve(subscription_id)
                status = sub.get("status")
                current_period_end = to_dt_from_unix(sub.get("current_period_end"))
                items = (sub.get("items", {}) or {}).get("data", []) or []
                if items and (items[0].get("price") or {}).get("id"):
                    price_id = items[0]["price"]["id"]
        except Exception:
            logger.exception("Failed to retrieve Stripe subscription for %s", subscription_id)

        await upsert_subscription(
            session,
            email=email,
            customer_id=str(customer_id) if customer_id else None,
            subscription_id=str(subscription_id) if subscription_id else None,
            price_id=price_id,
            status=status,
            current_period_end=current_period_end,
        )

        return {"received": True}

    # ----------------------------
    # customer.subscription.updated / deleted
    # ----------------------------
    if event_type in ("customer.subscription.updated", "customer.subscription.deleted"):
        subscription_id = obj.get("id")
        customer_id = obj.get("customer")
        status = obj.get("status")
        current_period_end = to_dt_from_unix(obj.get("current_period_end"))

        # price id
        price_id = None
        items = (obj.get("items", {}) or {}).get("data", []) or []
        if items and items[0].get("price"):
            price_id = (items[0]["price"] or {}).get("id")

        # We may not have email on these events; keep existing email in DB if present.
        sub_id = str(subscription_id) if subscription_id else None
        if not sub_id:
            return {"received": True}

        res = await session.execute(
            select(Subscription).where(Subscription.subscription_id == sub_id)
        )
        row = res.scalar_one_or_none()
        if row:
            row.customer_id = str(customer_id) if customer_id else row.customer_id
            row.status = status or row.status
            row.price_id = price_id or row.price_id
            row.current_period_end = current_period_end or row.current_period_end
            await session.commit()

        return {"received": True}

    # ignore other events
    return {"received": True}


@app.post("/generate-summary")
async def generate_summary(
    payload: GenerateSummaryRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    This endpoint stores the generated summary into Postgres.
    Your Streamlit app generates summary text and POSTs it here.
    """
    user = await get_or_create_user(session, str(payload.email))

    # latest subscription (optional)
    res = await session.execute(
        select(Subscription)
        .where(Subscription.user_id == str(user.id))
        .order_by(Subscription.id.desc())
        .limit(1)
    )
    sub = res.scalar_one_or_none()

    row = Summary(
        user_id=str(user.id),
        subscription_id=sub.id if sub else None,
        input_type=payload.input_type,
        input_name=payload.input_name,
        summary_text=payload.summary_text,
        tokens_used=int(payload.tokens_used or 0),
    )
    session.add(row)
    await session.commit()

    return {
        "ok": True,
        "user_id": str(user.id),
        "subscription_id": sub.subscription_id if sub else None,
    }


@app.get("/subscription-status")
async def subscription_status(email: EmailStr, session: AsyncSession = Depends(get_session)):
    email_norm = str(email).strip().lower()

    sub = await get_latest_subscription_for_email(session, email_norm)
    if not sub:
        return {
            "email": email_norm,
            "has_active_subscription": False,
            "status": "none",
            "plan": "none",
            "current_period_end": None,
            "stripe_customer_id": None,
            "stripe_subscription_id": None,
        }

    status = (sub.status or "none").lower()
    plan = plan_from_price_id(sub.price_id)

    return {
        "email": email_norm,
        "has_active_subscription": is_active_status(status),
        "plan": plan,
        "status": status,
        "current_period_end": int(sub.current_period_end.timestamp()) if sub.current_period_end else None,
        "stripe_customer_id": sub.customer_id,
        "stripe_subscription_id": sub.subscription_id,
        "user_id": sub.user_id,
    }
