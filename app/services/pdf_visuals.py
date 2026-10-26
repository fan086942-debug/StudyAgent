"""Render only relevant PDF pages for model input, with bounded memory and scope."""

import base64
import logging
import re

from sqlalchemy import select

from app.models import Document
from app.services.pdf_preview import render_pdf_page

logger = logging.getLogger("studyagent")


class PDFVisuals:
    def __init__(self, settings, sessions):
        self.settings, self.sessions = settings, sessions

    def prepare(self, request, sources, llm):
        if self.settings.pdf_visual_mode == "disabled":
            return [], None
        candidates = list(dict.fromkeys(
            (source.document_id, source.page)
            for source in sources
            if source.file_type == "pdf" and source.page
        ))
        explicit_pages = [int(p) for p in re.findall(r"第\s*(\d+)\s*页", request.question)]
        with self.sessions() as session:
            query = select(Document).where(
                Document.course_id == request.course_id,
                Document.file_type == "pdf",
                Document.status == "ready",
            )
            if request.document_ids is not None:
                query = query.where(Document.id.in_(request.document_ids))
            documents = {
                doc.id: (doc.storage_path, doc.name, doc.document_type)
                for doc in session.scalars(query)
            }
        if not candidates and len(documents) == 1 and explicit_pages:
            candidates = [(next(iter(documents)), page) for page in explicit_pages]
        candidates = [item for item in candidates if item[0] in documents]
        if not candidates:
            return [], None
        if not getattr(llm, "supports_images", False):
            return [], "当前模型未启用 PDF 原图输入，本次仅使用提取文字；图表题需支持图像的模型。"
        content, warnings = [], []
        limit = self.settings.pdf_visual_max_pages
        for document_id, number in candidates[:limit]:
            path, name, document_type = documents[document_id]
            try:
                picture, _ = render_pdf_page(
                    path, number, max_edge=self.settings.pdf_visual_max_edge,
                )
                encoded = base64.b64encode(picture).decode("ascii")
                references = [source.citation_id for source in sources if (
                    source.document_id == document_id and source.page == number
                    and source.document_type != "exam"
                )]
                role = (
                    "题目原图，不是教材答案依据。"
                    if document_type == "exam" or not references else
                    "参考资料原图，对应 evidence 编号 " + ", ".join(references)
                    + "；只引用图中实际支持的事实。"
                )
                content.extend([
                    {"type": "text", "text": f"以下为 {name} 的 PDF 物理第 {number} 页原图，仅解答本次指定题目。{role}"},
                    {"type": "image_url", "image_url": {
                        "url": "data:image/jpeg;base64," + encoded, "detail": "high",
                    }},
                ])
            except Exception as exc:
                logger.warning("pdf_visual_failed document=%s page=%s error_type=%s",
                               document_id, number, type(exc).__name__)
                warnings.append(f"PDF 第 {number} 页原图读取失败；涉及图表的条件请核对原页。")
        if len(candidates) > limit:
            warnings.append(f"本次最多核对 {limit} 页原图，其余片段仅使用文字；跨页图表请缩小页码范围。")
        return content, " ".join(warnings) or None
