import os, stripe
from fastapi import HTTPException
from stripe.error import StripeError, InvalidRequestError

PLAN_TO_PRICE = {
    "basic": os.environ["PRICE_BASIC"],
    "pro": os.environ["PRICE_PRO"],
    "enterprise": os.environ["PRICE_ENTERPRISE"],
}

@router.post("/create-checkout-session")
def create_checkout_session(body: Body):
    # 1) Resolve plan -> price id
    price_id = PLAN_TO_PRICE.get(body.plan)
    if not price_id:
        raise HTTPException(400, "Unknown plan")

    # 2) DEBUG LOG (outside/above the try is fine)
    print(f">>> DEBUG plan={body.plan}, price_id={price_id}", flush=True)

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=os.environ["SUCCESS_URL"] + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=os.environ["CANCEL_URL"],
            automatic_tax={"enabled": True},
        )
        return {"url": session.url}

    except InvalidRequestError as e:
        raise HTTPException(400, e.user_message or str(e))
    except StripeError:
        raise HTTPException(400, "Payment provider error")
    except Exception:
        raise HTTPException(500, "Checkout creation failed")
