from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class ConnectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["demo", "api"] = "api"
    base_url: str = Field(default="https://api.openai.com/v1", max_length=500)
    model: str = Field(default="", max_length=160)
    api_key: SecretStr = SecretStr("")

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("请填写 HTTP(S) 接口根地址，不包含密钥、查询参数或账号")
        # Reading port also validates malformed ports.
        _ = parsed.port
        return value

    @field_validator("model")
    @classmethod
    def trim_model(cls, value: str) -> str:
        return value.strip()

    @field_validator("api_key")
    @classmethod
    def valid_key(cls, value: SecretStr) -> SecretStr:
        key = value.get_secret_value().strip()
        if len(key) > 4096 or any(ord(char) < 32 for char in key):
            raise ValueError("密钥格式不合法")
        return SecretStr(key)
