import re
from dataclasses import dataclass, field

from pydantic import ValidationError
from sqlalchemy import select

from app.core.errors import AppError
from app.models import Document
from app.schemas.agent import KnowledgeArgs, QuestionArgs, ToolResult
from app.schemas.chat import SearchRequest, Source
from app.schemas.exam import QuestionSearch
from app.schemas.generation import ArtifactSummary, GenerationArgs, GenerationRequest
from app.schemas.learning import LearningArgs, PlanArgs, WrongListArgs

TOOL_SPECS = {
    "get_learning_progress": (
        LearningArgs,
        "读取真实练习次数、自评正确率、错题与薄弱知识点，不推断能力。",
    ),
    "list_wrong_questions": (WrongListArgs, "读取尚未掌握的错题及原题快照、作答与错因。"),
    "create_study_plan": (
        PlanArgs,
        "根据薄弱知识点或 topics 安排 days 天、每天 daily_minutes 分钟的复习计划并保存。仅在用户明确要求安排计划时使用。",
    ),
    "generate_weakness_review": (
        LearningArgs,
        "根据真实错题中的薄弱知识点生成有资料来源的复习提纲；仅在用户明确要求生成薄弱点复习资料时使用。",
    ),
    "generate_review": (
        GenerationArgs,
        "按 topics 主题生成并保存有来源的复习提纲、关键点和易错点。只有用户明确要求生成时使用。",
    ),
    "generate_mock_exam": (
        GenerationArgs,
        "按 topics、question_count、question_type 和 difficulty 生成并保存模拟卷及参考解析。"
        "题型为 choice/short_answer/calculation；demo 仅支持 short_answer。只有用户明确要求生成时使用。",
    ),
    "search_knowledge": (
        KnowledgeArgs,
        "检索课程教材、课件、笔记中的知识；query 用简短知识关键词。",
    ),
    "locate_source": (KnowledgeArgs, "定位知识在资料中的原文与真实页码、章节或段落。"),
    "search_questions": (
        QuestionSearch,
        "搜索历史试题。按知识关键词 query、试卷名 paper_name、题号 number、题型或知识点筛选；题号可能重复。",
    ),
    "get_question": (QuestionArgs, "根据搜索返回的 question_id 获取原题、选项、知识点和真实来源。"),
    "analyze_question": (
        QuestionArgs,
        "结合教材检索分析已找到的题目，返回参考答案、解析及相关题；必须使用已查询到的 question_id。",
    ),
}


@dataclass
class ToolContext:
    request: SearchRequest
    sources: dict[str, Source] = field(default_factory=dict)
    questions: dict = field(default_factory=dict)
    artifacts: dict = field(default_factory=dict)
    plans: dict = field(default_factory=dict)
    learning: dict = field(default_factory=dict)
    learning_answer: str = ""

    def cite(self, sources: list[Source]) -> list[Source]:
        result = []
        for source in sources:
            # 不同工具可能各自返回 S1；统一编号才能让多轮观察和最终答案指向同一证据。
            if source.chunk_id not in self.sources:
                self.sources[source.chunk_id] = source.model_copy(
                    update={"citation_id": f"S{len(self.sources) + 1}"}
                )
            result.append(self.sources[source.chunk_id])
        return result


