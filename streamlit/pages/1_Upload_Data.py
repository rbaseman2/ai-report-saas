# --- path shim so `from app.*` works from /streamlit/pages ---
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

import streamlit as st
import pandas as pd
import json, traceback
from datetime import datetime

# OPTIONAL gate: comment out during testing to avoid premium block
try:
    from app.entitlements import has_feature
    if "user_email" not in st.session_state:
        st.session_state["user_email"] = "test@example.com"
    email = st.session_state["user_email"]
    st.sidebar.caption(f"Signed in as: **{email}**")
    st.sidebar.write("Premium enabled?", has_feature(email, "premium_reports"))
    # Comment the next two lines if you want to test uploads without gating:
    # if not has_feature(email, "premium_reports"):
    #     st.info("Premium feature. Upgrade on **Billing** to unlock."); st.stop()
except Exception as e:
    st.sidebar.error(f"Entitlements import failed: {e}")

st.set_page_config(page_title="Upload Data", page_icon="📄")
st.title("Upload Data")
st.caption("Pick a CSV or Excel file. We’ll preview and save a copy.")

# --- Debug panel: shows environment & paths to confirm everything is wired ---
with st.expander("Debug (you can hide this later)", expanded=False):
    st.write({
        "cwd": str(pathlib.Path.cwd()),
        "ROOT": str(ROOT),
        "session_state_keys": list(st.session_state.keys()),
    })

# --- make sure upload dir exists
UPLOAD_DIR = ROOT / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
st.write(f"Upload folder: `{UPLOAD_DIR}`")

# --- the actual uploader
file = st.file_uploader("Choose a CSV or Excel file", type=["csv", "xlsx", "xls"])

def _safe_read(uploaded_file):
    """Read a CSV/Excel safely with helpful errors."""
    name = uploaded_file.name.lower()
    uploaded_file.seek(0)
    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file)
    elif name.endswith(".xlsx") or name.endswith(".xls"):
        # openpyxl is the default engine for .xlsx; make sure it's installed
        return pd.read_excel(uploaded_file)
    else:
        raise ValueError("Unsupported file type")

if file is not None:
    try:
        df = _safe_read(file)
        st.success(f"Loaded **{file.name}** → shape {df.shape[0]:,} rows × {df.shape[1]:,} cols")

        # Preview & metadata
        st.dataframe(df.head(50), use_container_width=True)
        st.write("Columns:", list(df.columns))
        st.write("Dtypes:", df.dtypes.astype(str).to_dict())

        # Save a copy with timestamp (and keep original name)
        file.seek(0)
        out = UPLOAD_DIR / f"{datetime.now():%Y%m%d_%H%M%S}__{file.name.replace(' ', '_')}"
        out.write_bytes(file.read())
        st.caption(f"Saved a copy to `{out}`")

        # Also write a tiny JSON sidecar with basic stats for quick checks
        sidecar = {
            "name": file.name,
            "saved_as": str(out),
            "rows": int(df.shape[0]),
            "cols": int(df.shape[1]),
            "columns": list(map(str, df.columns)),
        }
        (out.with_suffix(out.suffix + ".meta.json")).write_text(json.dumps(sidecar, indent=2))

    except Exception as e:
        st.error(f"Could not read file: {e}")
        st.exception(e)   # shows full traceback in the app for quick debugging
else:
    st.info("⬆️ Pick a file above to begin.")
