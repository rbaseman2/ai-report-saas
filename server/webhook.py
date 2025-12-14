"""
server/webhook.py

Single-file FastAPI backend for:
- Stripe checkout session creation (with coupon/promo code box enabled)
- Stripe webhook processing (subscription activation/cancellation)
- Subscription status lookup by billing email
- Generate summary endpoint that accepts multipart/form-data (file + fields)
  NOTE: This fixes the UnicodeDecodeError caused by trying to parse multipart as JSON.
"""
from __future__ import annotations

import os
import json
import time
from typing import Optional, Dict, Any, Tuple

from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import stripe
import requests

# Optional dependencies for document parsing
try:
    from pypdf import PdfReader  # type: ignore
except Exception:
    PdfReader = None  # type: ignore

try:
    import docx  # python-docx
except Exception:
    docx = None  # type: ignore


# -----------------------------
# Config
# -----------------------------
def _env(*names: str, default: Optional[str] = None) -> Optional[str]:
    for n in names:
        v = os.getenv(n)
        if v is not None and str(v).strip() != "":
            return v
    return default


STRIPE_SECRET_KEY = _env("STRIPE_SECRET_KEY", "STRIPE_API_KEY", "STRIPE_KEY")
STRIPE_WEBHOOK_SECRET = _env("STRIPE_WEBHOOK_SECRET", "STRIPE_ENDPOINT_SECRET")

PRICE_BASIC = _env("STRIPE_PRICE_BASIC")
PRICE_PRO = _env("STRIPE_PRICE_PRO")
PRICE_ENTERPRISE = _env("STRIPE_PRICE_ENTERPRISE")

FRONTEND_URL = _env("FRONTEND_URL", default="http://localhost:8501")
CANCEL_URL = _env("CANCEL_URL", default=FRONTEND_URL)

OPENAI_API_KEY = _env("OPENAI_API_KEY")
BREVO_API_KEY = _env("BREVO_API_KEY")
EMAIL_FROM = _env("EMAIL_FROM")  # must be a verified sender in Brevo

if not STRIPE_SECRET_KEY:
    # We don't crash hard at import time; some endpoints can still respond with helpful errors.
    stripe.api_key = ""
else:
    stripe.api_key = STRIPE_SECRET_KEY


PLAN_BY_PRICE: Dict[str, str] = {}
if PRICE_BASIC:
    PLAN_BY_PRICE[PRICE_BASIC] = "basic"
if PRICE_PRO:
    PLAN_BY_PRICE[PRICE_PRO] = "pro"
if PRICE_ENTERPRISE:
    PLAN_BY_PRICE[PRICE_ENTERPRISE] = "enterprise"

CHAR_LIMITS = {
    "basic": 400_000,        # aligns with your UI copy
    "pro": 1_500_000,
    "enterprise": 5_000_000,
}


# -----------------------------
# App + CORS
# -----------------------------
app = FastAPI()

# Allow your Streamlit frontend to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "https://ai-report-saas.onrender.com", "https://ai-report-saas.onrender.com/"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------
# Helpers
# -----------------------------
def _require_stripe_config() -> None:
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Stripe is not configured (missing STRIPE_SECRET_KEY).")
    if not (PRICE_BASIC and PRICE_PRO and PRICE_ENTERPRISE):
        raise HTTPException(
            status_code=500,
            detail="Stripe price IDs are not configured (missing STRIPE_PRICE_BASIC/PRO/ENTERPRISE).",
        )


