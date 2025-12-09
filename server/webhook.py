# ------------------- Create Checkout Session -------------------

class CheckoutRequest(BaseModel):
    plan: str
    email: str
    coupon: Optional[str] = None

@app.post("/create-checkout-session")
async def create_checkout_session(req: CheckoutRequest):
    try:
        price_id = PLAN_TO_PRICE.get(req.plan.lower())
        if not price_id:
            raise HTTPException(status_code=400, detail="Invalid plan selected.")

        checkout_params = {
            "customer_email": req.email,
            "line_items": [{"price": price_id, "quantity": 1}],
            "mode": "subscription",
            "success_url": SUCCESS_URL,
            "cancel_url": SUCCESS_URL,
        }

        # ---- NEW: Apply coupon only if provided ----
        if req.coupon:
            checkout_params["discounts"] = [{"coupon": req.coupon}]

        session = stripe.checkout.Session.create(**checkout_params)

        return {"checkout_url": session.url}

    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e.user_message))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
