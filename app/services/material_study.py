import re
import time
from collections import Counter, OrderedDict
from math import ceil

from sqlalchemy import select

from app.core.errors import AppError
from app.models import Document, DocumentChunk, StudyArtifact
from app.rag.sources import chunk_source
from app.schemas.generation import GeneratedContent, ReviewSection, StudyGenerationTask
from app.services.study_checkpoint import StudyCheckpoint


def normalize(text):
    return re.sub(r"[\s_，。.,：:、·-]+", "", text).casefold()


def ready_materials(service, request):
    service.exams.validate_scope(request.course_id, request.document_ids)
    with service.sessions() as session:
        docs = list(
            session.scalars(select(Document).where(Document.course_id == request.course_id))
        )
        if request.document_ids is not None:
            docs = [doc for doc in docs if doc.id in request.document_ids]
        if request.document_name:
            docs = [doc for doc in docs if normalize(request.document_name) in normalize(doc.name)]
            if not docs:
                raise AppError(
                    "material_not_found",
                    "当前资料范围中没有找到所指文件，请在左侧选择对应资料",
                    409,
                )
        refs = [doc for doc in docs if doc.document_type != "exam"]
        ready = [
            doc
            for doc in refs
            if doc.status == "ready"
            and doc.embedding_fingerprint == service.retriever.embeddings.fingerprint
        ]
        if not ready:
            states = {
                "processing": "正在解析/OCR",
                "cancelling": "正在停止",
                "cancelled": "已取消，需要重试",
                "failed": "处理未完成，需要重试",
                "stale": "需要重建索引",
            }
            detail = "；".join(
                f"{doc.name[:55]}：{states.get(doc.status, doc.status)}" for doc in refs[:3]
            )
            raise AppError(
                "materials_not_ready",
                "目前没有可学习的参考资料。" + (detail or "请上传教材、课件或笔记并等待显示可检索"),
                409,
            )
        if request.document_ids is not None and len(ready) != len(refs):
            raise AppError(
                "materials_not_ready",
                "选中的资料尚未全部完成处理，请先重试或取消勾选未完成资料",
                409,
            )
        ignored = [doc.name for doc in docs if doc not in ready]
        rows = list(
            session.execute(
                select(DocumentChunk, Document)
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(Document.id.in_([doc.id for doc in ready]))
                .order_by(Document.id, DocumentChunk.ordinal)
            )
        )
        return ready, rows, ignored


def material_units(service, request):
    docs, rows, ignored = ready_materials(service, request)
    groups, all_sources = OrderedDict(), []
    loose_sizes = {}
    for chunk, doc in rows:
        heading = (chunk.chapter or chunk.section or "").strip()
        chapter = re.match(r"第\s*([一二三四五六七八九十百\d]+)\s*章", heading)
        if chapter:
            key = (doc.id, "chapter:" + chapter[1])
            title = re.sub(r"\s+", "", heading)[:100]
            structure = "chapter"
        elif heading:
            key = (doc.id, "section:" + normalize(heading))
            title, structure = heading[:100], "section"
        else:
            index, size = loose_sizes.get(doc.id, (1, 0))
            if size and size + len(chunk.text) > service.settings.study_window_chars:
                index, size = index + 1, 0
            loose_sizes[doc.id] = (index, size + len(chunk.text))
            key = (doc.id, "part:" + str(index))
            title, structure = f"{doc.name[:60]} · 资料段 {index}", "part"
        if key not in groups:
            topic = f"{doc.name[:40]} · {title[:75]}" if len(docs) > 1 else title
            if topic in {group["topic"] for group in groups.values()}:
                topic = topic[:105] + f" · {len(groups) + 1}"
            groups[key] = dict(topic=topic, structure=structure, document_id=doc.id, sources=[])
        source = chunk_source(chunk, doc, f"S{len(all_sources) + 1}")
        groups[key]["sources"].append(source)
        all_sources.append(source)
    if not groups:
        raise AppError("materials_not_ready", "资料尚未建立正文索引，请重新处理后再生成学习包", 409)
    units = list(groups.values())
    if len(units) > 64:
        if len(docs) > 64:
            raise AppError(
                "study_scope_too_large", "单次学习最多包含 64 份参考资料，请缩小范围", 422
            )
        # A long slide deck should not fail simply because every slide has its own title.
        compact = []
        for doc in docs:
            own = [u for u in units if u["document_id"] == doc.id]
            slots = 1 + int((64 - len(docs)) * len(own) / len(units))
            step = max(1, ceil(len(own) / slots))
            for offset in range(0, len(own), step):
                batch = own[offset : offset + step]
                if len(batch) == 1:
                    compact.append(batch[0])
                else:
                    compact.append(
                        dict(
                            topic=f"{doc.name[:65]} · 小节 {offset + 1}–{offset + len(batch)}",
                            structure="group",
                            document_id=doc.id,
                            subtopics=[u["topic"] for u in batch],
                            sources=[s for u in batch for s in u["sources"]],
                        )
                    )
        units = compact
    return docs, units, all_sources, ignored


