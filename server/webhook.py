# server/webhook.py
import os
import json
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text

import stripe
from .db import engine, create_tables, ping

# --- Boot-time setup ---------------------------------------------------------
stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
WEBHOOK_SECRET = os.environ["STRIPE_WEBHOOK_SECRET"]

# Make sure tables exist and DB is reachable
create_tables()
ping()

app = FastAPI()

@app.get("/health")
def health():
    return {"ok": True}

# Small helper to insert an event idempotently
def _record_event(event_dict: dict) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO stripe_events(event_id, type, payload)
                VALUES (:event_id, :type, CAST(:payload AS JSONB))
                ON CONFLICT (event_id) DO NOTHING
            """),
            {
                "event_id": event_dict["id"],
                "type": event_dict["type"],
                "payload": json.dumps(event_dict),
            },
        )

# Upsert a subscription row
def _upsert_subscription(*, customer_id: str, email: str | None,
                         subscription_id: str, price_id: str | None,
                         status: str | None, current_period_end: int | None) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO subscriptions
                  (customer_id, email, subscription_id, price_id, status, current_period_end)
                VALUES
                  (:customer_id, :email, :subscription_id, :price_id, :status,
                   CASE WHEN :current_period_end IS NULL
                        THEN NULL
                        ELSE to_timestamp(:current_period_end) END)
                ON CONFLICT (subscription_id) DO UPDATE
                SET status = EXCLUDED.status,
                    price_id = COALESCE(EXCLUDED.price_id, subscriptions.price_id),
                    email = COALESCE(EXCLUDED.email, subscriptions.email),
                    current_period_end = COALESCE(EXCLUDED.current_period_end, subscriptions.current_period_end)
            """),
            {
                "customer_id": customer_id,
                "email": email,
                "subscription_id": subscription_id,
                "price_id": price_id,
                "status": status,
                "current_period_end": current_period_end,
            },
        )

@app.post("/webhook")
async def stripe_webhook(request: Request):
    raw = await request.body()
    sig = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload=raw, sig_header=sig, secret=WEBHOOK_SECRET
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Store raw event (idempotent)
    _record_event(event)

    etype = event["type"]

    # ---------------------------------------------------------------------------------
    # 1) checkout.session.completed — user finished checkout, create/attach subscription
    # ---------------------------------------------------------------------------------
    if etype == "checkout.session.completed":
        session = event["data"]["object"]

        customer_id = session.get("customer")
        email = session.get("customer_details", {}).get("email")
        subscription_id = session.get("subscription")
        price_id = session.get("metadata", {}).get("price_id")
        status = None
        current_period_end = None

        # Fetch subscription to enrich details (status/period end/price)
        if subscription_id:
            sub = stripe.Subscription.retrieve(
                subscription_id, expand=["items.data.price"]
            )
            status = sub.get("status")
            current_period_end = sub.get("current_period_end")
            if not price_id:
                items = sub.get("items", {}).get("data", [])
                if items:
                    price_id = items[0].get("price", {}).get("id")

        if customer_id and subscription_id:
            _upsert_subscription(
                customer_id=customer_id,
                email=email,
                subscription_id=subscription_id,
                price_id=price_id,
                status=status,
                current_period_end=current_period_end,
            )

    # ---------------------------------------------------------------------------------
    # 2) Subscription lifecycle events — keep status/dates up to date
    # ---------------------------------------------------------------------------------
    elif etype in ("customer.subscription.created",
                   "customer.subscription.updated",
                   "customer.subscription.deleted"):
        sub = event["data"]["object"]
        customer_id = sub.get("customer")
        subscription_id = sub.get("id")
        status = sub.get("status")
        current_period_end = sub.get("current_period_end")
        items = sub.get("items", {}).get("data", [])
        price_id = items[0].get("price", {}).get("id") if items else None

        # Email isn’t on subscription; we’ll leave None here.
        if customer_id and subscription_id:
            _upsert_subscription(
                customer_id=customer_id,
                email=None,
                subscription_id=subscription_id,
                price_id=price_id,
                status=status,
                current_period_end=current_period_end,
            )

    return JSONResponse({"received": True})


# Optional: quick helper endpoint to check a user's plan/status by email
@app.get("/entitlement/{email}")
def entitlement(email: str):
    row = None
    with engine.begin() as conn:
        row = conn.execute(
            text("""
                SELECT price_id, status
                FROM subscriptions
                WHERE email = :email
                ORDER BY id DESC
                LIMIT 1
            """),
            {"email": email},
        ).mappings().first()

    if not row:
        return {"email": email, "plan": None, "status": "none"}
    return {"email": email, "plan": row["price_id"], "status": row["status"]}
