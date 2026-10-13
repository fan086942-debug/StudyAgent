"""Bounded per-tab Agent context, persisted in the owning workspace with a two-hour TTL."""

import json
import time
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from threading import RLock

from sqlalchemy import delete, select

from app.core.errors import AppError
from app.models import AgentContext, Document


@dataclass
class SessionMemory:
    scope: tuple
    fingerprint: tuple
    turns: list = field(default_factory=list)
    updated: float = field(default_factory=time.monotonic)
    busy: bool = False


class AgentMemory:
    max_turns = 10
    max_chars = 20000
    max_sessions = 100
    ttl = 7200

    def __init__(self, sessions):
        self.sessions, self.entries, self.lock = sessions, {}, RLock()

    def _scope(self, request):
        scope = (
            request.course_id,
            None if request.document_ids is None else tuple(sorted(set(request.document_ids))),
        )
        with self.sessions() as session:
            query = (
                select(Document)
                .where(Document.course_id == request.course_id)
                .order_by(Document.id)
            )
            if request.document_ids is not None:
                query = query.where(Document.id.in_(request.document_ids))
            fingerprint = tuple(
                (d.id, d.sha256, d.status, d.chunk_count, d.embedding_fingerprint)
                for d in session.scalars(query)
            )
        return scope, fingerprint

    def _persist(self, identifier, entry):
        with self.sessions() as session:
            row = session.get(AgentContext, identifier)
            if row is None:
                row = AgentContext(id=identifier, course_id=entry.scope[0])
                session.add(row)
            row.payload = dict(scope=entry.scope, fingerprint=entry.fingerprint, turns=entry.turns)
            row.updated_at = time.time()
            session.execute(delete(AgentContext).where(AgentContext.updated_at < time.time() - self.ttl))
            session.flush()
            # Bound durable storage too; an active context is protected by its in-process lock.
            rows = list(session.scalars(select(AgentContext).order_by(AgentContext.updated_at.desc())))
            for old in rows[self.max_sessions:]:
                cached = self.entries.get(old.id)
                if old.id != identifier and not (cached and cached.busy):
                    session.delete(old)
            session.commit()

    def _restore(self, identifier):
        with self.sessions() as session:
            row = session.get(AgentContext, identifier)
            if row is None or row.updated_at < time.time() - self.ttl:
                return None
            payload = row.payload
            course, documents = payload["scope"]
            scope = (course, None if documents is None else tuple(documents))
            fingerprint = tuple(tuple(item) for item in payload["fingerprint"])
            return SessionMemory(scope, fingerprint, deepcopy(payload["turns"]))

    def _entry(self, identifier, scope, fingerprint):
        now = time.monotonic()
        for key, entry in list(self.entries.items()):
            if not entry.busy and now - entry.updated > self.ttl:
                del self.entries[key]
                with self.sessions() as session:
                    session.execute(delete(AgentContext).where(AgentContext.id == key))
                    session.commit()
        entry = self.entries.get(identifier)
        if entry is None:
            entry = self._restore(identifier)
        reset = entry is None
        if entry is not None and entry.scope != scope:
            raise AppError("session_scope_changed", "课程或资料范围已改变，请开启新对话。", 409)
        if entry is not None and entry.busy:
            raise AppError("session_busy", "当前对话仍在处理上一条消息，请稍后再发送。", 409)
        if identifier not in self.entries:
            if len(self.entries) >= self.max_sessions:
                idle = [(key, value) for key, value in self.entries.items() if not value.busy]
                if not idle:
                    raise AppError("session_capacity", "当前对话服务繁忙，请稍后重试。", 503)
                del self.entries[min(idle, key=lambda item: item[1].updated)[0]]
        if entry is None:
            entry = SessionMemory(scope, fingerprint)
        if entry.fingerprint != fingerprint:
            entry.fingerprint, entry.turns, reset = fingerprint, [], True
        self.entries[identifier] = entry
        entry.updated = now
        self._persist(identifier, entry)
        return entry, reset

    @contextmanager
    def turn(self, request):
        scope, fingerprint = self._scope(request)
        with self.lock:
            entry, reset = self._entry(request.session_id, scope, fingerprint)
            entry.busy = True
            history = deepcopy(entry.turns)
        try:
            yield entry, history, reset
        finally:
            with self.lock:
                entry.busy, entry.updated = False, time.monotonic()
                self._persist(request.session_id, entry)

    def remember(self, entry, request, result, generation):
        turn = dict(
            id=result.conversation_id,
            question=request.question,
            answer=result.answer[:4000],
            topics=[],
            generated_questions=[],
        )
        # Remember generated questions, rather than just "saved successfully".
        for summary in result.artifacts[-1:]:
            artifact = generation.get(request.course_id, summary.id)
            turn["topics"] = artifact.request.topics if hasattr(artifact.request, "topics") else []
            turn["generated_questions"] = [
                dict(
                    q.model_dump(),
                    stem=q.stem[:1000],
                    answer=q.answer[:1000],
                    explanation=q.explanation[:1000],
                )
                for q in artifact.content.questions[:12]
            ]
            if not turn["topics"]:
                turn["topics"] = list(dict.fromkeys(q.topic for q in artifact.content.questions))[
                    :8
                ]
        if not turn["topics"]:
            for trace in reversed(result.trace):
                if trace.status == "ok" and trace.arguments.get("query"):
                    turn["topics"] = [trace.arguments["query"][:120]]
                    break
        if not turn["topics"] and entry.turns:
            turn["topics"] = entry.turns[-1]["topics"]
        if result.finish_reason not in {"completed", "insufficient_evidence"}:
            return
        with self.lock:
            while (
                len(json.dumps(turn, ensure_ascii=False)) > self.max_chars
                and turn["generated_questions"]
            ):
                turn["generated_questions"].pop()
            entry.turns.append(turn)
            while (
                len(entry.turns) > self.max_turns
                or len(json.dumps(entry.turns, ensure_ascii=False)) > self.max_chars
            ):
                entry.turns.pop(0)

    def snapshot(self, request):
        scope, fingerprint = self._scope(request)
        with self.lock:
            entry, reset = self._entry(request.session_id, scope, fingerprint)
            return dict(
                session_id=request.session_id, turns=deepcopy(entry.turns), context_reset=reset
            )

    @contextmanager
    def deleting_conversation(self, course_id, session_id):
        """Commit the deletion before dropping its dependent context; exclude active turns."""
        with self.lock:
            entry = self.entries.get(session_id)
            matches = entry is not None and entry.scope[0] == course_id
            if matches and entry.busy:
                raise AppError("session_busy", "该对话正在生成回答，请处理完成后再删除。", 409)
            if not matches and session_id:
                with self.sessions() as session:
                    row = session.get(AgentContext, session_id)
                    matches = row is not None and row.course_id == course_id
            yield matches
            if matches:
                # The learning service removes durable context in the deletion transaction.
                self.entries.pop(session_id, None)