def _safe_email(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = s.strip()
    return s if "@" in s and "." in s else None


def _extract_text_from_upload(upload: UploadFile) -> str:
    """
    Extract plain text from supported file types.
    Keeps it simple and safe; if parsing libs are missing, we fail with a clear message.
    """
    filename = (upload.filename or "").lower()
    content = upload.file.read()  # bytes
    upload.file.close()

    # TXT / MD / CSV
    if filename.endswith((".txt", ".md", ".csv")):
        # Replace invalid bytes rather than failing.
        return content.decode("utf-8", errors="replace")

    # PDF
    if filename.endswith(".pdf"):
        if PdfReader is None:
            raise HTTPException(status_code=500, detail="PDF support not installed (missing pypdf).")
        try:
            import io
            reader = PdfReader(io.BytesIO(content))
            chunks = []
            for p in reader.pages:
                try:
                    chunks.append(p.extract_text() or "")
                except Exception:
                    chunks.append("")
            return "\n".join(chunks).strip()
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not read PDF: {e}")

    # DOCX
    if filename.endswith(".docx"):
        if docx is None:
            raise HTTPException(status_code=500, detail="DOCX support not installed (missing python-docx).")
        try:
            import io
            f = io.BytesIO(content)
            d = docx.Document(f)
            return "\n".join(p.text for p in d.paragraphs).strip()
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not read DOCX: {e}")

    raise HTTPException(status_code=400, detail="Unsupported file type. Use TXT, MD, PDF, DOCX, or CSV.")


def _stripe_find_customer_id_by_email(email: str) -> Optional[str]:
    _require_stripe_config()
    res = stripe.Customer.list(email=email, limit=1)
    if res and res.data:
        return res.data[0].id
    return None


def _stripe_get_plan_for_email(email: str) -> Tuple[str, Optional[str]]:
    """
    Returns (status, plan) where:
      status: 'active' | 'trialing' | 'past_due' | 'canceled' | 'none'
      plan:   'basic' | 'pro' | 'enterprise' | None
    """
    _require_stripe_config()

    customer_id = _stripe_find_customer_id_by_email(email)
    if not customer_id:
        return ("none", None)

    subs = stripe.Subscription.list(
        customer=customer_id,
        status="all",
        limit=10,
        expand=["data.items.data.price"],
    )
    if not subs or not subs.data:
        return ("none", None)

    # Prefer an active or trialing sub; otherwise pick the newest.
    preferred = None
    for s in subs.data:
        if s.status in ("active", "trialing"):
            preferred = s
            break
    if preferred is None:
        preferred = sorted(subs.data, key=lambda x: getattr(x, "created", 0), reverse=True)[0]

    plan = None
    try:
        price_id = preferred["items"]["data"][0]["price"]["id"]
        plan = PLAN_BY_PRICE.get(price_id)
    except Exception:
        plan = None

    return (preferred.status or "none", plan)


def _openai_summarize(text: str, plan: str) -> str:
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OpenAI is not configured (missing OPENAI_API_KEY).")

    # Keep request minimal; uses OpenAI responses via HTTPS (no SDK dependency required).
    # If you use a different model name, update here.
    model = _env("OPENAI_MODEL", default="gpt-4o-mini")

    if plan == "enterprise":
        instructions = (
            "Create an enterprise-grade document summary with:\n"
            "- Executive summary\n"
            "- Key findings (bullets)\n"
            "- Risks / red flags\n"
            "- Recommended next steps\n"
            "- Plain-language explanation for a non-expert\n"
            "Be accurate and avoid leaking personal identifiers unless relevant."
        )
    elif plan == "pro":
        instructions = (
            "Create a professional summary with:\n"
            "- Summary\n"
            "- Key points\n"
            "- Action items\n"
            "Be concise but thorough."
        )
    else:
        instructions = (
            "Create a brief, clear summary with:\n"
            "- Summary\n"
            "- 3–5 key takeaways\n"
        )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": text[:2000000]},  # guard huge payloads
        ],
        "temperature": 0.2,
    }

    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
        data=json.dumps(payload),
        timeout=90,
    )
    if r.status_code >= 300:
        raise HTTPException(status_code=500, detail=f"OpenAI error: {r.status_code} {r.text[:500]}")
    data = r.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except Exception:
        raise HTTPException(status_code=500, detail="OpenAI response parsing failed.")


def _brevo_send_email(to_email: str, subject: str, html: str) -> None:
    if not BREVO_API_KEY:
        raise HTTPException(status_code=500, detail="Email is not configured (missing BREVO_API_KEY).")
    if not EMAIL_FROM:
        raise HTTPException(status_code=500, detail="Email sender is not configured (missing EMAIL_FROM).")

    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "api-key": BREVO_API_KEY,
        "Content-Type": "application/json",
        "accept": "application/json",
    }
    payload = {
        "sender": {"email": EMAIL_FROM},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html,
    }
    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
    if resp.status_code >= 300:
        raise HTTPException(status_code=500, detail=f"Brevo email failed: {resp.status_code} {resp.text[:500]}")


