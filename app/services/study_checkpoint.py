import hashlib
import json
import logging
import os
from threading import RLock
from uuid import uuid4

from sqlalchemy import select

from app.core.errors import AppError
from app.llm.structured import merge_usage
from app.models import Document
from app.schemas.generation import GeneratedContent

logger = logging.getLogger("studyagent")
cache_lock = RLock()


def cache_root(data_dir, course_id):
    data_root = data_dir.resolve()
    base = (data_root / "study-cache").resolve()
    if base.parent != data_root:
        return None
    root = (base / hashlib.sha256(course_id.encode()).hexdigest()).resolve()
    return root if root.parent == base else None


def purge_study_cache(data_dir, course_id, document_id=None):
    with cache_lock:
        root = cache_root(data_dir, course_id)
        if root is None or not root.exists():
            return
        for path in root.glob("*.json"):
            if path.resolve().parent != root:
                continue
            if document_id is not None:
                try:
                    if document_id not in json.loads(path.read_text(encoding="utf-8"))["documents"]:
                        continue
                except (OSError, ValueError, KeyError):
                    continue
            path.unlink(missing_ok=True)
        if not any(root.iterdir()):
            root.rmdir()


class StudyCheckpoint:
    """Cache validated chapter work, not incomplete answers or billed usage."""

    def __init__(self, service, request):
        self.service, self.request = service, request
        self.usage, self.calls, self.hits, self.saved = {}, 0, 0, 0

    def generate(self, task, data, sources, validator):
        settings = self.service.settings
        digest = hashlib.sha256(
            json.dumps(
                dict(
                    version="json-contract-2",
                    course=self.request.course_id,
                    model=settings.llm_model,
                    url=settings.llm_base_url,
                    task=task.model_dump(),
                    data=data,
                    provenance=[s.model_dump() for s in sources],
                ),
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()
        root = cache_root(settings.data_dir, self.request.course_id)
        path = root / f"{digest}.json" if root else None
        cacheable = task.kind == "review" and path is not None and path.resolve().parent == root
        if cacheable:
            try:
                content = GeneratedContent.model_validate(
                    json.loads(path.read_text(encoding="utf-8"))["content"]
                )
                validator(content)
                self.hits += 1
                return content
            except (OSError, ValueError, KeyError, AppError):
                pass
        try:
            content, used = self.service.provider.generate(task, data, validator=validator)
            merge_usage(self.usage, used)
        except AppError as exc:
            merge_usage(self.usage, exc.usage)
            raise
        finally:
            self.calls += getattr(self.service.provider, "last_request_count", 1)
        validator(content)
        if cacheable:
            with cache_lock:
                with self.service.sessions() as session:
                    ids = {s.document_id for s in sources}
                    ready = set(
                        session.scalars(
                            select(Document.id).where(
                                Document.id.in_(ids), Document.status == "ready"
                            )
                        )
                    )
                if ids == ready:
                    temporary = root / f".{uuid4().hex}.tmp"
                    try:
                        root.mkdir(parents=True, exist_ok=True)
                        temporary.write_text(
                            json.dumps(
                                dict(
                                    documents=sorted(ids), content=content.model_dump(mode="json")
                                ),
                                ensure_ascii=False,
                            ),
                            encoding="utf-8",
                        )
                        os.replace(temporary, path)
                        self.saved += 1
                    except OSError:
                        logger.warning("study_checkpoint_write_failed")
                    finally:
                        temporary.unlink(missing_ok=True)
        return content
