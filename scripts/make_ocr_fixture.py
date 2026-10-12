"""Synthetic OCR fixture; never reads or uploads the user's textbook."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas


def make_scan(path: Path, mixed: bool = False, copies: int = 1):
    path.parent.mkdir(parents=True, exist_ok=True)
    chinese_font = Path("C:/Windows/Fonts/msyh.ttc")
    font = ImageFont.truetype(str(chinese_font) if chinese_font.exists() else "DejaVuSans.ttf", 36)
    image = Image.new("RGB", (1100, 650), "white")
    draw = ImageDraw.Draw(image)
    lines = [
        "Machine Learning",
        "Supervised learning uses labeled data.",
        "Models learn patterns from training examples.",
    ]
    if chinese_font.exists():
        lines.insert(0, "机器学习：监督学习与训练数据")
    for index, line in enumerate(lines):
        draw.text((65, 70 + 100 * index), line, fill="black", font=font)
    canvas = Canvas(str(path), pagesize=(550, 400))
    if mixed:
        canvas.setFont("Helvetica", 16)
        canvas.drawString(30, 340, "Native text must stay on physical page 1.")
        canvas.showPage()
        canvas.setFont("Helvetica", 10)
        canvas.drawString(30, 385, "Page 2")
    for _ in range(copies):
        canvas.drawImage(ImageReader(image), 0, 30, width=550, height=325)
        canvas.showPage()
    if mixed:
        canvas.showPage()  # A blank page should not become invented OCR text.
    canvas.save()
    return path


if __name__ == "__main__":
    make_scan(Path("data/ocr-test-fixtures/scanned-learning.pdf"), copies=8)
