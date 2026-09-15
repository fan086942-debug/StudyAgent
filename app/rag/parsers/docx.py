from pathlib import Path

from docx import Document
from docx.table import Table

from app.schemas.document import ParsedDocument, TextBlock


def table_text(table: Table) -> str:
    rows = []
    for row in table.rows:
        cells, seen = [], set()
        for cell in row.cells:
            if cell._tc in seen:
                continue
            seen.add(cell._tc)
            parts = []
            for item in cell.iter_inner_content():
                parts.append(table_text(item) if isinstance(item, Table) else item.text)
            cells.append("\n".join(parts))
        rows.append(" | ".join(cells))
    return "\n".join(rows)


def parse_docx(path: Path) -> ParsedDocument:
    document = Document(path)
    blocks, headings = [], {}
    # 段落和表格按原始顺序遍历，不能先提取所有段落再追加所有表格。
    for number, item in enumerate(document.iter_inner_content(), 1):
        if isinstance(item, Table):
            text, kind = table_text(item), "table"
        else:
            text, kind = item.text, "paragraph"
            style = item.style.name if item.style else ""
            if style.startswith("Heading ") and style.split()[-1].isdigit():
                level = int(style.split()[-1])
                headings = {k: v for k, v in headings.items() if k < level}
                headings[level] = text
        blocks.append(
            TextBlock(
                text=text,
                chapter=headings.get(1),
                section=" / ".join(headings.values()) or None,
                block_index=number,
                location_type=kind,
            )
        )
    return ParsedDocument(blocks=blocks)
