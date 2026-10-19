"""Validate sourced answers and explicitly labelled model reasoning separately."""

import re

from app.schemas.chat import Source


def valid_answer(answer, sources: list[Source], *, allow_model=False) -> bool:
    if answer.insufficient_evidence or not answer.answer.strip():
        return False
    if re.search(r"第\s*(?:\d+(?:\.\d+)*|[一二三四五六七八九十百]+)\s*[页章]", answer.answer):
        return False
    claimed = set(answer.citation_ids)
    inline = set(re.findall(r"\[(S\d+)\]", answer.answer))
    if answer.answer_basis == "model":
        return allow_model and not claimed and not inline
    if answer.answer_basis not in {"materials", "mixed"}:
        return False
    available = {source.citation_id for source in sources}
    return bool(claimed and claimed == inline and claimed.issubset(available))


def solve(llm, question, sources):
    provider = getattr(llm, "solve", llm.generate)
    result = provider(question, [{"id": source.citation_id, "text": source.text} for source in sources])
    if result.content.insufficient_evidence:
        result.content = result.content.model_copy(update={"answer_basis": "unanswered"})
    elif not sources and not result.content.citation_ids:
        result.content = result.content.model_copy(update={"answer_basis": "model"})
    return result
