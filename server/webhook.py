"""
server/webhook.py
FastAPI backend for AI Report SaaS

Goals:
- Keep the existing working contract for the Streamlit frontend.
- Be tolerant of environment variable naming differences (Render vs local).
- Provide BOTH legacy + newer response keys to avoid breaking UI pages.

Endpoints used by frontend:
- GET  /health
- GET  /subscription-status?email=...
- POST /create-checkout-session   {email, plan}
- POST /upload                   multipart/form-data (file + account_email)
- POST /generate-summary          (JSON or multipart) -> returns summary, and can email it
- POST /webhook                   Stripe webhook endpoint
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import stripe
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

logger = logging.getLogger("ai_report_backend")
logging.basicConfig(level=logging.INFO)

app = FastAPI()

# -----------------------------
# CORS
# -----------------------------
FRONTEND_URL = os.getenv("FRONTEND_URL", "*")
allowed_origins = ["*"] if FRONTEND_URL in ("*", "", None) else [FRONTEND_URL]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# Environment / Stripe config
# -----------------------------
# Render UI shows STRIPE_API_KEY; many tutorials use STRIPE_SECRET_KEY.
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY") or os.getenv("STRIPE_API_KEY") or ""
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET") or ""

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or ""
BREVO_API_KEY = os.getenv("BREVO_API_KEY") or os.getenv("SENDINBLUE_API_KEY") or ""
EMAIL_FROM = os.getenv("EMAIL_FROM") or os.getenv("SENDER_EMAIL") or ""

# Stripe prices (must be set in Render for live)
STRIPE_PRICE_BASIC = os.getenv("STRIPE_PRICE_BASIC") or ""
STRIPE_PRICE_PRO = os.getenv("STRIPE_PRICE_PRO") or ""
STRIPE_PRICE_ENTERPRISE = os.getenv("STRIPE_PRICE_ENTERPRISE") or ""

PLAN_ALIASES = {
    "basic": "basic",
    "starter": "basic",
    "free": "basic",
    "pro": "pro",
    "professional": "pro",
    "plus": "pro",
    "enterprise": "enterprise",
    "ent": "enterprise",
    "business": "enterprise",
}

PLAN_TO_PRICE = {
    "basic": STRIPE_PRICE_BASIC,
    "pro": STRIPE_PRICE_PRO,
    "enterprise": STRIPE_PRICE_ENTERPRISE,
}

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY


def normalize_plan(plan: str) -> str:
    p = (plan or "").strip().lower()
    p = PLAN_ALIASES.get(p, p)
    return p


def require_env(value: str, name: str) -> None:
    if not value:
        raise HTTPException(status_code=500, detail=f"{name} is not set in environment variables.")


# -----------------------------
# In-memory upload store
# (Good enough for now; later you can move this to DB or S3)
# -----------------------------
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR") or "/tmp/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# upload_id -> dict(path, filename, content_type, created_at, sha256)
UPLOAD_INDEX: Dict[str, Dict[str, Any]] = {}


# -----------------------------
# Models
# -----------------------------
class CheckoutRequest(BaseModel):
    email: EmailStr
    plan: str


class UploadResponse(BaseModel):
    upload_id: str
    filename: str
    content_type: str
    bytes: int


class GenerateSummaryJSONRequest(BaseModel):
    # Either provide 'content' (text) OR 'upload_id' (previously uploaded file).
    content: Optional[str] = None
    upload_id: Optional[str] = None
    recipient_email: Optional[EmailStr] = None
    email_summary: bool = True


# -----------------------------
# Helpers
# -----------------------------
def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_upload(upload_id: str) -> Tuple[bytes, Dict[str, Any]]:
    meta = UPLOAD_INDEX.get(upload_id)
    if not meta:
        raise HTTPException(status_code=404, detail="upload_id not found (please re-upload).")
    path = Path(meta["path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Uploaded file missing on server (please re-upload).")
    return path.read_bytes(), meta


def _extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """
    Best-effort PDF text extraction.
    """
    try:
        # pypdf is lightweight and commonly available
        from pypdf import PdfReader  # type: ignore
        reader = PdfReader(io.BytesIO(pdf_bytes))
        parts = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        return "\n".join(parts).strip()
    except Exception:
        # fallback to PyPDF2 if installed
        try:
            import PyPDF2  # type: ignore
            reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
            parts = []
            for page in reader.pages:
                parts.append(page.extract_text() or "")
            return "\n".join(parts).strip()
        except Exception:
            return ""


def _simple_summary(text: str, max_chars: int = 6000) -> str:
    """
    Minimal, deterministic summary (keeps app working even if OpenAI key isn't configured yet).
    If OPENAI_API_KEY is set, you can later swap this to a real LLM call.
    """
    t = (text or "").strip()
    if not t:
        return "No text content was provided."
    t = t[:max_chars]
    # simple heuristic: return first chunk with a header
    return f"Summary (preview):\n\n{t[:1500]}"


def _send_email_brevo(to_email: str, subject: str, html: str) -> bool:
    """
    Sends email via Brevo if configured. Returns True if sent, False otherwise.
    """
    if not (BREVO_API_KEY and EMAIL_FROM):
        logger.warning("Email not sent: BREVO_API_KEY and/or EMAIL_FROM not configured.")
        return False

    try:
        import requests  # type: ignore
        url = "https://api.brevo.com/v3/smtp/email"
        headers = {"api-key": BREVO_API_KEY, "Content-Type": "application/json", "accept": "application/json"}
        payload = {
            "sender": {"email": EMAIL_FROM, "name": "AI Report"},
            "to": [{"email": to_email}],
            "subject": subject,
            "htmlContent": html,
        }
        r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=20)
        if r.status_code >= 200 and r.status_code < 300:
            return True
        logger.error("Brevo send failed: %s %s", r.status_code, r.text)
        return False
    except Exception:
        logger.exception("Brevo send failed with exception")
        return False


# -----------------------------
# Routes
# -----------------------------
@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/subscription-status")
def subscription_status(email: str) -> Dict[str, Any]:
    """
    Return keys expected by Billing page:
      - plan (basic/pro/enterprise or None)
      - status (active/trialing/canceled/none)
    Also returns richer keys for future use (backward compatible).
    """
    # If Stripe isn't configured, don't 500 the UI.
    if not STRIPE_SECRET_KEY:
        return {
            "email": email,
            "plan": None,
            "status": "none",
            "has_customer": False,
            "has_active_subscription": False,
            "current_plan": None,
            "subscription_status": "none",
            "current_period_end": None,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            "note": "Stripe not configured (missing STRIPE_SECRET_KEY/STRIPE_API_KEY).",
        }

    try:
        customers = stripe.Customer.list(email=email, limit=1)
        if not customers.data:
            return {
                "email": email,
                "plan": None,
                "status": "none",
                "has_customer": False,
                "has_active_subscription": False,
                "current_plan": None,
                "subscription_status": "none",
                "current_period_end": None,
                "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            }

        customer = customers.data[0]
        subs = stripe.Subscription.list(
            customer=customer.id,
            status="all",
            limit=10,
            expand=["data.items.data.price"],
        )

        chosen = None
        if subs.data:
            # prefer active/trialing, else most recent
            active = [s for s in subs.data if s.status in ("active", "trialing")]
            chosen = active[0] if active else subs.data[0]

        if not chosen:
            return {
                "email": email,
                "plan": None,
                "status": "none",
                "has_customer": True,
                "has_active_subscription": False,
                "current_plan": None,
                "subscription_status": "none",
                "current_period_end": None,
                "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            }

        price_id = None
        try:
            price_id = chosen["items"]["data"][0]["price"]["id"]
        except Exception:
            price_id = None

        current_plan = None
        if price_id:
            for plan_name, env_price in PLAN_TO_PRICE.items():
                if env_price and env_price == price_id:
                    current_plan = plan_name
                    break

        has_active = chosen.status in ("active", "trialing")

        return {
            # keys Billing.py expects
            "email": email,
            "plan": current_plan if has_active else None,
            "status": chosen.status if chosen.status else "none",
            # extra keys (keep compatibility)
            "has_customer": True,
            "has_active_subscription": has_active,
            "current_plan": current_plan,
            "subscription_status": chosen.status,
            "current_period_end": int(getattr(chosen, "current_period_end", 0) or 0) or None,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
    except stripe.error.StripeError as e:
        logger.exception("Stripe error in subscription-status")
        raise HTTPException(status_code=500, detail=str(e.user_message or str(e)))


@app.post("/create-checkout-session")
def create_checkout_session(req: CheckoutRequest) -> Dict[str, Any]:
    require_env(STRIPE_SECRET_KEY, "STRIPE_SECRET_KEY (or STRIPE_API_KEY)")
    plan = normalize_plan(req.plan)

    if plan not in PLAN_TO_PRICE:
        raise HTTPException(status_code=400, detail="Invalid plan")

    price_id = PLAN_TO_PRICE.get(plan, "")
    if not price_id:
        raise HTTPException(status_code=500, detail=f"Stripe price id for plan '{plan}' is not set (missing STRIPE_PRICE_{plan.upper()}).")

    # Default return URLs (frontend can just redirect to Stripe; success will land on frontend)
    success_url = os.getenv("SUCCESS_URL") or f"{FRONTEND_URL}/Upload_Data"
    cancel_url = os.getenv("CANCEL_URL") or f"{FRONTEND_URL}/Billing"

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{success_url}?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=cancel_url,
            customer_email=req.email,
            allow_promotion_codes=True,
        )
        checkout_url = session.url
        logger.info("Created checkout session %s for %s (%s)", session.id, req.email, plan)

        # Return BOTH keys (some frontends look for checkout_url, others url)
        return {"checkout_url": checkout_url, "url": checkout_url, "session_id": session.id}
    except Exception:
        logger.exception("create-checkout-session failed")
        raise HTTPException(status_code=500, detail="Checkout session failed. Check server logs.")


@app.post("/webhook")
async def stripe_webhook(request: Request) -> Dict[str, Any]:
    """
    Stripe webhook endpoint. Configure Stripe to post to:
      https://<your-backend>/webhook
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not STRIPE_WEBHOOK_SECRET:
        # Don't break in dev; just acknowledge.
        logger.warning("STRIPE_WEBHOOK_SECRET not set; skipping signature verification.")
        return {"received": True, "verified": False}

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception:
        logger.exception("Stripe webhook signature verification failed")
        raise HTTPException(status_code=400, detail="Invalid signature")

    # You can extend these handlers later.
    try:
        event_type = event["type"]
        logger.info("Stripe webhook received: %s", event_type)
    except Exception:
        event_type = "unknown"

    return {"received": True, "verified": True, "type": event_type}


@app.post("/upload", response_model=UploadResponse)
async def upload(
    file: UploadFile = File(...),
    account_email: str = Form(...),
) -> UploadResponse:
    """
    Upload a PDF (or any file). Returns an upload_id.
    Streamlit can store upload_id in session_state.
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload")

    upload_id = uuid.uuid4().hex
    safe_name = (file.filename or "upload.bin").replace("\\", "_").replace("/", "_")
    path = UPLOAD_DIR / f"{upload_id}__{safe_name}"
    path.write_bytes(data)

    meta = {
        "path": str(path),
        "filename": safe_name,
        "content_type": file.content_type or "application/octet-stream",
        "bytes": len(data),
        "sha256": _sha256(data),
        "account_email": account_email,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    UPLOAD_INDEX[upload_id] = meta

    return UploadResponse(upload_id=upload_id, filename=safe_name, content_type=meta["content_type"], bytes=meta["bytes"])


@app.post("/generate-summary")
async def generate_summary(request: Request) -> Dict[str, Any]:
    """
    Accepts either:
    - JSON: {content?, upload_id?, recipient_email?, email_summary?}
    - multipart/form-data:
        file (optional) OR upload_id
        recipient_email (optional)
        email_summary (optional)
        content (optional)
    Returns:
      {summary: "...", emailed: bool, upload_id?: "..."}
    """
    content_type = request.headers.get("content-type", "")
    recipient_email: Optional[str] = None
    email_summary: bool = True
    content_text: Optional[str] = None
    upload_id: Optional[str] = None
    file_bytes: Optional[bytes] = None
    file_meta: Optional[Dict[str, Any]] = None

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        recipient_email = (form.get("recipient_email") or form.get("email") or None)
        email_summary = str(form.get("email_summary") or "true").lower() not in ("0", "false", "no")
        content_text = (form.get("content") or None)
        upload_id = (form.get("upload_id") or None)

        upl = form.get("file")
        if isinstance(upl, UploadFile):
            file_bytes = await upl.read()
            file_meta = {"filename": upl.filename, "content_type": upl.content_type}
    else:
        try:
            payload = await request.json()
        except Exception:
            payload = {}

        # tolerate non-dict payloads
        if not isinstance(payload, dict):
            payload = {}

        recipient_email = payload.get("recipient_email")
        email_summary = bool(payload.get("email_summary", True))
        content_text = payload.get("content")
        upload_id = payload.get("upload_id")

    if file_bytes:
        # PDF? extract; else treat as text bytes (best effort)
        extracted = ""
        if (file_meta or {}).get("content_type", "").lower().endswith("pdf") or (file_meta or {}).get("filename", "").lower().endswith(".pdf"):
            extracted = _extract_text_from_pdf(file_bytes)
        if not extracted:
            try:
                extracted = file_bytes.decode("utf-8", errors="ignore")
            except Exception:
                extracted = ""
        content_text = (content_text or "") + ("\n\n" + extracted if extracted else "")

    if upload_id and not content_text:
        raw, meta = _read_upload(upload_id)
        if str(meta.get("content_type", "")).lower().endswith("pdf") or str(meta.get("filename", "")).lower().endswith(".pdf"):
            content_text = _extract_text_from_pdf(raw)
        else:
            content_text = raw.decode("utf-8", errors="ignore")

    summary = _simple_summary(content_text or "")

    emailed = False
    if recipient_email and email_summary:
        html = f"<h2>Your AI Report Summary</h2><pre style='white-space:pre-wrap'>{summary}</pre>"
        emailed = _send_email_brevo(recipient_email, "Your AI Report Summary", html)

    return {"summary": summary, "emailed": emailed, "upload_id": upload_id}
