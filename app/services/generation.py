import re
import time
from threading import Lock

from sqlalchemy import select

from app.core.errors import AppError
from app.models import Document, StudyArtifact
from app.schemas.chat import SearchRequest
from app.schemas.generation import (
    ArtifactOut,
    ArtifactSummary,
    GeneratedContent,
    GenerationRequest,
    PracticeQuestion,
    ReviewSection,
)


class GenerationService:
    def __init__(self, settings, sessions, retriever, exams, provider):
        self.settings, self.sessions = settings, sessions
        self.retriever, self.exams, self.provider = retriever, exams, provider
        self.lock = Lock()

    def generate(self, request: GenerationRequest, avoid_stems=()) -> ArtifactOut:
        self.exams.validate_scope(request.course_id, request.document_ids)
        if request.kind == "mock_exam" and request.question_count < len(request.topics):
            raise AppError("invalid_blueprint", "题数不能少于主题数，每个主题至少一道题", 422)
        if (
            self.settings.study_mode == "demo"
            and request.kind == "mock_exam"
            and request.question_type != "short_answer"
        ):
            raise AppError(
                "demo_question_type", "演示模式仅支持摘录简答练习，其他题型请使用 API 模式", 422
            )
        if not self.lock.acquire(blocking=False):
            raise AppError("generation_busy", "已有内容正在生成，请稍后重试", 409)
        try:
            return self._generate(request, avoid_stems)
        finally:
            self.lock.release()

    def _evidence(self, request):
        # 先校验用户范围，再排除试卷；题干中的待求结论不能作为生成答案的依据。
        with self.sessions() as session:
            statement = select(Document.id).where(
                Document.course_id == request.course_id, Document.document_type != "exam"
            )
            if request.document_ids is not None:
                statement = statement.where(Document.id.in_(request.document_ids))
            ids = list(session.scalars(statement))
        if not ids:
            raise AppError(
                "generation_no_evidence", "请先上传或选择教材、课件、笔记等参考资料", 409
            )
        sources, by_chunk, topic_ids = [], {}, {}
        quota = self.settings.context_char_budget // len(request.topics)
        for topic in request.topics:
            found = self.retriever.search(
                SearchRequest(course_id=request.course_id, document_ids=ids, question=topic)
            ).sources
            remaining, accepted = quota, []
            for source in found[:8]:
                if source.chunk_id in by_chunk:
                    accepted.append(by_chunk[source.chunk_id].citation_id)
                    continue
                if remaining < 100:
                    break
                # 快照保存的原文必须与模型实际收到的文本完全一致。
                source = source.model_copy(
                    update={"citation_id": f"S{len(sources) + 1}", "text": source.text[:remaining]}
                )
                sources.append(source)
                by_chunk[source.chunk_id] = source
                accepted.append(source.citation_id)
                remaining -= len(source.text)
            if not accepted:
                raise AppError(
                    "generation_no_evidence",
                    f"主题「{topic}」没有检索到可用依据，请补充资料或缩小主题范围",
                    409,
                )
            topic_ids[topic] = accepted
        return sources, topic_ids

    def _generate(self, request, avoid_stems=()):
        start = time.perf_counter()
        sources, topic_ids = self._evidence(request)
        if self.settings.study_mode == "demo":
            content, usage = self._demo(request, sources, topic_ids, excluded=avoid_stems), {}
            warning = "演示模式：复习内容为原文摘录，练习题为摘录模板；未调用 LLM，难度未评估。"
        else:
            content, usage = self.provider.generate(
                request,
                {
                    "topics": topic_ids,
                    "sources": [{"id": s.citation_id, "text": s.text} for s in sources],
                    "avoid_stems": list(avoid_stems),
                },
            )
            warning = "模型生成的复习内容与参考答案需对照原文核查，题目难度为模型估计，非官方试卷。"
        try:
            self._validate(request, content, topic_ids)
            if any(
                re.sub(r"\s+", "", q.stem) in {re.sub(r"\s+", "", stem) for stem in avoid_stems}
                for q in content.questions
            ):
                raise AppError(
                    "generation_duplicate_questions",
                    "模型重复了当前对话中的题目，未保存，请重试。",
                    502,
                )
        except AppError as exc:
            exc.usage = usage
            raise
        # 所有生成和校验完成后才写一次事务，失败不会在历史中留下半份成品。
        with self.sessions() as session:
            row = StudyArtifact(
                course_id=request.course_id,
                kind=request.kind,
                title=content.title,
                mode=self.settings.study_mode,
                warning=warning,
                payload={
                    "request": request.model_dump(mode="json"),
                    "content": content.model_dump(mode="json"),
                    "sources": [s.model_dump(mode="json") for s in sources],
                    "usage": usage,
                    "total_ms": round((time.perf_counter() - start) * 1000, 1),
                },
            )
            session.add(row)
            session.commit()
            return self._out(row)

    @staticmethod
    def _validate(request, content, topic_ids, allowed_headings=()):
        if content.insufficient_evidence:
            raise AppError(
                "generation_no_evidence", "当前资料不足以生成符合要求的内容，请补充资料", 409
            )
        items = content.sections if request.kind == "review" else content.questions
        invalid = (
            (
                request.kind == "review"
                and (len(content.sections) != len(request.topics) or content.questions)
            )
            or (
                request.kind == "mock_exam"
                and (len(content.questions) != request.question_count or content.sections)
            )
            or {item.topic for item in items} != set(request.topics)
        )
        for item in items:
            if not set(item.citation_ids).issubset(topic_ids.get(item.topic, [])):
                invalid = True
            if isinstance(item, PracticeQuestion):
                if item.type != request.question_type or item.difficulty != request.difficulty:
                    invalid = True
            # 引用和位置由服务端渲染；禁止正文夹带另一套来源编号或编造页码。
            text = str(item.model_dump(exclude={"citation_ids", "topic"}))
            for heading in allowed_headings:
                text = text.replace(heading, "")
            if re.search(r"\[S\d+\]|第\s*[\d一二三四五六七八九十百]+\s*[页章]", text):
                invalid = True
        stems = [re.sub(r"\s+", "", q.stem) for q in content.questions]
        if len(set(stems)) != len(stems):
            invalid = True
        if invalid:
            raise AppError(
                "generation_invalid_content",
                "生成结果未通过主题、题数、题型或来源校验，未保存；请减少要求或重试",
                502,
            )

    @staticmethod
    def _demo(request, sources, topic_ids, excluded=()):
        lookup = {s.citation_id: s for s in sources}
        if request.kind == "review":
            selected = {
                topic: ids
                if len(ids) <= 8
                else [ids[round(i * (len(ids) - 1) / 7)] for i in range(8)]
                for topic, ids in topic_ids.items()
            }
            return GeneratedContent(
                title="复习资料 · 原文摘录",
                sections=[
                    ReviewSection(
                        topic=topic,
                        summary="以下为检索原文，请结合完整资料自行整理。",
                        key_points=[lookup[c].text for c in ids],
                        citation_ids=ids,
                    )
                    for topic, ids in selected.items()
                ],
            )
        # 离线模式不假装推理解题，只用不同原文片段构造可核对的摘录练习。
        pools = {}
        for topic, ids in topic_ids.items():
            pool, seen = [], set()
            for citation in ids:
                for text in re.split(r"(?<=[。！？；])|\n+", lookup[citation].text):
                    text = text.strip()
                    if len(text) >= 8 and text not in seen:
                        pool.append((text, citation))
                        seen.add(text)
            pools[topic] = pool
        questions, used = [], set(excluded)
        for index in range(request.question_count):
            topic = request.topics[index % len(request.topics)]
            candidate = next(
                (
                    p
                    for p in pools[topic]
                    if p[0] not in used
                    and f"阅读材料：{p[0]}\n请概括这段材料中与「{topic}」相关的要点。" not in used
                ),
                None,
            )
            if candidate is None:
                raise AppError(
                    "demo_insufficient_excerpts",
                    f"主题「{topic}」的不同原文摘录不足，请减少题数、补充资料或使用 API 模式",
                    409,
                )
            text, citation = candidate
            used.add(text)
            questions.append(
                PracticeQuestion(
                    topic=topic,
                    type="short_answer",
                    difficulty=request.difficulty,
                    stem=f"阅读材料：{text}\n请概括这段材料中与「{topic}」相关的要点。",
                    answer=text,
                    explanation="演示参考摘录：请对照原文检查概括是否保留关键条件，未使用模型评分。",
                    citation_ids=[citation],
                )
            )
        return GeneratedContent(title="模拟练习 · 摘录简答", questions=questions)

    @staticmethod
    def _summary(row):
        return ArtifactSummary(
            id=row.id,
            course_id=row.course_id,
            kind=row.kind,
            title=row.title,
            mode=row.mode,
            created_at=row.created_at,
            warning=row.warning,
        )

    @classmethod
    def _out(cls, row):
        return ArtifactOut(**cls._summary(row).model_dump(), **row.payload)

    def list(self, course_id, limit=30, offset=0):
        self.exams.validate_scope(course_id, None)
        with self.sessions() as session:
            rows = session.scalars(
                select(StudyArtifact)
                .where(StudyArtifact.course_id == course_id)
                .order_by(StudyArtifact.created_at.desc(), StudyArtifact.id)
                .limit(limit)
                .offset(offset)
            )
            return [self._summary(row) for row in rows]

    def get(self, course_id, artifact_id):
        self.exams.validate_scope(course_id, None)
        with self.sessions() as session:
            row = session.scalar(
                select(StudyArtifact).where(
                    StudyArtifact.id == artifact_id, StudyArtifact.course_id == course_id
                )
            )
            if row is None:
                raise AppError("artifact_not_found", "当前课程中未找到该生成记录", 404)
            return self._out(row)


