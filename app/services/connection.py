import json
import logging
import os
from contextlib import contextmanager
from threading import Lock
from uuid import uuid4

from pydantic import SecretStr, ValidationError

from app.agent.agent import StudyAgent
from app.agent.planner import APIPlanner, DemoPlanner
from app.agent.tools import ToolRegistry
from app.core.errors import AppError
from app.llm.compatible_provider import CompatibleLLM, post_json
from app.llm.exam_provider import ExamExtractor
from app.llm.generation_provider import GenerationProvider
from app.schemas.connection import ConnectionInput
from app.services.agent_memory import AgentMemory
from app.services.exams import ExamService
from app.services.generation import GenerationService
from app.services.ingestion import IngestionService
from app.services.learning import LearningService
from app.services.material_learning import MaterialLearningService
from app.services.pdf_visuals import PDFVisuals
from app.services.qa import QAService

logger = logging.getLogger("studyagent")


class UnconfiguredModelClient:
    def post(self, *_args, **_kwargs):
        raise AppError("connection_required", "请先在模型连接中填写模型和 API Key 并保存", 422)


def model_services(state, settings):
    """Rebind the entire model graph while preserving database and embedding space."""
    model_http = state.http
    if settings.study_mode != "demo" and (
        not settings.llm_model or not settings.llm_api_key.get_secret_value()
    ):
        model_http = UnconfiguredModelClient()
    exams = ExamService(settings, state.sessions, ExamExtractor(settings, model_http))
    ingestion = IngestionService(settings, state.sessions, state.embeddings, state.vectors, exams)
    visuals = PDFVisuals(settings, state.sessions)
    qa = QAService(settings, state.retriever, CompatibleLLM(settings, model_http), visuals)
    generation = GenerationService(
        settings, state.sessions, state.retriever, exams, GenerationProvider(settings, model_http)
    )
    learning = LearningService(state.sessions, exams, generation)
    material_learning = MaterialLearningService(state.sessions, exams, state.retriever)
    registry = ToolRegistry(
        settings,
        state.sessions,
        state.retriever,
        exams,
        qa.llm,
        generation,
        learning,
        material_learning,
        visuals,
    )
    planner = DemoPlanner() if settings.study_mode == "demo" else APIPlanner(settings, model_http)
    if not hasattr(state, "agent_memory"):
        state.agent_memory = AgentMemory(state.sessions)
    return dict(
        settings=settings,
        exams=exams,
        ingestion=ingestion,
        qa=qa,
        generation=generation,
        learning=learning,
        material_learning=material_learning,
        agent=StudyAgent(settings, registry, planner, state.agent_memory),
    )


