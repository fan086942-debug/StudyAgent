import json
import logging
import re

from pydantic import ValidationError

from app.core.errors import AppError

logger = logging.getLogger("studyagent")


def usage_of(result):
    value = result.get("usage") or {}
    return (
        {k: v for k, v in value.items() if type(v) is int and v >= 0}
        if isinstance(value, dict)
        else {}
    )


def merge_usage(total, used):
    for key, value in used.items():
        total[key] = total.get(key, 0) + value


def parse_content(content, schema):
    if not isinstance(content, str):
        raise ValueError("missing_content")
    content = content.strip().lstrip("\ufeff")
    fence = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", content, re.I)
    if fence:
        content = fence[1]
    return schema.model_validate_json(content)


def choice_of(result, stage):
    try:
        choice = result["choices"][0]
        if not isinstance(choice.get("message"), dict):
            raise ValueError("invalid message")
    except (KeyError, IndexError, TypeError, AttributeError, ValueError) as exc:
        raise AppError(
            f"{stage}_invalid_output", "模型接口返回的响应结构不完整", 502, usage=usage_of(result)
        ) from exc
    if choice.get("finish_reason") == "length":
        raise AppError(
            f"{stage}_output_truncated",
            "模型输出达到长度上限，本次内容未完成",
            502,
            usage=usage_of(result),
        )
    if choice.get("finish_reason") == "content_filter" or choice["message"].get("refusal"):
        raise AppError(
            f"{stage}_refused", "模型服务拒绝了本次内容请求", 502, usage=usage_of(result)
        )
    return choice


def format_feedback(exc, schema):
    errors = (
        [{"field": ".".join(map(str, e["loc"])), "type": e["type"]} for e in exc.errors()]
        if isinstance(exc, ValidationError)
        else [{"type": "missing_content"}]
    )
    return (
        "上次响应未通过结构校验。只修正输出结构，不增加新事实，不改变引用。返回完整 JSON 对象，不要代码围栏或额外文字。\n"
        + json.dumps(
            dict(errors=errors[:6], output_schema=schema.model_json_schema()), ensure_ascii=False
        )
    )


def log_invalid(stage, choice, exc, usage):
    fields = (
        [{"loc": e["loc"], "type": e["type"]} for e in exc.errors()][:6]
        if isinstance(exc, ValidationError)
        else []
    )
    logger.warning(
        "model_output stage=%s finish=%s chars=%s fields=%s usage=%s",
        stage,
        choice.get("finish_reason"),
        len(choice["message"].get("content") or ""),
        fields,
        usage,
    )
