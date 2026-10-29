from typing import TYPE_CHECKING, AsyncIterator, List

if TYPE_CHECKING:
    from openai.types.chat import ChatCompletionMessageParam

from ..types import ChatMessage, MessageRole


class OpenAIProvider:
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        base_url: str | None = None,
    ) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=60.0)
        self._model = model

    def _build_messages(
        self, messages: List[ChatMessage]
    ) -> list["ChatCompletionMessageParam"]:
        result: list[ChatCompletionMessageParam] = []
        for message in messages:
            if message.role == MessageRole.SYSTEM:
                result.append({"role": "system", "content": message.content})
            elif message.role == MessageRole.USER:
                result.append({"role": "user", "content": message.content})
            else:
                result.append({"role": "assistant", "content": message.content})
        return result

    async def stream(self, messages: List[ChatMessage]) -> AsyncIterator[str]:
        sdk_messages = self._build_messages(messages)

        response = await self._client.chat.completions.create(
            model=self._model, messages=sdk_messages, stream=True
        )

        try:
            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content is not None:
                    yield chunk.choices[0].delta.content
        finally:
            await response.close()

    async def complete(self, messages: List[ChatMessage]) -> str:
        sdk_messages = self._build_messages(messages)

        response = await self._client.chat.completions.create(
            model=self._model, messages=sdk_messages
        )

        content = response.choices[0].message.content
        if content is None:
            raise ValueError("The LLM returned no text response.")
        return content
