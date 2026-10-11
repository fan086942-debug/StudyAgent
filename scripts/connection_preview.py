"""Isolated browser acceptance server; uses a simulated model, never external API keys."""

import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn

from app.core.config import Settings
from app.main import create_app


def simulated_model(request):
    body = json.loads(request.content)
    if body.get("tool_choice") != "auto":
        message = {
            "tool_calls": [{"function": {"name": "connection_check", "arguments": '{"ok":true}'}}]
        }
    elif not any(row["role"] == "tool" for row in body["messages"]):
        message = {
            "tool_calls": [
                {
                    "id": "browser-progress",
                    "type": "function",
                    "function": {"name": "get_learning_progress", "arguments": "{}"},
                }
            ]
        }
    else:
        message = {
            "content": json.dumps(
                {"answer": "已查看真实学习记录", "citation_ids": [], "insufficient_evidence": False}
            )
        }
    return httpx.Response(
        200, json={"choices": [{"message": message}], "usage": {"total_tokens": 20}}
    )


def create_preview():
    app = create_app(Settings(_env_file=None, data_dir=Path("data/connection-browser-check")))
    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        async with original(app):
            with httpx.Client(transport=httpx.MockTransport(simulated_model)) as simulated:
                app.state.http = simulated
                # Rebind a saved connection if this acceptance server is restarted.
                app.state.connection.save(app.state.connection.profile)
                yield

    app.router.lifespan_context = lifespan
    return app


if __name__ == "__main__":
    uvicorn.run(create_preview(), host="127.0.0.1", port=8766)
