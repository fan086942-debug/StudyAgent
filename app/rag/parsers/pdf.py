import re
from pathlib import Path

from pypdf import PdfReader

from app.core.errors import AppError
from app.schemas.document import ParsedDocument, TextBlock


def parse_pdf(path: Path) -> ParsedDocument:
    reader = PdfReader(path)
    if reader.is_encrypted:
        raise AppError("encrypted_pdf", "PDF 已加密，请先提供解除密码保护的副本")
    if len(reader.pages) > 1000:
        raise AppError("too_many_pages", "单个 PDF 最多 1000 页，请拆分上传")
    blocks, empty_pages = [], []
    chapter = None
    for page_number, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        if not text.strip():
            empty_pages.append(page_number)
            continue
        for line in text.splitlines()[:5]:
            if re.match(r"^\s*第[一二三四五六七八九十百\d]+章", line):
                chapter = line.strip()[:200]
                break
        blocks.append(
            TextBlock(
                text=text,
                page=page_number,
                chapter=chapter,
                block_index=page_number,
                location_type="pdf_page",
            )
        )
    warnings = []
    if empty_pages:
        warnings.append(f"{len(empty_pages)} 页未提取到文字，可能是空白页或扫描页；未执行 OCR")
    return ParsedDocument(blocks=blocks, warnings=warnings)