# -----------------------------
# Routes
# -----------------------------
@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "stripe_configured": bool(STRIPE_SECRET_KEY),
        "prices_configured": bool(PRICE_BASIC and PRICE_PRO and PRICE_ENTERPRISE),
        "openai_configured": bool(OPENAI_API_KEY),
        "email_configured": bool(BREVO_API_KEY and EMAIL_FROM),
        "ts": int(time.time()),
    }


@app.get("/subscription-status")
def subscription_status(email: str = Query(...)) -> Dict[str, Any]:
    email = (email or "").strip()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required.")
    status, plan = _stripe_get_plan_for_email(email)
    return {"email": email, "status": status, "plan": plan}


@app.post("/create-checkout-session")
async def create_checkout_session(request: Request) -> Dict[str, Any]:
    """
    Expects JSON: { "email": "...", "plan": "basic|pro|enterprise" }
    Returns: { "url": "https://checkout.stripe.com/..." }
    """
    _require_stripe_config()

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON.")

    email = _safe_email(body.get("email"))
    plan = (body.get("plan") or "").strip().lower()

    if not email:
        raise HTTPException(status_code=400, detail="Valid email is required.")
    if plan not in ("basic", "pro", "enterprise"):
        raise HTTPException(status_code=400, detail="Plan must be basic, pro, or enterprise.")

    price_id = {
        "basic": PRICE_BASIC,
        "pro": PRICE_PRO,
        "enterprise": PRICE_ENTERPRISE,
    }.get(plan)

    if not price_id:
        raise HTTPException(status_code=500, detail="Price ID missing for selected plan.")

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer_email=email,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{FRONTEND_URL}/Billing?status=success&session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{CANCEL_URL}/Billing?status=cancel",
        allow_promotion_codes=True,  # <-- coupon/promo code box
    )
    return {"url": session.url}


@app.post("/webhook")
async def stripe_webhook(request: Request):
    """
    Stripe sends raw bytes; verify signature then process.
    """
    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Missing STRIPE_WEBHOOK_SECRET.")

    try:
        event = stripe.Webhook.construct_event(payload=payload, sig_header=sig, secret=STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Webhook signature verification failed: {e}")

    # Minimal processing: you can persist subscription/customer mapping in DB if desired.
    # For now, we just acknowledge.
    return {"received": True, "type": event.get("type")}


@app.post("/generate-summary")
async def generate_summary(
    billing_email: str = Form(...),
    recipient_email: Optional[str] = Form(None),
    text: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
):
    """
    IMPORTANT:
    This endpoint is called by Streamlit using requests.post(data=payload, files=files).
    That is multipart/form-data, not JSON.
    The previous implementation used `await request.json()` which caused:
      UnicodeDecodeError: 'utf-8' codec can't decode byte ... (because the body includes binary PDF bytes)

    This implementation accepts proper Form + File params.
    """
    billing_email = (billing_email or "").strip()
    if not billing_email:
        raise HTTPException(status_code=400, detail="billing_email is required.")

    recipient_email = _safe_email(recipient_email) if recipient_email else None

    extracted = ""
    if file is not None:
        extracted = _extract_text_from_upload(file)
    if text and text.strip():
        # Manual text overrides/augments extracted content.
        extracted = (extracted + "\n\n" + text.strip()).strip() if extracted else text.strip()

    if not extracted:
        raise HTTPException(status_code=400, detail="Provide a file or text to summarize.")

    status, plan = _stripe_get_plan_for_email(billing_email)
    # If no plan found but subscription exists, treat as lowest tier; you can change this behavior.
    plan = plan or "basic"

    # Enforce limits
    limit = CHAR_LIMITS.get(plan, CHAR_LIMITS["basic"])
    if len(extracted) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"Input too large for {plan} plan ({len(extracted):,} chars). Limit is {limit:,}.",
        )

    summary = _openai_summarize(extracted, plan)

    email_sent = False
    if recipient_email:
        # Simple HTML email
        subject = f"Your {plan.capitalize()} Summary"
        html = f"""
        <div style="font-family: Arial, sans-serif; line-height:1.4">
          <h2>{subject}</h2>
          <pre style="white-space:pre-wrap; font-family: Arial, sans-serif">{summary}</pre>
        </div>
        """
        _brevo_send_email(recipient_email, subject, html)
        email_sent = True

    return JSONResponse(
        {
            "status": "ok",
            "subscription_status": status,
            "plan": plan,
            "summary": summary,
            "email_sent": email_sent,
            "recipient_email": recipient_email,
        }
    )
