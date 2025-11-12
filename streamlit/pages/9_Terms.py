# streamlit/pages/9_Terms.py
import os
import datetime
import streamlit as st

st.set_page_config(page_title="Terms of Service", page_icon="📜", layout="centered")

# --- Brand / contact (edit if you changed these in Billing) ---
BUSINESS_NAME = os.getenv("BUSINESS_NAME", "AI Report")
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "support@yourdomain.com")
BILLING_EMAIL = os.getenv("BILLING_EMAIL", "billing@yourdomain.com")
LAST_UPDATED = os.getenv("TERMS_LAST_UPDATED", datetime.date.today().isoformat())

st.title("Terms of Service")
st.caption(f"Last updated: {LAST_UPDATED}")

st.markdown(
f"""
Welcome to **{BUSINESS_NAME}**. By accessing or using our services, websites, and applications
(collectively, the “Service”), you agree to these Terms of Service (“Terms”). If you do not agree,
do not use the Service.

## 1) Your Account
You are responsible for maintaining the confidentiality of your account and credentials and for all activities
that occur under your account. You must provide accurate information and promptly update it as needed.

## 2) Acceptable Use
You agree not to misuse the Service. Prohibited uses include:
- Violating any applicable law or third-party rights
- Attempting to reverse engineer, bypass, or disrupt security or access controls
- Transmitting malware or harmful content
- Abusive, harassing, or discriminatory behavior toward others

We may suspend or terminate accounts that violate these Terms.

## 3) Subscriptions, Billing, and Taxes
Certain features require a paid subscription billed on a recurring basis through our payment provider
(Stripe). By subscribing, you authorize recurring charges until cancellation. Prices may change with
notice. Applicable taxes (e.g., sales tax or VAT) are calculated automatically during checkout.

For billing questions, contact **{BILLING_EMAIL}**.

## 4) Cancellations and Refunds
You can cancel at any time from the Billing Portal; your access continues until the end of the current
billing period. Refund requests are evaluated case-by-case per our Refund Policy (see Pricing FAQ or
contact **{SUPPORT_EMAIL}**).

## 5) Intellectual Property
We (and our licensors) retain ownership of the Service and all associated intellectual property.
You retain ownership of the content and data you submit to the Service. By submitting content, you
grant us the limited rights necessary to operate and improve the Service (e.g., processing your inputs,
generating outputs, and maintaining backups).

## 6) AI Outputs and Accuracy
The Service may generate AI-assisted outputs. While we aim for quality, AI can be fallible. You are
responsible for validating results before relying on them for critical decisions.

## 7) Data Protection and Privacy
Our use of your data is described in our Privacy Policy. By using the Service, you consent to our
data practices described there.

## 8) Service Changes and Availability
We may add, modify, or discontinue features with or without notice. We strive for high availability but do not
guarantee uninterrupted service. For Enterprise plans, uptime targets are stated in your plan description.

## 9) Third-Party Services
The Service may interoperate with third-party products (e.g., Stripe). Their terms and privacy policies apply
to your use of those products.

## 10) Disclaimers; Limitation of Liability
The Service is provided “as is” without warranties of any kind. To the maximum extent permitted by law,
{BUSINESS_NAME} and its affiliates are not liable for indirect, incidental, special, or consequential damages,
or any loss of data, profits, or business opportunities.

## 11) Indemnification
You agree to indemnify and hold {BUSINESS_NAME} harmless from claims arising from your misuse of the Service
or violation of these Terms.

## 12) Governing Law; Disputes
These Terms are governed by the laws of the jurisdiction where {BUSINESS_NAME} is organized, without regard
to conflict-of-law rules. Disputes will be resolved in the courts of that jurisdiction unless otherwise
required by law.

## 13) Changes to These Terms
We may update these Terms from time to time. If changes are material, we will provide reasonable notice
(e.g., in-app notice or email). Your continued use constitutes acceptance of the updated Terms.

---

**Questions?** Email **{SUPPORT_EMAIL}**.
"""
)
