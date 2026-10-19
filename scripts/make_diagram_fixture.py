"""An original directed-graph exam PDF for visual-input acceptance tests."""
import math
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


def make_diagram_pdf(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1050, 520), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 42)
    except OSError:
        font = ImageFont.load_default()
    nodes = {"P": (100, 260), "T": (370, 100), "Q": (660, 390), "R": (950, 240), "S": (350, 420)}
    for a, b in [("P", "T"), ("T", "Q"), ("Q", "R")]:
        x1, y1 = nodes[a]
        x2, y2 = nodes[b]
        length = math.hypot(x2 - x1, y2 - y1)
        ux, uy = (x2 - x1) / length, (y2 - y1) / length
        start = (x1 + 40 * ux, y1 + 40 * uy)
        end = (x2 - 40 * ux, y2 - 40 * uy)
        draw.line([start, end], fill="black", width=7)
        draw.polygon([end, (end[0] - 23 * ux + 11 * uy, end[1] - 23 * uy - 11 * ux),
                      (end[0] - 23 * ux - 11 * uy, end[1] - 23 * uy + 11 * ux)], fill="black")
    for name, (x, y) in nodes.items():
        draw.ellipse((x - 38, y - 38, x + 38, y + 38), fill="white", outline="black", width=4)
        box = draw.textbbox((0, 0), name, font=font)
        draw.text((x - (box[2] - box[0]) / 2, y - (box[3] - box[1]) / 2 - box[1]),
                  name, font=font, fill="black")
    stream = BytesIO()
    image.save(stream, "PNG")
    image.close()
    pdf = canvas.Canvas(str(path), pagesize=(612, 792))
    pdf.setFont("Helvetica", 12)
    pdf.drawString(30, 748, "1.1 Follow the directed arrows in the diagram.")
    pdf.drawString(30, 728, "What is the ONLY directed path from P to R? List the nodes in order.")
    pdf.drawImage(ImageReader(stream), 20, 365, width=572, height=283)
    pdf.setFont("Helvetica", 10)
    for index in range(8):
        pdf.drawString(30, 320 - index * 17, "Graph exercise. Read the arrowheads carefully; do not guess alphabetical order.")
    pdf.save()
    return path
