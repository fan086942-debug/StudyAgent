from threading import RLock

from app.core.config import Settings
from app.core.errors import AppError


class VectorStore:
    def __init__(self, settings: Settings, fingerprint: str):
        self.settings, self.fingerprint = settings, fingerprint
        self._client = self._collection = None
        self._lock = RLock()

    @property
    def client(self):
        with self._lock:
            if self._client is None:
                import chromadb
                from chromadb.config import Settings as ChromaSettings

                self._client = chromadb.PersistentClient(
                    path=str(self.settings.data_dir / "chroma"),
                    settings=ChromaSettings(anonymized_telemetry=False),
                )
            return self._client

    @property
    def collection(self):
        with self._lock:
            if self._collection is None:
                self._collection = self.client.get_or_create_collection(
                    name="chunks-" + self.fingerprint,
                    embedding_function=None,
                    configuration={"hnsw": {"space": "cosine"}},
                )
            return self._collection

    def close(self):
        # Closing an unused store must not import or initialize Chroma.
        with self._lock:
            if self._client is not None:
                self._client.close()
                self._client = self._collection = None

    def delete_document(self, document_id: str):
        try:
            self.collection.delete(where={"document_id": document_id})
        except Exception as exc:
            raise AppError("index_failed", "向量索引清理失败，请重试", 503) from exc

    def delete_document_everywhere(self, document_id: str):
        """Remove a document from current and previous embedding collections."""
        try:
            for collection in self.client.list_collections():
                if collection.name.startswith("chunks-"):
                    self.client.get_collection(collection.name, embedding_function=None).delete(
                        where={"document_id": document_id}
                    )
        except Exception as exc:
            raise AppError("index_failed", "向量索引清理失败，请重试删除", 503) from exc

    # 将embedinig向量和chunk存入向量索引
    def add(self, chunks, vectors):
        try:
            for start in range(0, len(chunks), 100):
                batch = chunks[start : start + 100]
                self.collection.upsert(
                    ids=[chunk.id for chunk in batch],
                    embeddings=vectors[start : start + 100],
                    metadatas=[
                        {"course_id": chunk.course_id, "document_id": chunk.document_id}
                        for chunk in batch
                    ],
                )
        except Exception as exc:
            raise AppError("index_failed", "向量索引写入失败，请重试", 503) from exc

    def search(self, vector: list[float], course_id: str, document_ids: list[str], count: int):
        if not document_ids:
            return []
        try:
            result = self.collection.query(
                query_embeddings=[vector],
                n_results=count,
                where={"$and": [{"course_id": course_id}, {"document_id": {"$in": document_ids}}]},
                include=["distances"],
            )
            return list(zip(result["ids"][0], result["distances"][0], strict=True))
        except Exception as exc:
            raise AppError("index_unavailable", "向量查询失败，请检查索引或重建资料", 503) from exc
