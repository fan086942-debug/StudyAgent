import logging
import time

from app.schemas.chat import ChatResponse, SearchRequest
from app.services.answering import solve, valid_answer

logger = logging.getLogger("studyagent")
NO_EVIDENCE = "当前资料中未找到可靠来源。"


class QAService:
    def __init__(self, settings, retriever, llm, visuals=None):
        self.settings, self.retriever, self.llm = settings, retriever, llm
        self.visuals = visuals

    def answer(self, request: SearchRequest) -> ChatResponse:
        start = time.perf_counter()
        retrieval = self.retriever.search(request)
        sources = retrieval.sources
        answer, insufficient, warning, usage, llm_ms = NO_EVIDENCE, True, None, None, 0.0
        answer_basis = "unanswered"
        if sources and self.settings.study_mode == "demo":
            answer = "演示模式仅展示检索摘录，未调用 LLM，不能判断这些资料是否足以回答问题。\n\n"
            answer += "\n\n".join(f"[{s.citation_id}] {s.text}" for s in sources)
            warning = "当前使用字词哈希检索；切换 API 模式后才能生成语义问答。"
            # 演示摘录没有做证据充分性判断，不宣称问题已被回答。
            insufficient = True
        elif self.settings.study_mode != "demo":
            llm_start = time.perf_counter()
            # 将筛选后的正文与引用编号交给模型，真实文件位置由后端的 Source 提供。
            images, warning = self.visuals.prepare(request, sources, self.llm) if self.visuals else ([], None)
            result = solve(self.llm, request.question, sources, images=images)
            llm_ms = (time.perf_counter() - llm_start) * 1000
            usage = result.usage
            content = result.content
            # 检查声明引用、正文引用与检索来源是否一致；此校验不判断内容是否被证据支持。
            claimed = set(content.citation_ids)
            if content.insufficient_evidence:
                sources = []
                answer = content.answer
            elif not valid_answer(content, sources, allow_model=True):
                warning = "模型输出包含无效引用或自行生成的位置，已拒绝展示，请重试。"
                sources = []
            else:
                answer, insufficient = content.answer, False
                answer_basis = content.answer_basis
                sources = [source for source in sources if source.citation_id in claimed]
        logger.info(
            "qa mode=%s sources=%s insufficient=%s retrieval_ms=%.1f llm_ms=%.1f",
            self.settings.study_mode,
            [source.chunk_id for source in sources],
            insufficient,
            retrieval.retrieval_ms,
            llm_ms,
        )
        return ChatResponse(
            answer=answer,
            answer_basis=answer_basis,
            sources=sources,
            mode=self.settings.study_mode,
            insufficient_evidence=insufficient,
            warning=warning,
            retrieval_ms=retrieval.retrieval_ms,
            llm_ms=llm_ms,
            total_ms=(time.perf_counter() - start) * 1000,
            usage=usage,
        )