def artifact_markdown(artifact, include_answers=True):
    """导出存储快照，不重新调用模型；无答案卷不附原文，避免通过来源泄露答案。"""
    content = artifact.content
    lines = [
        f"# {content.title}",
        "",
        artifact.warning,
        "",
        f"生成时间：{artifact.created_at}",
        "",
    ]
    for section in content.sections if include_answers or not content.questions else []:
        lines += [f"## {section.topic}", "", section.summary, ""]
        lines += [f"- {p}" for p in section.key_points]
        if section.pitfalls:
            lines += ["", "易错点："] + [f"- {p}" for p in section.pitfalls]
        lines += ["", "依据：" + " ".join(f"[{c}]" for c in section.citation_ids), ""]
    types = {"choice": "选择题", "short_answer": "简答题", "calculation": "计算题"}
    for i, question in enumerate(content.questions, 1):
        lines += [f"## {i}. {question.topic} · {types[question.type]}", "", question.stem, ""]
        lines += [f"{letter}. {option}" for letter, option in zip("ABCD", question.options)]
        lines += [""]
    if content.questions and include_answers:
        lines += ["## 参考答案与解析", ""]
        for i, question in enumerate(content.questions, 1):
            lines += [
                f"### 第 {i} 题",
                "",
                question.answer,
                "",
                question.explanation,
                "",
                "依据：" + " ".join(f"[{c}]" for c in question.citation_ids),
                "",
            ]
    if include_answers or not content.questions:
        lines += ["## 来源原文快照", ""]
        for source in artifact.sources:
            location = (
                f"PDF 物理第 {source.page} 页"
                if source.location_type == "pdf_page"
                else f"第 {source.page} 张幻灯片"
                if source.location_type == "slide"
                else f"第 {source.block_index} 个段落 / 表格块"
            )
            lines += [
                f"### [{source.citation_id}] {source.document_name} · {location}",
                "",
                source.text,
                "",
            ]
    return "\n".join(lines)
