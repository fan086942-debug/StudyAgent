import logging
import re
import time

from app.schemas.chat import ChatResponse, SearchRequest

logger = logging.getLogger("studyagent")
NO_EVIDENCE = "当前资料中未找到可靠来源。"


class QAService:
    def __init__(self, settings, retriever, llm):
        self.settings, self.retriever, self.llm = settings, retriever, llm

    def answer(self, request: SearchRequest) -> ChatResponse:
        start = time.perf_counter()
        retrieval = self.retriever.search(request)
        sources = retrieval.sources
        answer, insufficient, warning, usage, llm_ms = NO_EVIDENCE, True, None, None, 0.0
        if sources and self.settings.study_mode == "demo":
            answer = "演示模式仅展示检索摘录，未调用 LLM，不能判断这些资料是否足以回答问题。\n\n"
            answer += "\n\n".join(f"[{s.citation_id}] {s.text}" for s in sources)
            warning = "当前使用字词哈希检索；切换 API 模式后才能生成语义问答。"
            # 演示摘录没有做证据充分性判断，不宣称问题已被回答。
            insufficient = True
        elif sources:
            llm_start = time.perf_counter()
            result = self.llm.generate(
                request.question,
                [{"id": source.citation_id, "text": source.text} for source in sources],
            )
            llm_ms = (time.perf_counter() - llm_start) * 1000
            usage = result.usage
            content = result.content
            available = {source.citation_id for source in sources}
            claimed = set(content.citation_ids)
            inline = set(re.findall(r"\[(S\d+)\]", content.answer))
            bad_location = re.search(r"第\s*[\d一二三四五六七八九十百]+\s*[页章]", content.answer)
            if content.insufficient_evidence:
                sources = []
            elif (
                not claimed
                or not content.answer.strip()
                or not claimed.issubset(available)
                or not inline.issubset(claimed)
                or bad_location
            ):
                warning = "模型输出包含无效引用或自行生成的位置，已拒绝展示，请重试。"
                sources = []
            else:
                answer, insufficient = content.answer, False
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
            sources=sources,
            mode=self.settings.study_mode,
            insufficient_evidence=insufficient,
            warning=warning,
            retrieval_ms=retrieval.retrieval_ms,
            llm_ms=llm_ms,
            total_ms=(time.perf_counter() - start) * 1000,
            usage=usage,
        )
