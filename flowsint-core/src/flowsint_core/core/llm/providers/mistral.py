from typing import TYPE_CHECKING, AsyncIterator, List

if TYPE_CHECKING:
    from mistralai.models import (
        AssistantMessage,
        SystemMessage,
        ToolMessage,
        UserMessage,
    )

from ..types import ChatMessage, MessageRole

_ROLE_MAP = {
    MessageRole.SYSTEM: "SystemMessage",
    MessageRole.USER: "UserMessage",
    MessageRole.ASSISTANT: "AssistantMessage",
}


class MistralProvider:
    def __init__(self, api_key: str, model: str = "mistral-small-latest"):
        from mistralai import Mistral

        self._client = Mistral(api_key=api_key)
        self._model = model

    def _build_messages(
        self, messages: List[ChatMessage]
    ) -> list["SystemMessage | UserMessage | AssistantMessage | ToolMessage"]:
        from mistralai.models import AssistantMessage, SystemMessage, UserMessage

        result: list[SystemMessage | UserMessage | AssistantMessage | ToolMessage] = []
        for message in messages:
            if message.role == MessageRole.SYSTEM:
                result.append(SystemMessage(content=message.content))
            elif message.role == MessageRole.USER:
                result.append(UserMessage(content=message.content))
            else:
                result.append(AssistantMessage(content=message.content))
        return result

    async def stream(self, messages: List[ChatMessage]) -> AsyncIterator[str]:
        sdk_messages = self._build_messages(messages)

        response = await self._client.chat.stream_async(
            model=self._model, messages=sdk_messages
        )

        async for chunk in response:
            if chunk.data.choices[0].delta.content is not None:
                yield chunk.data.choices[0].delta.content

    async def complete(self, messages: List[ChatMessage]) -> str:
        sdk_messages = self._build_messages(messages)

        response = await self._client.chat.complete_async(
            model=self._model, messages=sdk_messages
        )

        content = response.choices[0].message.content
        if not isinstance(content, str):
            raise ValueError("The LLM returned no text response.")
        return content
