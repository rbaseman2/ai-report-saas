import pandas as pd

def compute_kpis(df: pd.DataFrame):
    out = {}
    if "Revenue" in df.columns:
        out["total_revenue"] = float(df["Revenue"].sum())
    if "Region" in df.columns and "Revenue" in df.columns:
        by_region = df.groupby("Region")["Revenue"].sum().sort_values(ascending=False).to_dict()
        out["by_region"] = {k: float(v) for k, v in by_region.items()}
    if "Date" in df.columns and "Revenue" in df.columns:
        df = df.copy()
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        if df["Date"].notna().any():
            maxd = df["Date"].max()
            recent = df[df["Date"] >= (maxd - pd.Timedelta(days=30))]["Revenue"].sum()
            prior = df[(df["Date"] < (maxd - pd.Timedelta(days=30))) &
                       (df["Date"] >= (maxd - pd.Timedelta(days=60)))]["Revenue"].sum()
            out["trend_30d"] = {"recent": float(recent), "prior": float(prior)}
    return out
