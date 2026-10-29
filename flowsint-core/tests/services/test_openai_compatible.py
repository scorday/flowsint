"""Exercise the real SDK against a deterministic OpenAI-compatible HTTP server."""

import json

import httpx
import pytest
from openai import AsyncOpenAI

from flowsint_core.core.llm import ChatMessage, MessageRole
from flowsint_core.core.llm.providers.openai import OpenAIProvider

MESSAGES = [ChatMessage(role=MessageRole.USER, content="Summarize this investigation")]


@pytest.mark.asyncio
async def test_stream_ignores_reasoning_and_empty_usage_chunks(monkeypatch):
    def handler(request):
        assert str(request.url) == "https://compatible.example/api/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body["model"] == "deepseek/test"
        assert body["stream"] is True
        assert body["messages"] == [{"role": "user", "content": MESSAGES[0].content}]
        chunks = [
            {
                "choices": [
                    {"index": 0, "delta": {"role": "assistant", "content": None}}
                ]
            },
            {
                "choices": [
                    {"index": 0, "delta": {"reasoning_content": "private reasoning"}}
                ]
            },
            {"choices": [{"index": 0, "delta": {"content": "Hello "}}]},
            {"choices": [{"index": 0, "delta": {"content": "world"}}]},
            {"choices": []},
        ]
        data = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=data + "data: [DONE]\n\n",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        real_client = AsyncOpenAI
        monkeypatch.setattr(
            "openai.AsyncOpenAI",
            lambda **kwargs: real_client(**kwargs, http_client=http_client),
        )
        provider = OpenAIProvider(
            api_key="test-key",
            model="deepseek/test",
            base_url="https://compatible.example/api/v1",
        )
        assert [chunk async for chunk in provider.stream(MESSAGES)] == [
            "Hello ",
            "world",
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["name: generated-template", None])
async def test_completion_returns_text_or_rejects_empty_output(monkeypatch, content):
    def handler(request):
        assert json.loads(request.content).get("stream", False) is False
        return httpx.Response(
            200,
            json={
                "id": "completion-test",
                "object": "chat.completion",
                "created": 0,
                "model": "openai/gpt-6-luna",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": content},
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        real_client = AsyncOpenAI
        monkeypatch.setattr(
            "openai.AsyncOpenAI",
            lambda **kwargs: real_client(**kwargs, http_client=http_client),
        )
        provider = OpenAIProvider(
            api_key="test-key",
            model="openai/gpt-6-luna",
            base_url="https://compatible.example/api/v1",
        )
        if content is None:
            with pytest.raises(ValueError, match="no text response"):
                await provider.complete(MESSAGES)
        else:
            assert await provider.complete(MESSAGES) == content
