from pathlib import Path
from zipfile import ZipFile

from app.core.errors import AppError
from app.rag.parsers.docx import parse_docx
from app.rag.parsers.pdf import parse_pdf
from app.rag.parsers.pptx import parse_pptx
from app.schemas.document import ParsedDocument


def parse_document(path: Path) -> ParsedDocument:
    parsers = {".pdf": parse_pdf, ".pptx": parse_pptx, ".docx": parse_docx}
    parser = parsers.get(path.suffix.lower())
    if parser is None:
        raise AppError("unsupported_type", "仅支持文本 PDF、PPTX、DOCX；旧格式请先转换")
    try:
        if path.suffix.lower() != ".pdf":
            # OOXML 是 ZIP 容器，先限制解压量，避免小文件包含异常大数据。
            with ZipFile(path) as archive:
                if sum(item.file_size for item in archive.infolist()) > 200 * 1024 * 1024:
                    raise AppError("document_too_large", "文档解压后超过 200MB，请拆分上传")
        result = parser(path)
        result.blocks = [block for block in result.blocks if block.text.strip()]
        if not result.blocks:
            raise AppError("no_text", "没有可提取文本；扫描 PDF 或图片资料需要 OCR")
        if sum(len(block.text) for block in result.blocks) > 2_000_000:
            raise AppError("document_too_large", "提取文字超过 200 万字符，请拆分资料")
        return result
    except AppError:
        raise
    except Exception as exc:
        raise AppError("parse_failed", "文件解析失败，请检查文件是否损坏、加密或格式不符") from exc
