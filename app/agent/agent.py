import json
import logging
import time
from uuid import uuid4

from app.agent.intents import relation_intent, study_intent
from app.agent.planner import AGENT_PROMPT
from app.agent.tools import TOOL_SPECS, ToolContext, valid_answer
from app.core.errors import AppError
from app.schemas.agent import AgentResponse, ToolTrace
from app.schemas.chat import SearchRequest

logger = logging.getLogger("studyagent")


class StudyAgent:
    def __init__(self, settings, registry, planner):
        self.settings, self.registry, self.planner = settings, registry, planner

    def run(self, request: SearchRequest) -> AgentResponse:
        self.registry.exams.validate_scope(request.course_id, request.document_ids)
        start, run_id = time.perf_counter(), uuid4().hex
        context = ToolContext(request)
        intent = relation_intent(request.question)
        tool = "match_material_questions" if intent is not None else "generate_study_pack"
        if intent is None:
            intent = study_intent(request.question)
        if intent is not None:
            begun = time.perf_counter()
            try:
                result = self.registry.execute(
                    tool, json.dumps(intent, ensure_ascii=False), context
                )
                trace = [
                    ToolTrace(
                        step=1,
                        tool=tool,
                        purpose=TOOL_SPECS[tool][1],
                        arguments=intent,
                        status="ok",
                        observation={
                            "artifacts": len(result.artifacts),
                            "chapters_or_sections": len(
                                result.learning.get("study_coverage", {}).get("units", [])
                            ),
                            "material_question_links": len(
                                result.learning.get("material_question_links", [])
                            ),
                        },
                        elapsed_ms=(time.perf_counter() - begun) * 1000,
                    )
                ]
                return self._finish(
                    context, trace, result.usage, None, "completed", result.warning, start
                )
            except AppError as exc:
                return AgentResponse(
                    answer=exc.message,
                    sources=[],
                    questions=[],
                    artifacts=[],
                    plans=[],
                    learning={},
                    trace=[
                        ToolTrace(
                            step=1,
                            tool=tool,
                            purpose=TOOL_SPECS[tool][1],
                            arguments=intent,
                            status="error",
                            observation={"error": {"code": exc.code, "message": exc.message}},
                            elapsed_ms=(time.perf_counter() - begun) * 1000,
                        )
                    ],
                    mode=self.settings.study_mode,
                    insufficient_evidence=True,
                    finish_reason="study_failed",
                    warning=exc.message,
                    usage={},
                    total_ms=(time.perf_counter() - start) * 1000,
                )
        messages = [
            {"role": "system", "content": AGENT_PROMPT},
            {"role": "user", "content": request.question},
        ]
        trace, usage, cache, call_ids = [], {}, {}, set()
        warning, reason, final = None, "step_limit", None
        # 一轮由“模型选择 → 校验参数 → 执行工具 → 回传观察”组成。
        # 除模型轮数外，也限制总工具调用数，多工具响应不能绕过执行上限。
        for _ in range(self.settings.agent_max_steps + 1):
            if len(json.dumps(messages, ensure_ascii=False)) > self.settings.agent_context_chars:
                reason, warning = "context_limit", "执行上下文达到上限，请缩小资料范围或拆分问题。"
                break
            try:
                turn = self.planner.step(messages, self.registry.schemas())
            except AppError as exc:
                reason, warning = "provider_error", exc.message
                break
            self._usage(usage, turn.usage)
            if not turn.calls:
                final, reason = turn.final, "completed"
                break
            if len(trace) + len(turn.calls) > self.settings.agent_max_steps:
                reason, warning = "step_limit", "达到工具调用上限，已停止；请缩小问题范围后重试。"
                break
            if any(call.id in call_ids for call in turn.calls):
                reason, warning = "provider_error", "模型重复使用工具调用编号，已停止本次执行。"
                break
            call_ids.update(call.id for call in turn.calls)
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [call.model_dump() for call in turn.calls],
                }
            )
            for call in turn.calls:
                begun = time.perf_counter()
                name, raw = call.function.name, call.function.arguments
                try:
                    args = json.loads(raw)
                    if not isinstance(args, dict):
                        raise ValueError("arguments must be object")
                except ValueError:
                    args = {"invalid_json": True}
                key = name + json.dumps(args, sort_keys=True, ensure_ascii=False)
                state = "ok"
                before_sources, before_questions = dict(context.sources), dict(context.questions)
                before_artifacts, before_plans = dict(context.artifacts), dict(context.plans)
                before_learning, before_answer = dict(context.learning), context.learning_answer
                try:
                    if key in cache:
                        output, state = cache[key], "cached"
                    else:
                        result = self.registry.execute(name, raw, context)
                        output = result.model_dump(mode="json")
                        self._usage(usage, result.usage)
                        cache[key] = output
                    observation = {
                        "sources": len(output.get("sources", [])),
                        "questions": len(output.get("questions", [])),
                        "artifacts": len(output.get("artifacts", [])),
                        "insufficient_evidence": output.get("insufficient_evidence", False),
                    }
                except AppError as exc:
                    context.sources, context.questions = before_sources, before_questions
                    context.artifacts, context.plans = before_artifacts, before_plans
                    context.learning, context.learning_answer = before_learning, before_answer
                    # 错误作为 observation 交回模型，让下一轮有机会修正参数或换工具。
                    state, output = "error", {"error": {"code": exc.code, "message": exc.message}}
                    observation = output
                except Exception as exc:
                    # 失败工具没有把结果交给模型，撤回它临时注册的证据，避免引用未观察到的来源。
                    context.sources, context.questions = before_sources, before_questions
                    context.artifacts, context.plans = before_artifacts, before_plans
                    context.learning, context.learning_answer = before_learning, before_answer
                    logger.error(
                        "agent run=%s tool=%s error_type=%s", run_id, name, type(exc).__name__
                    )
                    state, output = (
                        "error",
                        {
                            "error": {
                                "code": "tool_failed",
                                "message": "工具执行失败，请重试或换一种查询",
                            }
                        },
                    )
                    observation = output
                trace.append(
                    ToolTrace(
                        step=len(trace) + 1,
                        tool=name,
                        purpose=TOOL_SPECS[name][1] if name in TOOL_SPECS else "未注册工具",
                        arguments=args,
                        status=state,
                        observation=observation,
                        elapsed_ms=(time.perf_counter() - begun) * 1000,
                    )
                )
                # tool_call_id 把观察绑定到具体调用，模型下一轮可据此继续规划。
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(output, ensure_ascii=False),
                    }
                )
                logger.info(
                    "agent run=%s step=%s tool=%s status=%s observation=%s",
                    run_id,
                    len(trace),
                    name,
                    state,
                    observation,
                )
        return self._finish(context, trace, usage, final, reason, warning, start)

    @staticmethod
    def _usage(total: dict, usage: dict) -> None:
        for key, value in usage.items():
            total[key] = total.get(key, 0) + value

    def _finish(self, context, trace, usage, final, reason, warning, start) -> AgentResponse:
        sources = list(context.sources.values())
        questions = list(context.questions.values())
        answer, insufficient = (
            "当前资料范围没有检索到足够依据，请确认资料已完成处理，或明确需要学习的内容。",
            True,
        )
        if context.learning_answer:
            answer, insufficient = context.learning_answer, False
        elif context.artifacts:
            answer = "已生成并保存：" + "、".join(a.title for a in context.artifacts.values())
            answer += "。可从下方入口预览、练习和下载。"
            if context.learning.get("study_coverage"):
                coverage = context.learning["study_coverage"]
                answer += f"已分段读取 {coverage['read_chunks']} 个正文片段，整理 {len(coverage['units'])} 个章节/小节。"
            insufficient = False
            if self.settings.study_mode == "demo":
                answer += "演示模式未调用 LLM，内容为原文整理与摘录模板。"
                warning = warning or "演示内容不代表真实模型生成质量。"
        elif self.settings.study_mode == "demo":
            answer = "演示模式未调用 LLM，仅展示工具执行结果，未生成参考答案。"
            if not trace and final:
                answer = final.answer
            elif questions:
                answer += "\n\n" + "\n\n".join(
                    f"{q.paper_name} · 第 {q.number} 题\n{q.content}" for q in questions
                )
                if len(questions) > 1 and not any(
                    step.tool == "analyze_question" for step in trace
                ):
                    answer += "\n\n匹配到多道题，可在题库中选择具体题目进行分析。"
            elif sources:
                answer += "\n\n" + "\n\n".join(f"[{s.citation_id}] {s.text}" for s in sources)
            else:
                answer += "\n\n当前范围内没有检索到结果。"
            warning = warning or "规则规划用于离线演示；真实任务选择与推理需要 API 模式。"
        elif final is not None and valid_answer(final, sources):
            answer, insufficient = final.answer, False
            sources = [s for s in sources if s.citation_id in final.citation_ids]
        elif final is not None and not final.insufficient_evidence:
            warning = "模型最终回答缺少有效引用或包含自行生成的位置，已拒绝展示。"
            reason = "invalid_citations"
        elif final is not None:
            # 不展示模型在“证据不足”标记下仍可能生成的事实，保留真实检索结果供用户核查。
            reason = "insufficient_evidence"
            if questions and not any(step.tool == "analyze_question" for step in trace):
                answer = "已找到候选试题，请在下方选择具体题目进行分析。"
        if reason in {"step_limit", "context_limit", "provider_error"}:
            insufficient = True
        if reason == "provider_error" and not context.artifacts:
            answer = (
                "已检索到资料，但模型响应发生错误，本次未完成回答。"
                if sources
                else "模型服务未能完成这次请求。"
            )
            if warning:
                answer += warning
        return AgentResponse(
            learning=context.learning,
            plans=list(context.plans.values()),
            artifacts=list(context.artifacts.values()),
            answer=answer,
            sources=sources,
            questions=questions,
            trace=trace,
            mode=self.settings.study_mode,
            insufficient_evidence=insufficient,
            finish_reason=reason,
            warning=warning,
            total_ms=(time.perf_counter() - start) * 1000,
            usage=usage,
        )
