from collections import Counter
from datetime import datetime, timedelta, timezone
from threading import Lock

from sqlalchemy import select

from app.core.errors import AppError
from app.models import Conversation, Document, PracticeAttempt, StudyPlan, WrongQuestion, new_id
from app.schemas.chat import SearchRequest
from app.schemas.learning import PlanArgs, PracticeRequest

SHANGHAI = timezone(timedelta(hours=8))


class LearningService:
    """记录来自真实题目/生成成品的练习，自评结果与模型判断分开。"""

    def __init__(self, sessions, exams, generation):
        self.sessions, self.exams, self.generation = sessions, exams, generation
        self.lock = Lock()

    @staticmethod
    def in_scope(snapshot, document_ids):
        return document_ids is None or bool(
            set(snapshot.get("document_ids", [])) & set(document_ids)
        )

    def _snapshot(self, course_id, body):
        if body.reference_type == "question":
            q = self.exams.get(course_id, None, body.reference_id)
            return {
                "stem": q.content,
                "topics": q.knowledge_points,
                "options": q.options,
                "answer": "",
                "explanation": "",
                "title": q.paper_name,
                "document_ids": [q.document_id],
                "file_url": q.file_url,
                "reference_type": "question",
                "reference_id": q.id,
                "question_index": 0,
            }
        if body.reference_type == "artifact":
            artifact = self.generation.get(course_id, body.reference_id)
            questions = artifact.content.questions
            if body.question_index >= len(questions):
                raise AppError("practice_not_found", "生成记录中没有这道练习题", 404)
            q = questions[body.question_index]
            return {
                "stem": q.stem,
                "topics": [q.topic],
                "options": q.options,
                "answer": q.answer,
                "explanation": q.explanation,
                "title": artifact.title,
                "document_ids": list(
                    dict.fromkeys(
                        s.document_id for s in artifact.sources if s.citation_id in q.citation_ids
                    )
                ),
                "file_url": None,
                "reference_type": "artifact",
                "reference_id": artifact.id,
                "question_index": body.question_index,
            }
        with self.sessions() as session:
            wrong = session.get(WrongQuestion, body.reference_id)
            if wrong is None or wrong.course_id != course_id:
                raise AppError("wrong_not_found", "当前课程中没有这条错题", 404)
            return dict(wrong.snapshot)

    def record_practice(self, course_id: str, body: PracticeRequest):
        self.exams.validate_scope(course_id, None)
        snapshot = self._snapshot(course_id, body)
        key = (
            f"{snapshot['reference_type']}:{snapshot['reference_id']}:{snapshot['question_index']}"
        )
        with self.lock, self.sessions() as session:
            attempt = PracticeAttempt(
                course_id=course_id,
                reference_key=key,
                snapshot=snapshot,
                answer=body.answer.strip(),
                outcome=body.outcome,
                note=body.note.strip(),
            )
            session.add(attempt)
            wrong = session.scalar(
                select(WrongQuestion).where(
                    WrongQuestion.course_id == course_id,
                    WrongQuestion.reference_key == key,
                )
            )
            if body.outcome == "wrong":
                if wrong is None:
                    wrong = WrongQuestion(course_id=course_id, reference_key=key, snapshot=snapshot)
                    session.add(wrong)
                wrong.answer, wrong.note, wrong.mastered = (
                    body.answer.strip(),
                    body.note.strip(),
                    False,
                )
                wrong.wrong_count = (wrong.wrong_count or 0) + 1
            elif wrong is not None:
                wrong.mastered = True
            session.commit()
            return {
                "id": attempt.id,
                "outcome": attempt.outcome,
                "wrong_id": wrong.id if wrong else None,
                "assessment": "self_reported",
            }

    @staticmethod
    def _wrong_out(row):
        return {
            "id": row.id,
            "course_id": row.course_id,
            "snapshot": row.snapshot,
            "answer": row.answer,
            "note": row.note,
            "mastered": row.mastered,
            "wrong_count": row.wrong_count,
            "created_at": row.created_at,
        }

    def wrong_questions(self, request: SearchRequest, include_mastered=False, limit=50, offset=0):
        self.exams.validate_scope(request.course_id, request.document_ids)
        with self.sessions() as session:
            query = select(WrongQuestion).where(WrongQuestion.course_id == request.course_id)
            if not include_mastered:
                query = query.where(WrongQuestion.mastered.is_(False))
            rows = session.scalars(
                query.order_by(WrongQuestion.created_at.desc(), WrongQuestion.id)
            )
            scoped = [
                self._wrong_out(row)
                for row in rows
                if self.in_scope(row.snapshot, request.document_ids)
            ]
            return scoped[offset : offset + limit]

    def update_wrong(self, course_id, wrong_id, mastered):
        self.exams.validate_scope(course_id, None)
        with self.lock, self.sessions() as session:
            row = session.get(WrongQuestion, wrong_id)
            if row is None or row.course_id != course_id:
                raise AppError("wrong_not_found", "当前课程中没有这条错题", 404)
            row.mastered = mastered
            session.commit()
            return self._wrong_out(row)

    def progress(self, request: SearchRequest):
        self.exams.validate_scope(request.course_id, request.document_ids)
        with self.sessions() as session:
            documents = list(
                session.scalars(select(Document).where(Document.course_id == request.course_id))
            )
            if request.document_ids is not None:
                documents = [d for d in documents if d.id in request.document_ids]
            attempts = [
                a
                for a in session.scalars(
                    select(PracticeAttempt)
                    .where(PracticeAttempt.course_id == request.course_id)
                    .order_by(PracticeAttempt.created_at)
                )
                if self.in_scope(a.snapshot, request.document_ids)
            ]
            wrongs = [
                w
                for w in session.scalars(
                    select(WrongQuestion).where(WrongQuestion.course_id == request.course_id)
                )
                if self.in_scope(w.snapshot, request.document_ids)
            ]
            plans = [
                p
                for p in session.scalars(
                    select(StudyPlan).where(StudyPlan.course_id == request.course_id)
                )
                if self.in_scope({"document_ids": p.document_ids}, request.document_ids)
            ]
        latest = {a.reference_key: a for a in attempts}
        correct = sum(a.outcome == "correct" for a in latest.values())
        weaknesses = Counter(
            t
            for w in wrongs
            if not w.mastered
            for t in w.snapshot.get("topics", []) or ["未标注知识点"]
        )
        daily = Counter(
            datetime.fromisoformat(a.created_at).astimezone(SHANGHAI).date().isoformat()
            for a in attempts
        )
        today = datetime.now(SHANGHAI).date()
        return {
            "documents": len(documents),
            "ready_documents": sum(d.status == "ready" for d in documents),
            "attempts": len(attempts),
            "practiced_questions": len(latest),
            "correct_questions": correct,
            "accuracy": round(correct / len(latest) * 100) if latest else None,
            "active_wrong": sum(not w.mastered for w in wrongs),
            "mastered_wrong": sum(w.mastered for w in wrongs),
            "weak_topics": [
                {"topic": topic, "count": count} for topic, count in weaknesses.most_common(8)
            ],
            "week": [
                {
                    "date": (today - timedelta(days=6 - i)).isoformat(),
                    "count": daily[(today - timedelta(days=6 - i)).isoformat()],
                }
                for i in range(7)
            ],
            "plan_tasks": sum(len(p.tasks) for p in plans),
            "completed_tasks": sum(t["completed"] for p in plans for t in p.tasks),
            "assessment": "self_reported",
        }

    @staticmethod
    def _plan_out(row):
        return {
            "id": row.id,
            "course_id": row.course_id,
            "title": row.title,
            "topics": row.topics,
            "daily_minutes": row.daily_minutes,
            "tasks": row.tasks,
            "document_ids": row.document_ids,
            "created_at": row.created_at,
        }

    def create_plan(self, request: SearchRequest, args: PlanArgs):
        self.exams.validate_scope(request.course_id, request.document_ids)
        with self.sessions() as session:
            query = select(Document).where(
                Document.course_id == request.course_id, Document.status == "ready"
            )
            if request.document_ids is not None:
                query = query.where(Document.id.in_(request.document_ids))
            docs = list(session.scalars(query))
        if not docs:
            raise AppError("plan_no_material", "请先上传可用资料，再安排复习计划", 409)
        topics = args.topics or [
            w["topic"]
            for w in self.progress(request)["weak_topics"]
            if w["topic"] != "未标注知识点"
        ]
        if not topics:
            from app.schemas.exam import QuestionSearch

            questions = self.exams.search(
                request.course_id, request.document_ids, QuestionSearch(limit=30)
            )
            topics = list(dict.fromkeys(t for q in questions for t in q.knowledge_points))[:8]
        topics = topics or [d.name.rsplit(".", 1)[0][:120] for d in docs[:8]]
        today = datetime.now(SHANGHAI).date()
        actions = [
            "梳理概念并对照资料",
            "不看资料主动回忆",
            "练习相关题并记录错因",
            "复盘错题与易错点",
        ]
        group_count = min(len(topics), args.days)
        groups = [topics[i::group_count] for i in range(group_count)]
        tasks = [
            {
                "id": new_id(),
                "day": i + 1,
                "due_date": (today + timedelta(days=i)).isoformat(),
                "topics": groups[i % group_count],
                "action": actions[(i // group_count) % len(actions)],
                "minutes": args.daily_minutes,
                "completed": False,
            }
            for i in range(args.days)
        ]
        with self.sessions() as session:
            plan = StudyPlan(
                course_id=request.course_id,
                title=f"{args.days} 天复习计划",
                topics=topics,
                daily_minutes=args.daily_minutes,
                tasks=tasks,
                document_ids=[d.id for d in docs],
            )
            session.add(plan)
            session.commit()
            return self._plan_out(plan)

    def plans(self, course_id, limit=20, offset=0):
        self.exams.validate_scope(course_id, None)
        with self.sessions() as session:
            return [
                self._plan_out(p)
                for p in session.scalars(
                    select(StudyPlan)
                    .where(StudyPlan.course_id == course_id)
                    .order_by(StudyPlan.created_at.desc(), StudyPlan.id)
                    .offset(offset)
                    .limit(limit)
                )
            ]

    def update_task(self, course_id, plan_id, task_id, completed):
        self.exams.validate_scope(course_id, None)
        with self.lock, self.sessions() as session:
            plan = session.get(StudyPlan, plan_id)
            if plan is None or plan.course_id != course_id:
                raise AppError("plan_not_found", "当前课程中没有这份计划", 404)
            if not any(t["id"] == task_id for t in plan.tasks):
                raise AppError("task_not_found", "计划中没有这项任务", 404)
            plan.tasks = [
                dict(t, completed=completed) if t["id"] == task_id else dict(t) for t in plan.tasks
            ]
            session.commit()
            return self._plan_out(plan)

    def save_conversation(self, request, kind, result):
        result.conversation_id = result.conversation_id or new_id()
        with self.sessions() as session:
            row = Conversation(
                id=result.conversation_id,
                course_id=request.course_id,
                question=request.question,
                kind=kind,
                document_ids=request.document_ids,
                payload=result.model_dump(mode="json"),
            )
            session.add(row)
            session.commit()

    def conversations(self, course_id, limit=20, offset=0):
        self.exams.validate_scope(course_id, None)
        with self.sessions() as session:
            return [
                {"id": c.id, "question": c.question, "kind": c.kind, "created_at": c.created_at}
                for c in session.scalars(
                    select(Conversation)
                    .where(Conversation.course_id == course_id)
                    .order_by(Conversation.created_at.desc(), Conversation.id)
                    .offset(offset)
                    .limit(limit)
                )
            ]

    def conversation(self, course_id, conversation_id):
        self.exams.validate_scope(course_id, None)
        with self.sessions() as session:
            row = session.get(Conversation, conversation_id)
            if row is None or row.course_id != course_id:
                raise AppError("conversation_not_found", "当前课程中没有这条对话", 404)
            return {
                "id": row.id,
                "question": row.question,
                "kind": row.kind,
                "document_ids": row.document_ids,
                "result": row.payload,
            }

    def delete_conversation(self, course_id, conversation_id):
        self.exams.validate_scope(course_id, None)
        with self.lock, self.sessions() as session:
            row = session.get(Conversation, conversation_id)
            if row is None or row.course_id != course_id:
                raise AppError("conversation_not_found", "当前课程中没有这条对话", 404)
            session.delete(row)
            session.commit()
