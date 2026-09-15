from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    study_mode: Literal["demo", "api"] = "demo"
    data_dir: Path = Path("data")
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = ""
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_api_key: SecretStr = SecretStr("")
    embedding_model: str = ""
    embedding_dimensions: int = Field(default=1536, ge=1)
    request_timeout: float = Field(default=60, gt=0)
    max_upload_mb: int = Field(default=25, ge=1, le=200)
    chunk_size: int = Field(default=800, ge=100, le=2000)
    chunk_overlap: int = Field(default=120, ge=0)
    retrieval_candidates: int = Field(default=12, ge=1, le=50)
    retrieval_top_k: int = Field(default=6, ge=1, le=20)
    min_similarity: float = Field(default=0.25, ge=-1, le=1)
    context_char_budget: int = Field(default=9000, ge=1000, le=30000)

    @model_validator(mode="after")
    def validate_settings(self):
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap 必须小于 chunk_size")
        if self.retrieval_top_k > self.retrieval_candidates:
            raise ValueError("top_k 不能超过候选数")
        if self.study_mode == "api" and not all(
            [
                self.llm_api_key.get_secret_value(),
                self.llm_model,
                self.embedding_api_key.get_secret_value(),
                self.embedding_model,
            ]
        ):
            raise ValueError("api 模式需要完整配置 LLM 和 Embedding 的模型与密钥")
        return self
