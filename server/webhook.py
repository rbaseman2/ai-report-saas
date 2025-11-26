# ---------- NEW: model for subscription status ----------

from pydantic import BaseModel, EmailStr

class SubscriptionStatusRequest(BaseModel):
    email: EmailStr
    # Stripe sends us back ?session_id=cs_... in the URL after checkout
    session_id: str | None = None


# Map Stripe price IDs -> internal plan names
PRICE_BASIC_ID = os.getenv("PRICE_BASIC")
PRICE_PRO_ID = os.getenv("PRICE_PRO")
PRICE_ENTERPRISE_ID = os.getenv("PRICE_ENTERPRISE")

PLAN_BY_PRICE_ID = {
    PRICE_BASIC_ID: "basic",
    PRICE_PRO_ID: "pro",
    PRICE_ENTERPRISE_ID: "enterprise",
}

# Optional: simple per-plan document limits the frontend can use
PLAN_MAX_DOCS = {
    "free": 1,
    "basic": 5,
    "pro": 30,
    "enterprise": 9999,
}


# ---------- NEW: /subscription-status endpoint ----------

@app.post("/subscription-status")
async def subscription_status(payload: SubscriptionStatusRequest):
    """
    Determine the user's plan.

    Priority:
    1) If a Checkout `session_id` is provided, look up the subscription from that.
    2) Otherwise, fall back to searching by email.
    3) If nothing is found, treat the user as 'free'.
    """

    email = payload.email
    session_id = payload.session_id
    subscription = None
    customer = None

    # 1) Try via Checkout Session (most reliable right after checkout)
    if session_id:
        try:
            session = stripe.checkout.Session.retrieve(
                session_id,
                expand=["subscription", "customer"],
            )
            subscription = session.subscription
            customer = session.customer
        except stripe.error.InvalidRequestError:
            # Bad or expired session_id – we silently fall back to email lookup
            subscription = None
        except Exception as exc:
            # Unexpected error -> log and fail gracefully as "free"
            print(f"[subscription-status] Error retrieving session {session_id}: {exc}")

    # 2) Fallback: search Stripe customers by email
    if subscription is None:
        try:
            customers = stripe.Customer.list(email=email, limit=5)
            for cust in customers.data:
                subs = stripe.Subscription.list(customer=cust.id, status="all", limit=10)
                for sub in subs.data:
                    if sub.status in ("active", "trialing"):
                        subscription = sub
                        customer = cust
                        break
                if subscription is not None:
                    break
        except Exception as exc:
            print(f"[subscription-status] Error searching by email {email}: {exc}")
            subscription = None

    # 3) Work out plan based on the subscription we found (if any)
    plan = "free"

    try:
        if subscription is not None and subscription.status in ("active", "trialing"):
            # Use the first subscription item’s price
            items = subscription["items"]["data"]
            if items:
                price_id = items[0]["price"]["id"]
                plan = PLAN_BY_PRICE_ID.get(price_id, "free")
    except Exception as exc:
        print(f"[subscription-status] Error deriving plan from subscription: {exc}")
        plan = "free"

    max_docs = PLAN_MAX_DOCS.get(plan, PLAN_MAX_DOCS["free"])

    return {
        "plan": plan,
        "max_documents": max_docs,
        "email": email,
        "checked_via": "session" if session_id else "email",
    }