class ModelConnection:
    def __init__(self, state, defaults):
        self.state, self.defaults = state, defaults
        self.path = defaults.data_dir / "model-connection.json"
        self.lock, self.active_requests = Lock(), 0
        self.exclusive_business = False
        self.profile = ConnectionInput(
            mode=defaults.study_mode,
            base_url=defaults.llm_base_url,
            model=defaults.llm_model,
            api_key=defaults.llm_api_key,
        )
        if self.path.exists():
            try:
                self.profile = ConnectionInput.model_validate_json(self.path.read_text("utf-8"))
                self._require_model(self.profile)
            except (OSError, ValueError, ValidationError, AppError):
                logger.warning("saved_model_connection_invalid; using environment settings")
                self.profile = ConnectionInput(
                    mode=defaults.study_mode,
                    base_url=defaults.llm_base_url,
                    model=defaults.llm_model,
                    api_key=defaults.llm_api_key,
                )
        if defaults.require_real_model and self.profile.mode == "demo":
            self.profile = self.profile.model_copy(update={"mode": "api"})
        settings = self._settings(self.profile)
        self._bind(model_services(state, settings))

    def _settings(self, profile):
        # LLM switching is independent of the embedding provider initialized at startup.
        return self.defaults.model_copy(
            update={
                "study_mode": profile.mode,
                "llm_base_url": profile.base_url,
                "llm_model": profile.model,
                "llm_api_key": profile.api_key,
            }
        )

    def _bind(self, services):
        for name, service in services.items():
            setattr(self.state, name, service)

    @staticmethod
    def _require_model(profile):
        if profile.mode == "api" and (not profile.model or not profile.api_key.get_secret_value()):
            raise AppError("connection_incomplete", "请填写模型名称和 API Key", 422)

    def resolve(self, body):
        with self.lock:
            if self.defaults.require_real_model and body.mode != "api":
                raise AppError("offline_disabled", "当前仅支持真实模型 API，请填写模型连接", 422)
            key = body.api_key.get_secret_value()
            if not key and self.profile.api_key.get_secret_value():
                if body.base_url != self.profile.base_url:
                    raise AppError("connection_key_required", "更换接口地址时，请重新填写密钥", 422)
                key = self.profile.api_key.get_secret_value()
            profile = body.model_copy(update={"api_key": SecretStr(key)})
            self._require_model(profile)
            return profile

    def describe(self):
        with self.lock:
            return self._description()

    def _description(self):
        embedding_settings = getattr(self.state, "embedding_settings", self.defaults)
        return {
            "mode": self.profile.mode,
            "base_url": self.profile.base_url,
            "model": self.profile.model,
            "has_api_key": bool(self.profile.api_key.get_secret_value()),
            "configured": bool(self.profile.model and self.profile.api_key.get_secret_value()),
            "embedding_mode": embedding_settings.study_mode,
            "embedding_model": embedding_settings.embedding_model
            if embedding_settings.study_mode == "api"
            else "本地字词检索",
        }

    def enter_request(self, *, require_model=False):
        with self.lock:
            if require_model and self.defaults.require_real_model:
                if not self.profile.model or not self.profile.api_key.get_secret_value():
                    raise AppError(
                        "connection_required", "请先在模型连接中填写模型和 API Key 并保存", 422
                    )
            if self.exclusive_business:
                raise AppError("course_busy", "正在删除课程，请稍后再操作", 409)
            self.active_requests += 1

    def leave_request(self):
        with self.lock:
            self.active_requests -= 1

    @contextmanager
    def exclusive_task(self):
        with self.lock:
            if self.exclusive_business or self.active_requests != 1:
                raise AppError("course_busy", "当前有任务正在处理，请结束后再删除课程", 409)
            self.exclusive_business = True
        try:
            yield
        finally:
            with self.lock:
                self.exclusive_business = False

    def save(self, body):
        profile = self.resolve(body)
        with self.lock:
            if self.active_requests:
                raise AppError("connection_busy", "当前有任务正在处理，请结束后再切换模型", 409)
            services = model_services(self.state, self._settings(profile))
            temporary = self.path.with_name(f".model-connection-{uuid4().hex}.tmp")
            try:
                # Keys stay only on the local server, under the ignored data directory.
                payload = profile.model_dump(exclude={"api_key"})
                payload["api_key"] = profile.api_key.get_secret_value()
                with temporary.open("w", encoding="utf-8") as file:
                    os.chmod(temporary, 0o600)
                    json.dump(payload, file, ensure_ascii=False)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary, self.path)
            except OSError as exc:
                raise AppError("connection_save_failed", "无法保存本地连接配置", 500) from exc
            finally:
                temporary.unlink(missing_ok=True)
            self._bind(services)
            self.profile = profile
            return self._description()

    def test(self, body):
        profile = self.resolve(body.model_copy(update={"mode": "api"}))
        result = post_json(
            self.state.http,
            profile.base_url + "/chat/completions",
            profile.api_key.get_secret_value(),
            {
                "model": profile.model,
                "max_tokens": 128,
                "messages": [{"role": "user", "content": "请调用 connection_check，ok 为 true。"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "connection_check",
                            "description": "验证工具调用连接",
                            "parameters": {
                                "type": "object",
                                "properties": {"ok": {"type": "boolean"}},
                                "required": ["ok"],
                                "additionalProperties": False,
                            },
                        },
                    }
                ],
                "tool_choice": {"type": "function", "function": {"name": "connection_check"}},
            },
        )
        try:
            call = result["choices"][0]["message"]["tool_calls"][0]["function"]
            if (
                call["name"] != "connection_check"
                or json.loads(call["arguments"]).get("ok") is not True
            ):
                raise ValueError("invalid tool call")
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
            raise AppError(
                "connection_tools_unsupported",
                "接口可响应，但未返回有效工具调用，请选择支持 Tool Calling 的模型",
                502,
            ) from exc
        return {
            "status": "ok",
            "message": "基础连接成功，接口与工具调用可用。此测试不验证长教材生成或最终回答格式；点击保存并启用即可使用。",
        }
