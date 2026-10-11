import re

from app.schemas.document import TextBlock


def clean_text(text: str) -> str:
    # 清除解析噪声并统一空白，同时保留换行，供后续选择切分边界。
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[^\S\n]+", " ", text)).strip()


def chunk_blocks(blocks: list[TextBlock], size: int, overlap: int) -> list[TextBlock]:
    """按字符数切分每个原始文本块；size 和 overlap 的单位均为字符，而非 token。"""
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("切块参数不合法")
    chunks = []
    # 不跨原始块拼接，避免把不同页或位置的内容混在一起，影响引用定位。
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
                # 只替换文本，保留解析阶段记录的页码、章节、块序号等来源信息。
                chunks.append(block.model_copy(update={"text": fragment}))
            if end == len(text):
                break
            # 相邻片段保留重叠上下文，减少边界处的信息割裂；至少前进一字符以防死循环。
            start = max(start + 1, end - overlap)
    return chunks
