# server/webhook.py
from __future__ import annotations

import os
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

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

if not STRIPE_SECRET_KEY:
    logger.warning("STRIPE_SECRET_KEY is not set")

stripe.api_key = STRIPE_SECRET_KEY

# Correct mappings
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

ACTIVE_STATUSES = {"active", "trialing"}

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
    await session.flush()  # assign id
    return user


async def resolve_customer_email(customer_id: Optional[str], fallback_email: Optional[str]) -> Optional[str]:
    """
    Stripe webhook events don't always include customer_email.
    Use fallback if present; otherwise look it up via Stripe Customer.
    """
    if fallback_email:
        return fallback_email.strip().lower()
    if not customer_id:
        return None

    try:
        cust = stripe.Customer.retrieve(customer_id)
        email = (cust.get("email") or "").strip().lower()
        return email or None
    except Exception:
        logger.exception("Failed to retrieve Stripe customer to resolve email")
        return None


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
    """
    email_norm = email.strip().lower()
    user = await get_or_create_user(session, email_norm)

    row = None
    if subscription_id:
        res = await session.execute(
            select(Subscription).where(Subscription.subscription_id == subscription_id)
        )
        row = res.scalar_one_or_none()

    if not row:
        row = Subscription(
            email=email_norm,
            customer_id=customer_id,
            subscription_id=subscription_id,
            price_id=price_id,
            status=status,
            current_period_end=current_period_end,
            user_id=str(user.id),
        )
        session.add(row)
    else:
        row.email = email_norm
        row.customer_id = customer_id or row.customer_id
        row.price_id = price_id or row.price_id
        row.status = status or row.status
        row.current_period_end = current_period_end or row.current_period_end
        row.user_id = str(user.id)

    await session.commit()


async def get_latest_subscription(
    session: AsyncSession, email: str
) -> Tuple[Optional[Subscription], Optional[str]]:
    """
    Returns (subscription_row, plan_name).
    Preference order:
      1) latest ACTIVE/TRIALING subscription
      2) latest subscription of any status (for display/debug)
    """
    user = await get_or_create_user(session, email)

    # Try active/trialing first
    res = await session.execute(
        select(Subscription)
        .where(Subscription.user_id == str(user.id))
        .where(Subscription.status.in_(list(ACTIVE_STATUSES)))
        .order_by(Subscription.id.desc())
        .limit(1)
    )
    sub = res.scalar_one_or_none()
    if sub:
        plan = PRICE_TO_PLAN.get(sub.price_id or "", "unknown")
        return sub, plan

    # Fallback: latest of any status
    res2 = await session.execute(
        select(Subscription)
        .where(Subscription.user_id == str(user.id))
        .order_by(Subscription.id.desc())
        .limit(1)
    )
    sub2 = res2.scalar_one_or_none()
    if sub2:
        plan2 = PRICE_TO_PLAN.get(sub2.price_id or "", "unknown")
        return sub2, plan2

    return None, None


# ----------------------------
# API Models
# ----------------------------
class CheckoutRequest(BaseModel):
    email: EmailStr
    plan: str = Field(..., description="basic|pro|enterprise")


class CheckoutResponse(BaseModel):
    url: str
    session_id: str


class SubscriptionStatusResponse(BaseModel):
    email: EmailStr
    has_active_subscription: bool
    plan: Optional[str] = None
    status: Optional[str] = None
    price_id: Optional[str] = None
    current_period_end: Optional[str] = None


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
        raise HTTPException(status_code=400, detail="Invalid plan (basic|pro|enterprise)")

    user = await get_or_create_user(session, str(payload.email))
    await session.commit()

    checkout = stripe.checkout.Session.create(
        mode="subscription",
        customer_email=str(payload.email),
        allow_promotion_codes=True,  # keep coupon box
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=SUCCESS_URL,
        cancel_url=CANCEL_URL,
        metadata={"user_id": str(user.id), "plan": plan},
    )

    logger.info("Created checkout session %s for plan %s and email %s", checkout.id, plan, payload.email)
    return CheckoutResponse(url=checkout.url, session_id=checkout.id)


@app.get("/subscription-status", response_model=SubscriptionStatusResponse)
async def subscription_status(
    email: EmailStr,
    session: AsyncSession = Depends(get_session),
):
    email_norm = str(email).strip().lower()
    sub, plan = await get_latest_subscription(session, email_norm)

    has_active = bool(sub and (sub.status in ACTIVE_STATUSES))
    cpe = sub.current_period_end.isoformat() if (sub and sub.current_period_end) else None

    return SubscriptionStatusResponse(
        email=email_norm,
        has_active_subscription=has_active,
        plan=plan if sub else None,
        status=sub.status if sub else None,
        price_id=sub.price_id if sub else None,
        current_period_end=cpe,
    )


@app.post("/stripe-webhook")
async def stripe_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    payload = await request.body()
    sig = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception:
        logger.exception("Stripe webhook signature verification failed")
        raise HTTPException(status_code=400, detail="Invalid signature")

    obj = event["data"]["object"]
    event_type = event.get("type")

    try:
        if event_type == "checkout.session.completed":
            # checkout session includes subscription + customer; email is often present
            customer_id = obj.get("customer")
            subscription_id = obj.get("subscription")
            email = await resolve_customer_email(customer_id, obj.get("customer_email"))

            if not email or not subscription_id:
                logger.warning("Missing email or subscription_id in checkout.session.completed")
                return {"received": True}

            sub = stripe.Subscription.retrieve(subscription_id, expand=["items.data.price"])
            price_id = sub["items"]["data"][0]["price"]["id"]
            status = sub.get("status")
            current_period_end = to_dt_from_unix(sub.get("current_period_end"))

            await upsert_subscription(
                session,
                email=email,
                customer_id=customer_id,
                subscription_id=subscription_id,
                price_id=price_id,
                status=status,
                current_period_end=current_period_end,
            )

        elif event_type in ("customer.subscription.updated", "customer.subscription.deleted"):
            # Subscription object typically has customer but not customer_email
            customer_id = obj.get("customer")
            email = await resolve_customer_email(customer_id, None)

            # If we cannot resolve email, we still store by subscription_id when possible,
            # but your DB schema uses email+user_id; best effort requires email.
            if not email:
                logger.warning("Could not resolve email for subscription event %s (customer=%s)", event_type, customer_id)
                return {"received": True}

            price_id = None
            try:
                # items may not be expanded in webhook; be defensive
                items = obj.get("items", {}).get("data", [])
                if items and items[0].get("price"):
                    price_id = items[0]["price"].get("id")
                else:
                    # retrieve to ensure price is available
                    sub_full = stripe.Subscription.retrieve(obj.get("id"), expand=["items.data.price"])
                    price_id = sub_full["items"]["data"][0]["price"]["id"]
            except Exception:
                logger.exception("Failed to resolve price_id for subscription event")

            await upsert_subscription(
                session,
                email=email,
                customer_id=customer_id,
                subscription_id=obj.get("id"),
                price_id=price_id,
                status=obj.get("status"),
                current_period_end=to_dt_from_unix(obj.get("current_period_end")),
            )

    except Exception:
        logger.exception("Stripe webhook handling failed for event type %s", event_type)
        # Return 200 so Stripe doesn't endlessly retry while you're iterating
        return {"received": True}

    return {"received": True}


@app.post("/generate-summary")
async def generate_summary(
    payload: GenerateSummaryRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    Enforce subscription tiers (Step A):
    - user must have an active/trialing subscription to generate a summary
    - store the summary in DB with the subscription_id attached (if available)
    """
    email_norm = str(payload.email).strip().lower()
    user = await get_or_create_user(session, email_norm)

    sub, plan = await get_latest_subscription(session, email_norm)
    if not sub or sub.status not in ACTIVE_STATUSES:
        raise HTTPException(status_code=403, detail="Active subscription required")

    row = Summary(
        user_id=str(user.id),
        subscription_id=sub.id,
        input_type=payload.input_type,
        input_name=payload.input_name,
        summary_text=payload.summary_text,
        tokens_used=payload.tokens_used,
    )
    session.add(row)
    await session.commit()

    return {"ok": True, "plan": plan}
