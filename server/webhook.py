@app.get("/subscription-status", response_model=SubscriptionStatusResponse)
async def subscription_status(email: EmailStr) -> SubscriptionStatusResponse:
    """
    Given a customer email, look up the latest Stripe subscription and map it to
    one of our plan names (basic/pro/enterprise). If nothing is found, return
    the 'free' plan.
    """
    if not STRIPE_SECRET_KEY:
        # No Stripe configured → treat as free
        limits = SUBSCRIPTION_LIMITS["free"]
        return SubscriptionStatusResponse(
            plan="free", status="inactive", current_period_end=None, limits=limits
        )

    try:
        customers = stripe.Customer.list(email=email, limit=1)
        ...
