# streamlit/pages/10_Privacy.py
import os
import datetime
import streamlit as st

st.set_page_config(page_title="Privacy Policy", page_icon="🔒", layout="centered")

# --- Brand / contact (edit if you changed these in Billing) ---
BUSINESS_NAME = os.getenv("BUSINESS_NAME", "AI Report")
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "support@yourdomain.com")
BILLING_EMAIL = os.getenv("BILLING_EMAIL", "billing@yourdomain.com")
LAST_UPDATED = os.getenv("PRIVACY_LAST_UPDATED", datetime.date.today().isoformat())

st.title("Privacy Policy")
st.caption(f"Last updated: {LAST_UPDATED}")

st.markdown(
f"""
Your privacy matters to **{BUSINESS_NAME}**. This Privacy Policy explains what data we collect, how we use it,
and your choices.

## 1) Information We Collect
- **Account Data**: Name, email, and settings you provide.
- **Billing Data**: Payment details processed by our provider (Stripe). We do not store full card numbers.
- **Usage Data**: Log data (e.g., IP, device information), activity events, and diagnostic information.
- **Content/Data You Provide**: Inputs, files, or prompts you submit; generated outputs; and feedback.

## 2) How We Use Your Information
We use your information to:
- Provide, maintain, and improve the Service
- Personalize your experience and features
- Process payments and manage subscriptions
- Prevent abuse, secure the Service, and troubleshoot issues
- Communicate about updates, new features, and support

## 3) Legal Bases (where applicable)
We process data based on consent, contractual necessity, legitimate interests (e.g., service improvement,
security), and compliance with legal obligations.

## 4) Sharing and Disclosure
We do not sell your personal information. We may share limited data with:
- **Service Providers** (e.g., Stripe for payments, hosting providers) under confidentiality agreements
- **Legal/Compliance** when required by law or to protect rights, safety, and security
- **Business Transfers** in the event of a merger, acquisition, or asset sale, in accordance with this policy

## 5) Data Retention
We retain data for as long as necessary to provide the Service and for legitimate business needs (e.g., legal,
security, and accounting requirements). You may request deletion of your personal data, subject to legal
obligations and technical feasibility.

## 6) Security
We take reasonable administrative, technical, and organizational measures to protect your data. However,
no method of transmission or storage is 100% secure; use the Service with this in mind.

## 7) Your Choices and Rights
Depending on your jurisdiction, you may have rights to access, correct, delete, or export personal data,
and to object to or restrict certain processing. To exercise rights or ask questions, email **{SUPPORT_EMAIL}**.

## 8) International Data Transfers
If we transfer personal data across borders, we use appropriate safeguards (e.g., contractual clauses) as
required by applicable law.

## 9) Cookies and Similar Technologies
We may use cookies and similar technologies to provide essential functionality, remember preferences,
and analyze usage. You can control cookies through your browser settings.

## 10) Children’s Privacy
The Service is not directed to children under the age of 13 (or as defined by local law). We do not
knowingly collect personal information from children.

## 11) Changes to This Policy
We may update this Privacy Policy to reflect changes in our practices. We will post updates here and,
when appropriate, notify you via email or in-app notice. Your continued use constitutes acceptance of the updates.

---

**Questions or requests?** Email **{SUPPORT_EMAIL}**.  
For billing-related inquiries, contact **{BILLING_EMAIL}**.
"""
)
