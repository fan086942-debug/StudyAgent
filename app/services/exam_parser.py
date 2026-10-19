import re
import unicodedata
from dataclasses import dataclass

from app.core.errors import AppError
from app.rag.chunker import clean_text
from app.schemas.document import TextBlock
from app.schemas.exam import ExtractedQuestion

NUMBER = re.compile(
    r"^[ \t]*(?:第\s*(\d{1,3}(?:[.．]\d{1,3}){0,3})\s*题\s*[:：、.]?"
    r"|(?:题\s*)?(\d{1,3})[.．、)）](?!\d)"
    r"|(\d{1,3}(?:[.．]\d{1,3}){1,3})(?:[.．、)）](?!\d)|(?=\s)))\s*"
)
SECTION = re.compile(r"^[一二三四五六七八九十]+[、.．]\s*")
CHAPTER = re.compile(r"^第\s*[一二三四五六七八九十百\d]+\s*[章节](?:\s|$)")
PAGE_HEADER = re.compile(r"^\s*第\s*\d+\s*页\s*共\s*\d+\s*页\s*$")
TYPES = {
    "选择": "choice",
    "判断": "true_false",
    "填空": "fill_blank",
    "简答": "short_answer",
    "计算": "calculation",
    "综合": "essay",
    "论述": "essay",
}


@dataclass
class ExamText:
    text: str
    # 每个原始块对应 [start, end)，跨页题目可以据此保留多个真实位置。
    spans: list[tuple[int, int, TextBlock]]

    def locations(self, start: int, end: int) -> list[dict]:
        return [
            block.model_dump(exclude={"text"})
            for a, b, block in self.spans
            if a < end and b > start
        ]


def build_exam_text(blocks: list[TextBlock]) -> ExamText:
    text, spans = "", []
    for block in blocks:
        cleaned = clean_text(block.text)
        if block.location_type == "pdf_page":
            # Remove only a recognizable page counter at a page margin, not question text.
            lines = cleaned.splitlines()
            if lines and PAGE_HEADER.fullmatch(lines[0]):
                lines.pop(0)
            if lines and PAGE_HEADER.fullmatch(lines[-1]):
                lines.pop()
            cleaned = "\n".join(lines)
        start = len(text)
        text += cleaned + "\n"
        spans.append((start, start + len(cleaned), block))
    return ExamText(text, spans)


def question_type(text: str, fallback: str = "unknown") -> str:
    return next((value for key, value in TYPES.items() if key in text), fallback)


def rule_extract(text: str) -> list[ExtractedQuestion]:
    """离线基线：根据题号切题，保留跨行选项；不推测答案和难度。"""
    result, lines, number, kind = [], [], None, "unknown"

    def finish():
        if number is None or not lines:
            return
        content = "\n".join(lines).strip()
        options = re.findall(r"(?:^|\n|\s)([A-H][.．、)）].*?)(?=\s+[A-H][.．、)）]|\n|$)", content)
        score = re.search(r"[（(]\s*(\d+(?:\.\d+)?)\s*分\s*[）)]", content)
        # 明示标签可离线提取；一般课程知识点在 API 模式中由模型标注。
        tag = re.search(r"【知识点[：:](.*?)】", content)
        points = re.split(r"[,，、;；]", tag[1]) if tag else []
        result.append(
            ExtractedQuestion(
                number=number,
                type="choice" if options else kind,
                source_text=content,
                options=options,
                score=float(score[1]) if score else None,
                knowledge_points=[p.strip() for p in points if p.strip()],
            )
        )

    for line in text.splitlines():
        if (SECTION.match(line) or CHAPTER.match(line) or line.strip() == "习题"
                or re.match(r"^(参考答案|答案与解析)\s*[:：]?$", line)):
            finish()
            lines, number = [], None
            kind = question_type(line)
            if line.startswith(("参考答案", "答案与解析")):
                break
            continue
        match = NUMBER.match(line)
        if match:
            finish()
            number, lines = next(group for group in match.groups() if group), [line]
        elif number is not None:
            lines.append(line)
    finish()
    return result


def quote_char(char: str) -> str:
    # Width differences and invisible PDF layout characters are not semantic edits.
    # Keep operators, digits, superscripts and punctuation otherwise distinct.
    if char.isspace() or char in "\u00ad\u200b\ufeff":
        return ""
    if "\uff01" <= char <= "\uff5e":
        return chr(ord(char) - 0xfee0)
    return char


def locate_quote(text: str, quote: str, start: int = 0) -> tuple[int, int]:
    # Exact matching after narrowly defined layout normalization; never fuzzy matching.
    chars, positions = [], []
    for index, char in enumerate(text):
        normalized = quote_char(char)
        if normalized:
            chars.append(normalized)
            positions.append(index)
    needle = "".join(quote_char(char) for char in quote)
    offset = next((i for i, pos in enumerate(positions) if pos >= start), len(positions))
    match = "".join(chars).find(needle, offset)
    if not needle or match < 0:
        raise AppError("exam_unverified_text", "模型提取的题目无法匹配原文，请重试或检查文件", 502)
    return positions[match], positions[match + len(needle) - 1] + 1


def verify_number(number: str, text: str) -> None:
    # 题干中可能有年份、分值等数字，不能仅凭“数字出现在原文里”就认定它是题号。
    number = unicodedata.normalize("NFKC", number).strip()
    text = unicodedata.normalize("NFKC", text).lstrip()
    detected = NUMBER.match(text)
    if detected and next(group for group in detected.groups() if group) != number:
        raise AppError("exam_invalid_number", "模型题号与原文开头不一致，请重试", 502)
    pattern = r"^(?:第\s*|题\s*|Question\s*|Q\s*|[\[(【])?" + re.escape(number)
    pattern += r"(?:\s*(?:题|[.、:)\]】])|\s+)"
    if not re.match(pattern, text, re.IGNORECASE):
        raise AppError("exam_invalid_number", "模型题号与原文开头不一致，请重试", 502)


def extraction_windows(text: str, size: int) -> list[tuple[int, str]]:
    # 优先在下一题开始处结束一个窗口，让完整题目进入同一次模型调用。
    starts = [m.start() for m in re.finditer(NUMBER.pattern, text, re.MULTILINE)]
    windows, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        candidates = [point for point in starts if start + size // 2 < point <= end]
        if end < len(text) and candidates:
            end = candidates[-1]
            next_start = end
        else:
            next_start = max(start + 1, end - min(2000, size // 4))
        windows.append((start, text[start:end]))
        if end == len(text):
            break
        start = next_start
    return windows
