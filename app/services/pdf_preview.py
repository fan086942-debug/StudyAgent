"""Bounded PDF page previews shared with the model's PDF rendering path."""

import hashlib
from io import BytesIO

from app.rag.parsers.ocr import pdfium_lock


def delete_preview_cache(data_dir, document_id):
    cache = (data_dir / "preview-cache").resolve()
    prefix = hashlib.sha256(document_id.encode()).hexdigest()
    for path in cache.glob(f"{prefix}-*.jpg"):
        path.unlink(missing_ok=True)


def render_pdf_page(path, number, *, width=None, max_edge=2400):
    # Imported on first use: PDFium's native bindings are a measurable part of
    # cold process start, but only page previews and OCR need them.
    import pypdfium2 as pdfium

    with pdfium_lock:
        reader = pdfium.PdfDocument(path)
        try:
            count = len(reader)
            if not 1 <= number <= count:
                raise IndexError("page outside document")
            page = reader[number - 1]
            try:
                page_width, page_height = page.get_size()
                scale = min(2.5, max_edge / max(page_width, page_height))
                if width is not None:
                    scale = min(scale, width / page_width)
                bitmap = page.render(scale=scale)
                try:
                    picture = bitmap.to_pil().convert("RGB")
                    try:
                        stream = BytesIO()
                        picture.save(stream, format="JPEG", quality=90)
                        return stream.getvalue(), count
                    finally:
                        picture.close()
                finally:
                    bitmap.close()
            finally:
                page.close()
        finally:
            reader.close()
