import json
from pathlib import Path
from typing import Dict, Any

ENTITLEMENTS_PATH = Path("data/entitlements.json")

def load_entitlements() -> Dict[str, Any]:
    if not ENTITLEMENTS_PATH.exists():
        return {"customers": {}}
    with ENTITLEMENTS_PATH.open() as f:
        return json.load(f)

def get_plan_for_email(email: str) -> str | None:
    ents = load_entitlements()
    for _, rec in ents.get("customers", {}).items():
        if rec.get("email", "").lower() == email.lower():
            return rec.get("plan")
    return None

def has_feature(email: str, feature: str) -> bool:
    ents = load_entitlements()
    for _, rec in ents.get("customers", {}).items():
        if rec.get("email", "").lower() == email.lower():
            return feature in (rec.get("features") or [])
    return False
