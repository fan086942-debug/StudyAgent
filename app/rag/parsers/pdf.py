from pathlib import Path

import pypdfium2 as pdfium

from app.core.errors import AppError
from app.rag.parsers.headings import heading_level
from app.rag.parsers.ocr import PageOCR, pdfium_lock
from app.schemas.document import ParsedDocument, TextBlock


def parse_pdf(
    path: Path,
    *,
    ocr_enabled=True,
    ocr_dpi=180,
    cache_dir=None,
    digest=None,
    progress=None,
    cancel=None,
) -> ParsedDocument:
    blocks, empty_pages, ocr_pages = [], [], []
    chapter, total_chars = None, 0
    ocr = None
    with pdfium_lock:
        try:
            reader = pdfium.PdfDocument(path)
        except pdfium.PdfiumError as exc:
            if exc.err_code == pdfium.raw.FPDF_ERR_PASSWORD:
                raise AppError("encrypted_pdf", "PDF 已加密，请先提供解除密码保护的副本") from exc
            raise
        try:
            total = len(reader)
            if total > 1000:
                raise AppError("too_many_pages", "单个 PDF 最多 1000 页，请拆分上传")
            for index in range(total):
                if cancel:
                    cancel()
                number = index + 1
                page = reader[index]
                try:
                    textpage = page.get_textpage()
                    try:
                        text = textpage.get_text_bounded() or ""
                    finally:
                        textpage.close()
                    images = bool(list(page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE])))
                    needs_ocr = images and len(text.strip()) < 300
                    if needs_ocr and ocr_enabled:
                        if progress:
                            progress(number, total, "ocr")
                        if ocr is None:
                            ocr = PageOCR(path, ocr_dpi, cache_dir, digest)
                        recognized = ocr.read(page, number)
                        if cancel:
                            cancel()
                        if len(recognized.strip()) > len(text.strip()):
                            text = recognized
                            ocr_pages.append(number)
                    elif progress:
                        progress(number, total, "text")
                    if not text.strip():
                        empty_pages.append(number)
                        continue
                    total_chars += len(text)
                    if total_chars > 2_000_000:
                        raise AppError("document_too_large", "提取文字超过 200 万字符，请拆分资料")
                    for line in text.splitlines()[:5]:
                        if heading_level(line) == 1:
                            chapter = line.strip()[:200]
                            break
                    blocks.append(
                        TextBlock(
                            text=text,
                            page=number,
                            chapter=chapter,
                            block_index=number,
                            location_type="pdf_page",
                        )
                    )
                finally:
                    page.close()
        finally:
            reader.close()
    warnings = []
    if ocr_pages:
        warnings.append(
            f"已对 {len(ocr_pages)} 页执行本地 OCR；公式、表格与低清文字可能存在识别误差，请对照原页核查"
        )
    if empty_pages:
        suffix = "已跳过，可能为空白或图片中无可识别文字" if ocr_enabled else "OCR 已关闭"
        warnings.append(f"{len(empty_pages)} 页未提取到文字；{suffix}")
    return ParsedDocument(blocks=blocks, warnings=warnings)
