from fastapi import FastAPI, Request, HTTPException
import requests
import os

app = FastAPI()

GA4_MEASUREMENT_ID = os.getenv("GA4_MEASUREMENT_ID")
GA4_API_SECRET = os.getenv("GA4_API_SECRET")


@app.post("/calendly/webhook")
async def calendly_webhook(request: Request):
    payload = await request.json()

    print("📩 Calendly webhook received")
    print(payload)

    return {"status": "ok"}

    # Check GA4 env vars INSIDE handler
    if not GA4_MEASUREMENT_ID or not GA4_API_SECRET:
        print("❌ GA4 env vars missing")
        return {"status": "ga4_not_configured"}

    payload = await request.json()

    print("📩 Calendly webhook received")
    print(payload)

    event_type = payload.get("event")

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
        "https://www.google-analytics.com/debug/mp/collect",
        params={
            "measurement_id": GA4_MEASUREMENT_ID,
            "api_secret": GA4_API_SECRET
        },
        json=ga4_payload,
        timeout=5
    )

    print("GA4 response:", response.text)

    return {"status": "tracked"}


@app.get("/calendly/webhook")
def webhook_test():
    return {"status": "use POST, not GET"}
