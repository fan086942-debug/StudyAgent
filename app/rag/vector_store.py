import chromadb
from chromadb.config import Settings as ChromaSettings

from app.core.config import Settings
from app.core.errors import AppError


class VectorStore:
    def __init__(self, settings: Settings, fingerprint: str):
        self.client = chromadb.PersistentClient(
            path=str(settings.data_dir / "chroma"),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name="chunks-" + fingerprint,
            embedding_function=None,
            configuration={"hnsw": {"space": "cosine"}},
        )

    def delete_document(self, document_id: str):
        try:
            self.collection.delete(where={"document_id": document_id})
        except Exception as exc:
            raise AppError("index_failed", "向量索引清理失败，请重试", 503) from exc

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