class ToolRegistry:
    def __init__(self, settings, sessions, retriever, exams, llm, generation=None, learning=None):
        self.settings, self.sessions, self.retriever = settings, sessions, retriever
        self.exams, self.llm = exams, llm
        self.generation, self.learning = generation, learning

    @staticmethod
    def schemas() -> list[dict]:
        # Schema 与运行时校验共用 Pydantic 定义，防止工具说明和实际参数逐渐不一致。
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": schema.model_json_schema(),
                },
            }
            for name, (schema, description) in TOOL_SPECS.items()
        ]

    def execute(self, name: str, arguments: str, context: ToolContext) -> ToolResult:
        if name not in TOOL_SPECS:
            raise AppError("unknown_tool", "工具不存在；请使用已注册的工具")
        try:
            args = TOOL_SPECS[name][0].model_validate_json(arguments)
        except (ValidationError, ValueError) as exc:
            raise AppError(
                "invalid_tool_arguments", "工具参数不合法，请按 JSON Schema 修正"
            ) from exc
        # 课程和资料范围来自用户请求，由服务端注入；模型无权自行扩大检索范围。
        request = context.request
        if name in {"get_learning_progress", "list_wrong_questions", "create_study_plan"}:
            if name == "get_learning_progress":
                data = self.learning.progress(request)
                rate = f"{data['accuracy']}%" if data["accuracy"] is not None else "暂无记录"
                answer = f"已记录 {data['attempts']} 次练习，自评正确率 {rate}；{data['active_wrong']} 道错题待复习。"
            elif name == "list_wrong_questions":
                wrongs = self.learning.wrong_questions(request, limit=args.limit)
                data = {"wrongbook": wrongs}
                answer = f"找到 {len(wrongs)} 道待复习错题。" + "\n".join(
                    w["snapshot"]["stem"] for w in wrongs
                )
            else:
                if not re.search(r"计划|安排|规划", request.question):
                    raise AppError("plan_not_requested", "用户尚未要求安排复习计划")
                plan = self.learning.create_plan(request, args)
                context.plans[plan["id"]] = plan
                data = {"plan": plan}
                answer = (
                    f"已保存 {len(plan['tasks'])} 天复习计划，每天 {plan['daily_minutes']} 分钟，主题："
                    + "、".join(plan["topics"])
                )
            context.learning.update(data)
            context.learning_answer = answer
            return ToolResult(learning=data, plans=list(context.plans.values()), answer=answer)
        if name == "generate_weakness_review":
            if not re.search(r"生成|整理|制作", request.question):
                raise AppError("generation_not_requested", "用户尚未要求生成复习资料")
            topics = [
                w["topic"]
                for w in self.learning.progress(request)["weak_topics"]
                if w["topic"] != "未标注知识点"
            ]
            if not topics:
                raise AppError("no_weak_topics", "还没有带知识点的待复习错题，请先记录练习")
            args = GenerationArgs(topics=topics)
        if name in {"generate_review", "generate_mock_exam", "generate_weakness_review"}:
            if not re.search(
                r"生成|整理|制作|出题|出.*卷|复习提纲|模拟卷|模拟试卷", request.question
            ):
                raise AppError("generation_not_requested", "用户尚未要求生成复习资料或练习卷")
            artifact = self.generation.generate(
                GenerationRequest(
                    **args.model_dump(),
                    course_id=request.course_id,
                    document_ids=request.document_ids,
                    kind="mock_exam" if name == "generate_mock_exam" else "review",
                )
            )
            summary = ArtifactSummary.model_validate(artifact.model_dump())
            context.artifacts[artifact.id] = summary
            return ToolResult(
                sources=context.cite(artifact.sources),
                artifacts=[summary],
                answer="生成结果已保存，可在生成记录中预览和下载。",
                warning=artifact.warning,
                usage=artifact.usage,
            )
        if name in {"search_knowledge", "locate_source"}:
            return ToolResult(sources=self._knowledge(args.query, context))
        if name == "search_questions":
            questions = self.exams.search(request.course_id, request.document_ids, args)
            for question in questions:
                context.questions[question.id] = question
            sources = context.cite([self._question_source(q, request.course_id) for q in questions])
            return ToolResult(questions=questions, sources=sources)
        if name == "analyze_question" and args.question_id not in context.questions:
            raise AppError("question_not_observed", "请先搜索或获取题目，再调用分析工具")
        question = self.exams.get(request.course_id, request.document_ids, args.question_id)
        context.questions[question.id] = question
        sources = context.cite([self._question_source(question, request.course_id)])
        if name == "get_question":
            return ToolResult(questions=[question], sources=sources)
        return self._analyze(question, sources, context)

    def _knowledge(self, query: str, context: ToolContext) -> list[Source]:
        request = context.request
        with self.sessions() as session:
            statement = select(Document.id).where(
                Document.course_id == request.course_id, Document.document_type != "exam"
            )
            if request.document_ids is not None:
                statement = statement.where(Document.id.in_(request.document_ids))
            ids = list(session.scalars(statement))
        if not ids:
            return []
        result = self.retriever.search(
            SearchRequest(course_id=request.course_id, document_ids=ids, question=query)
        )
        return context.cite(result.sources)

    @staticmethod
    def _question_source(question, course_id) -> Source:
        return Source(
            **question.locations[0],
            text=question.content,
            citation_id="",
            chunk_id="question:" + question.id,
            course_id=course_id,
            document_id=question.document_id,
            document_name=question.paper_name,
            document_type="exam",
            file_type=question.file_type,
            score=1.0,
            file_url=question.file_url,
        )

    def _analyze(self, question, sources: list[Source], context: ToolContext) -> ToolResult:
        query = " ".join(question.knowledge_points) or question.content[:1500]
        evidence = self._knowledge(query[:2000], context)
        related = (
            self.exams.search(
                context.request.course_id,
                context.request.document_ids,
                QuestionSearch(query=" ".join(question.knowledge_points), limit=6),
            )
            if question.knowledge_points
            else []
        )
        related = [q for q in related if q.id != question.id][:5]
        for item in related:
            context.questions[item.id] = item
        sources = sources + evidence
        sources += context.cite(
            [self._question_source(q, context.request.course_id) for q in related]
        )
        if self.settings.study_mode == "demo":
            return ToolResult(
                sources=sources,
                questions=[question] + related,
                insufficient_evidence=True,
                answer="演示模式未调用 LLM，仅提供原题、相关资料和关联试题，未生成参考答案。",
            )
        if not evidence:
            return ToolResult(
                sources=sources,
                questions=[question] + related,
                insufficient_evidence=True,
                answer="当前资料中未找到可靠来源，无法生成有依据的参考答案。",
            )
        if len(question.content) > 6000:
            # 不能静默截掉题目后半段；那里可能包含计算条件或选项，缺失会改变答案。
            return ToolResult(
                sources=sources,
                questions=[question] + related,
                insufficient_evidence=True,
                answer="题目超过单次分析长度上限，请按子题拆分后分析。",
            )
        result = self.llm.generate(
            "请分析以下试题，分为参考答案、详细解析、涉及知识点。答案是基于资料推导的参考答案，不冒充官方答案。"
            "缺少条件或资料不支持时明确拒答。试题：\n" + question.content,
            [{"id": source.citation_id, "text": source.text} for source in evidence],
        )
        answer = result.content
        if not valid_answer(answer, evidence):
            return ToolResult(
                sources=sources,
                questions=[question] + related,
                insufficient_evidence=True,
                answer="当前资料不足或模型引用无效，未生成可靠解析。",
                usage=result.usage or {},
            )
        return ToolResult(
            sources=sources,
            questions=[question] + related,
            answer=answer.answer,
            insufficient_evidence=answer.insufficient_evidence,
            usage=result.usage or {},
        )


def valid_answer(answer, sources: list[Source]) -> bool:
    if answer.insufficient_evidence:
        return False
    available = {source.citation_id for source in sources}
    claimed = set(answer.citation_ids)
    inline = set(re.findall(r"\[(S\d+)\]", answer.answer))
    # 引用必须既出现在正文，也属于实际观察到的证据；位置事实交给来源卡片展示。
    return bool(
        answer.answer.strip()
        and claimed
        and claimed == inline
        and claimed.issubset(available)
        and not re.search(r"第\s*[\d一二三四五六七八九十百]+\s*[页章]", answer.answer)
    )
