import pytest
from pypdf import PdfWriter

from app.core.errors import AppError
from app.rag.parsers import parse_document
from scripts.make_fixtures import generate


def test_three_formats_and_locations(tmp_path):
    pdf_path, ppt_path, docx_path = generate(tmp_path)
    pdf, ppt, docx = [parse_document(path) for path in (pdf_path, ppt_path, docx_path)]
    assert len(pdf.blocks) == 4
    assert "A*" in pdf.blocks[0].text
    assert pdf.blocks[0].page == 1
    assert "第1章" in pdf.blocks[0].chapter
    assert len(ppt.blocks) == 3
    assert "备注：" in ppt.blocks[0].text
    assert ppt.blocks[2].page == 3
    assert all(block.page is None for block in docx.blocks)
    assert docx.blocks[-1].location_type == "table"
    assert "队列" in docx.blocks[-1].text
    assert docx.blocks[1].section == "重点一：搜索"


def test_bad_and_empty_files(tmp_path):
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"not a document")
    with pytest.raises(AppError, match="解析失败"):
        parse_document(bad)
    blank = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(blank)
    with pytest.raises(AppError, match="OCR"):
        parse_document(blank)
    with pytest.raises(AppError, match="仅支持"):
        parse_document(tmp_path / "old.ppt")
