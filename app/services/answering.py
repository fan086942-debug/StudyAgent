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


def solve(llm, question, sources, *, images=None):
    provider = getattr(llm, "solve", llm.generate)
    evidence = [{"id": source.citation_id, "text": source.text} for source in sources]
    result = provider(question, evidence, images=images) if images else provider(question, evidence)
    if result.content.insufficient_evidence:
        result.content = result.content.model_copy(update={"answer_basis": "unanswered"})
    elif not result.content.citation_ids and not re.search(r"\[S\d+\]", result.content.answer):
        result.content = result.content.model_copy(update={"answer_basis": "model"})
    elif result.content.answer_basis in {"materials", "mixed"}:
        # Some providers declare valid sources but omit their inline markers.
        # Repair only that formatting omission, never unknown or conflicting IDs.
        declared = set(result.content.citation_ids)
        available = {source.citation_id for source in sources}
        inline = set(re.findall(r"\[(S\d+)\]", result.content.answer))
        if declared and declared.issubset(available) and inline.issubset(declared):
            missing = list(dict.fromkeys(
                ref for ref in result.content.citation_ids if ref not in inline
            ))
            if missing:
                result.content = result.content.model_copy(update={
                    "answer": result.content.answer + "\n\n资料依据：" + " ".join(
                        f"[{ref}]" for ref in missing
                    ),
                })
    return result
