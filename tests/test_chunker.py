from app.rag.chunker import chunk_blocks, clean_text
from app.schemas.document import TextBlock


def test_chunk_boundaries_and_overlap():
    text = "".join(chr(0x4E00 + i) for i in range(500))
    source = TextBlock(text=text, page=7, location_type="pdf_page")
    chunks = chunk_blocks([source], size=100, overlap=20)
    assert len(chunks) == 6
    assert chunks[0].text[-20:] == chunks[1].text[:20]
    assert all(len(chunk.text) <= 100 and chunk.page == 7 for chunk in chunks)
    recovered = chunks[0].text + "".join(chunk.text[20:] for chunk in chunks[1:])
    assert recovered == text


def test_empty_short_and_page_isolation():
    blocks = [
        TextBlock(text="", page=1, location_type="pdf_page"),
        TextBlock(text="A* 算法", page=2, location_type="pdf_page"),
        TextBlock(text="BFS 队列", page=3, location_type="pdf_page"),
    ]
    chunks = chunk_blocks(blocks, 100, 20)
    assert len(chunks) == 2
    assert [chunk.page for chunk in chunks] == [2, 3]


def test_repeated_watermark_is_reduced_without_removing_body_or_formulas():
    text = "正文与原始公式 A+A。\n" + "课程平台水印\n" * 40 + "后续正文\n重复要点\n重复要点"
    cleaned = clean_text(text)
    assert cleaned.count("课程平台水印") == 1
    assert "正文与原始公式 A+A。" in cleaned and "后续正文" in cleaned
    assert cleaned.count("重复要点") == 2
