import io
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

def export_pdf(path, title, exec_summary, kpi_dict, chart_png_bytes=None, brand_color="#38bdf8", logo_path=None):
    c = canvas.Canvas(path, pagesize=LETTER)
    width, height = LETTER

    # Logo (supports file-like obj)
    y = height - 50
    if logo_path:
        try:
            img = ImageReader(logo_path)
            c.drawImage(img, 40, y-24, width=140, height=24, mask='auto')
        except Exception:
            pass

    # Title
    c.setFont("Helvetica-Bold", 16)
    c.setFillColorRGB(0.22, 0.74, 0.97)
    c.drawString(40, y-60, title)

    # Exec Summary
    c.setFont("Helvetica", 10)
    c.setFillColorRGB(0, 0, 0)
    text = c.beginText(40, y-90)
    for line in (exec_summary or "").split("\n"):
        text.textLine(line)
    c.drawText(text)

    # KPIs
    text = c.beginText(40, y-220)
    text.textLine("KPIs")
    for k, v in (kpi_dict or {}).items():
        text.textLine(f"• {k}: {v}")
    c.drawText(text)

    # Chart
    if chart_png_bytes:
        try:
            img = ImageReader(io.BytesIO(chart_png_bytes))
            c.drawImage(img, 40, 140, width=520, height=220, preserveAspectRatio=True, mask='auto')
        except Exception:
            pass

    c.showPage()
    c.save()
