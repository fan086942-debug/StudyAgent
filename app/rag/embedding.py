import hashlib
import math
import re
from typing import Protocol

import httpx

from app.core.config import Settings
from app.core.errors import AppError
from app.llm.compatible_provider import post_json


class EmbeddingProvider(Protocol):
    fingerprint: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def fingerprint(settings: Settings) -> str:
    identity = (
        "demo-hash-v1-2048"
        if settings.study_mode == "demo"
        else f"api|{settings.embedding_base_url}|{settings.embedding_model}|"
        f"{settings.embedding_dimensions}"
    )
    return hashlib.sha256(identity.encode()).hexdigest()[:24]


class DemoEmbedding:
    """仅供演示的字词哈希向量，不具备学习到的语义能力，不会下载模型。"""

    def __init__(self, settings: Settings):
        self.fingerprint = fingerprint(settings)

    def embed(self, texts: list[str]) -> list[list[float]]:
        result = []
        for text in texts:
            words = re.findall(r"[a-z0-9]+\*?|[\u4e00-\u9fff]+", text.lower())
            tokens = []
            for word in words:
                if re.fullmatch(r"[\u4e00-\u9fff]+", word):
                    tokens.extend(word[i : i + 2] for i in range(max(1, len(word) - 1)))
                else:
                    tokens.append(word)
            vector = [0.0] * 2048
            for token in tokens:
                digest = hashlib.sha256(token.encode()).digest()
                index = int.from_bytes(digest[:4], "little") % len(vector)
                vector[index] += 1.0 if digest[4] % 2 else -1.0
            norm = math.sqrt(sum(value * value for value in vector))
            result.append([value / (norm or 1.0) for value in vector])
        return result


class APIEmbedding:
    def __init__(self, settings: Settings, client: httpx.Client):
        self.settings, self.client = settings, client
        self.fingerprint = fingerprint(settings)

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for offset in range(0, len(texts), 16):
            batch = texts[offset : offset + 16]
            data = post_json(
                self.client,
                self.settings.embedding_base_url.rstrip("/") + "/embeddings",
                self.settings.embedding_api_key.get_secret_value(),
                {"model": self.settings.embedding_model, "input": batch},
            )
            try:
                rows = sorted(data["data"], key=lambda row: row["index"])
                if [row["index"] for row in rows] != list(range(len(batch))):
                    raise ValueError("count or order mismatch")
                for row in rows:
                    vector = [float(value) for value in row["embedding"]]
                    if (
                        len(vector) != self.settings.embedding_dimensions
                        or not all(math.isfinite(value) for value in vector)
                        or not any(vector)
                    ):
                        raise ValueError("invalid vector")
                    vectors.append(vector)
            except (KeyError, TypeError, ValueError) as exc:
                raise AppError(
                    "embedding_invalid",
                    "Embedding 数量、维度或数值不合法；请核对 EMBEDDING_DIMENSIONS",
                    502,
                ) from exc
        return vectors