def windows(sources, limit):
    result, batch, chars = [], [], 0
    for source in sources:
        if batch and chars + len(source.text) > limit:
            result.append(batch)
            batch, chars = [], 0
        batch.append(source)
        chars += len(source.text)
    if batch:
        result.append(batch)
    return result


def evidence(topic_ids, sources, **extra):
    return dict(
        topics=topic_ids, sources=[dict(id=s.citation_id, text=s.text) for s in sources], **extra
    )


def validate(service, task, content, ids, sources):
    headings = []
    for source in sources:
        match = re.match(
            r"第\s*[一二三四五六七八九十百\d]+\s*章", source.chapter or source.section or ""
        )
        if match:
            headings.extend([match[0], re.sub(r"\s+", "", match[0])])
    service._validate(task, content, ids, allowed_headings=headings)


def exam_batches(units, count):
    batches, current, capacity = [], {}, 6
    for index, unit in enumerate(units):
        quota = count // len(units) + (index < count % len(units))
        while quota:
            take = min(quota, capacity)
            current[unit["topic"]] = take
            quota, capacity = quota - take, capacity - take
            if capacity == 0:
                batches.append(current)
                current, capacity = {}, 6
    if current:
        batches.append(current)
    return batches


def generate_study_pack(service, request):
    if not service.lock.acquire(blocking=False):
        raise AppError("generation_busy", "已有内容正在生成，请稍后重试", 409)
    checkpoint = StudyCheckpoint(service, request)
    try:
        return _generate(service, request, checkpoint)
    except AppError as exc:
        exc.usage = dict(checkpoint.usage)
        if checkpoint.saved + checkpoint.hits:
            exc.message += f"。已保留 {checkpoint.saved + checkpoint.hits} 段已完成整理，再次提交相同资料可继续，避免重复整理。"
        raise
    finally:
        service.lock.release()


