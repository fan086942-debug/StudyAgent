import re

from app.schemas.document import TextBlock


def clean_text(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[^\S\n]+", " ", text)).strip()


def chunk_blocks(blocks: list[TextBlock], size: int, overlap: int) -> list[TextBlock]:
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("切块参数不合法")
    chunks = []
    for block in blocks:
        text = clean_text(block.text)
        start = 0
        while start < len(text):
            end = min(start + size, len(text))
            if end < len(text):
                # 优先在后半段的句末或换行处切，避免为凑边界生成过短片段。
                boundary = max(text.rfind(c, start + size // 2, end) for c in "\n。！？;；")
                if boundary >= 0:
                    end = boundary + 1
            fragment = text[start:end].strip()
            if fragment:
                chunks.append(block.model_copy(update={"text": fragment}))
            if end == len(text):
                break
            start = max(start + 1, end - overlap)
    return chunks
