@app.get("/subscription-status", response_model=SubscriptionStatusResponse)
async def subscription_status(email: EmailStr) -> SubscriptionStatusResponse:
    """
    Given a customer email, look up the latest Stripe subscription and map it to
    one of our plan names (basic/pro/enterprise). If nothing is found, return
    the 'free' plan.
    """
    # If Stripe isn't configured, just treat everyone as on the free plan
    if not STRIPE_SECRET_KEY:
        limits = SUBSCRIPTION_LIMITS["free"]
        return SubscriptionStatusResponse(
            plan="free",
            status="inactive",
            current_period_end=None,
            limits=limits,
        )

    try:
        # 1) Find customer by email
        customers = stripe.Customer.list(email=email, limit=1)
        if not customers.data:
            limits = SUBSCRIPTION_LIMITS["free"]
            return SubscriptionStatusResponse(
                plan="free",
                status="inactive",
                current_period_end=None,
                limits=limits,
            )

        customer = customers.data[0]

        # 2) Get most recent subscription (any status)
        subs = stripe.Subscription.list(customer=customer.id, status="all", limit=1)
        if not subs.data:
            limits = SUBSCRIPTION_LIMITS["free"]
            return SubscriptionStatusResponse(
                plan="free",
                status="inactive",
                current_period_end=None,
                limits=limits,
            )

        sub = subs.data[0]

        # 3) Work out which plan this subscription maps to
        price_id = sub["items"]["data"][0]["price"]["id"]
        plan_name = PRICE_TO_PLAN.get(price_id, "unknown")

        limits = SUBSCRIPTION_LIMITS.get(plan_name, SUBSCRIPTION_LIMITS["free"])

        # 4) Safely get current_period_end (may not exist on some objects)
        current_period_end = sub.get("current_period_end", None)

        return SubscriptionStatusResponse(
            plan=plan_name,
            status=sub.status,
            current_period_end=current_period_end,
            limits=limits,
        )

    except Exception as e:  # noqa: BLE001
        logging.exception("Error looking up subscription status: %s", e)
        limits = SUBSCRIPTION_LIMITS["free"]
        return SubscriptionStatusResponse(
            plan="free",
            status="error",
            current_period_end=None,
            limits=limits,
        )