def _generate(service, request, checkpoint):
    start = time.perf_counter()
    docs, units, sources, ignored = material_units(service, request)
    count = request.question_count or max(5, len(units))
    if request.include_questions and count < len(units):
        raise AppError(
            "invalid_blueprint",
            f"资料包含 {len(units)} 个章节/小节，每个至少一道题，需要至少 {len(units)} 题，或缩小资料范围",
            422,
        )
    if (
        service.settings.study_mode == "demo"
        and request.include_questions
        and request.question_type != "short_answer"
    ):
        raise AppError(
            "demo_question_type", "演示模式仅支持摘录简答练习，其他题型请使用 API 模式", 422
        )
    batches = [windows(unit["sources"], service.settings.study_window_chars) for unit in units]
    paper_batches = exam_batches(units, count) if request.include_questions else []
    planned = sum(len(batch) + (len(batch) > 1) for batch in batches) + len(paper_batches)
    if planned > service.settings.study_max_calls:
        raise AppError(
            "study_scope_too_large", "整份资料超出本次学习任务预算，请选择部分资料分次学习", 422
        )
    sections, usage = [], checkpoint.usage
    lookup = {s.citation_id: s for s in sources}
    for unit, unit_batches in zip(units, batches):
        task = StudyGenerationTask(kind="review", topics=[unit["topic"]])
        partials = []
        for batch in unit_batches:
            ids = {unit["topic"]: [s.citation_id for s in batch]}
            if service.settings.study_mode == "demo":
                content = service._demo(task, batch, ids)
            else:
                content = checkpoint.generate(
                    task,
                    evidence(ids, batch),
                    batch,
                    lambda result: validate(service, task, result, ids, batch),
                )
            validate(service, task, content, ids, batch)
            partials.extend(content.sections)
        if len(partials) == 1:
            section = partials[0]
        else:
            cited = list(dict.fromkeys(c for part in partials for c in part.citation_ids))
            ids = {unit["topic"]: cited}
            if service.settings.study_mode == "demo":
                section = ReviewSection(
                    topic=unit["topic"],
                    summary="本节各段原文摘录，演示模式未进行模型总结。",
                    key_points=[point for part in partials for point in part.key_points][:8],
                    citation_ids=cited[:20],
                )
            else:
                # Consolidate drafts with their observed original citations, without losing scope.
                snapshots = [lookup[c] for c in cited]
                content = checkpoint.generate(
                    task,
                    evidence(
                        ids,
                        snapshots,
                        partial_reviews=[part.model_dump() for part in partials],
                        consolidate=True,
                    ),
                    snapshots,
                    lambda result: validate(service, task, result, ids, snapshots),
                )
                validate(service, task, content, ids, snapshots)
                section = content.sections[0]
        sections.append(section)
    questions = []
    for blueprint in paper_batches:
        chapter_sections = [section for section in sections if section.topic in blueprint]
        task = StudyGenerationTask(
            kind="mock_exam",
            topics=list(blueprint),
            question_count=sum(blueprint.values()),
            question_type=request.question_type,
            difficulty=request.difficulty,
        )
        ids = {section.topic: section.citation_ids for section in chapter_sections}
        selected = list(
            dict.fromkeys(c for section in chapter_sections for c in section.citation_ids)
        )
        exam_sources = [lookup[c] for c in selected]
        if service.settings.study_mode == "demo":
            items = []
            for topic, quota in blueprint.items():
                topic_task = task.model_copy(update={"topics": [topic], "question_count": quota})
                items.extend(
                    service._demo(
                        topic_task,
                        exam_sources,
                        {topic: ids[topic]},
                        excluded=[q.answer for q in questions + items],
                    ).questions
                )
            content = GeneratedContent(title="摘录练习", questions=items)
        else:
            content = checkpoint.generate(
                task,
                evidence(
                    ids,
                    exam_sources,
                    chapter_reviews=[section.model_dump() for section in chapter_sections],
                    question_blueprint=blueprint,
                    avoid_stems=[q.stem for q in questions],
                ),
                exam_sources,
                lambda result: validate(service, task, result, ids, exam_sources),
            )
        validate(service, task, content, ids, exam_sources)
        if Counter(q.topic for q in content.questions) != Counter(blueprint):
            raise AppError(
                "generation_invalid_content", "题目没有按章节蓝图分配，未保存，请重试", 502
            )
        questions.extend(content.questions)
    if len({re.sub(r"\s+", "", q.stem) for q in questions}) != len(questions):
        raise AppError(
            "generation_invalid_content", "不同出题批次出现重复题目，未保存，请重试", 502
        )
    content = GeneratedContent(
        title="资料学习包 · 重点与复习练习" if questions else "资料学习包 · 分章重点",
        sections=sections,
        questions=questions,
    )
    final_citations = {c for item in sections + questions for c in item.citation_ids}
    cited_sources = [source for source in sources if source.citation_id in final_citations]
    coverage = dict(
        documents=[dict(id=doc.id, name=doc.name) for doc in docs],
        read_chunks=len(sources),
        read_characters=sum(len(s.text) for s in sources),
        generation_calls=checkpoint.calls,
        cached_summaries=checkpoint.hits,
        units=[
            dict(
                topic=u["topic"],
                structure=u["structure"],
                chunks=len(u["sources"]),
                subtopics=u.get("subtopics", [u["topic"]]),
                first_page=min([s.page for s in u["sources"] if s.page] or [0]),
                last_page=max([s.page for s in u["sources"] if s.page] or [0]),
            )
            for u in units
        ],
        ignored_documents=ignored,
    )
    warning = "按已识别章节/小节分段读取资料并生成；OCR 标题、重点与参考答案需对照原文核查。"
    if any(u["structure"] == "part" for u in units):
        warning += "部分资料没有明确章节标题，按资料段组织，未假定教材目录。"
    if any(u["structure"] == "group" for u in units):
        warning += "小节较多，已合并相邻小节组织总结，所有正文仍逐段读取。"
    if ignored:
        warning += "本次未使用：" + "、".join(ignored)
    if service.settings.study_mode == "demo":
        warning = "演示模式：原文摘录与摘录练习，未调用模型，不代表真实总结与出题质量。" + warning
    with service.sessions() as session:
        row = StudyArtifact(
            course_id=request.course_id,
            kind="study_pack",
            title=content.title,
            mode=service.settings.study_mode,
            warning=warning,
            payload=dict(
                request=request.model_dump(mode="json"),
                content=content.model_dump(mode="json"),
                sources=[s.model_dump(mode="json") for s in cited_sources],
                usage=usage,
                coverage=coverage,
                total_ms=round((time.perf_counter() - start) * 1000, 1),
            ),
        )
        session.add(row)
        session.commit()
        return service._out(row)
