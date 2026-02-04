from fastapi import FastAPI, Request, HTTPException
import requests
import os

app = FastAPI()

GA4_MEASUREMENT_ID = os.getenv("GA4_MEASUREMENT_ID")
GA4_API_SECRET = os.getenv("GA4_API_SECRET")

if not GA4_MEASUREMENT_ID or not GA4_API_SECRET:
    raise RuntimeError("GA4_MEASUREMENT_ID or GA4_API_SECRET not set")

@app.post("/calendly/webhook")
async def calendly_webhook(request: Request):
    payload = await request.json()

    # 🔍 TEMP logging for verification
    print("📩 Calendly webhook received")
    print(payload)

    event_type = payload.get("event")

    # Only care about completed bookings
    if event_type != "invitee.created":
        return {"status": "ignored"}

    try:
        invitee = payload["payload"]["invitee"]
        event = payload["payload"]["event"]
    except KeyError:
        raise HTTPException(status_code=400, detail="Malformed Calendly payload")

    user_id = invitee.get("email")

    ga4_payload = {
        "client_id": f"calendly_{invitee.get('uuid')}",
        "user_id": user_id,
        "events": [
            {
                "name": "calendly_booking_completed",
                "params": {
                    "calendly_event_name": event.get("name"),
                    "event_start_time": event.get("start_time"),
                    "invitee_email": invitee.get("email"),
                    "invitee_name": invitee.get("name"),
                    "source": "calendly_webhook"
                }
            }
        ]
    }

    response = requests.post(
        "https://www.google-analytics.com/mp/collect",
        params={
            "measurement_id": GA4_MEASUREMENT_ID,
            "api_secret": GA4_API_SECRET
        },
        json=ga4_payload,
        timeout=5
    )

    response.raise_for_status()

    return {"status": "tracked"}


@app.get("/calendly/webhook")
def webhook_test():
    return {"status": "use POST, not GET"}










