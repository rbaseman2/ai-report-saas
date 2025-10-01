import io
import matplotlib.pyplot as plt

def revenue_by_region_bar(by_region: dict) -> bytes | None:
    if not by_region:
        return None
    fig, ax = plt.subplots()
    regions = list(by_region.keys())
    vals = list(by_region.values())
    ax.bar(regions, vals)
    ax.set_title("Revenue by Region")
    ax.set_ylabel("Revenue")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160)
    plt.close(fig)
    buf.seek(0)
    return buf.read()
