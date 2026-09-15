"""保留 Chat Completions 流式路径上的非标准推理增量（reasoning_content）。

langchain-openai 只提取 OpenAI 官方字段：第三方网关常用的
``delta.reasoning_content``（DeepSeek、阿里云等）在流式转换里会被丢弃
（``BaseChatOpenAI`` 的类文档明确要求由 provider 子类承担）。运行时的
``_reasoning_text`` 已经认识 ``additional_kwargs.reasoning_content`` 与
``additional_kwargs.reasoning``，所以这里只做一件事：把流式 chunk 上的
非标准推理字段搬回 ``additional_kwargs``。三协议统一逐 token 流式
（design/archive/2026-09-15-three-protocol-token-streaming.md）之后，
chat_completions 的思考增量才不会因为"流式开、字段被丢"而消失。

只影响流式转换：非流式响应走 ``_create_chat_result``，本类不介入。
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from langchain_openai import ChatOpenAI

__all__ = ["REASONING_DELTA_FIELDS", "ChatOpenAIWithReasoningContent"]

# 网关实际出现过的推理字段名；命中即按 reasoning 展示，语义与 responses 路径一致。
REASONING_DELTA_FIELDS = ("reasoning_content", "reasoning")


class ChatOpenAIWithReasoningContent(ChatOpenAI):
    """ChatOpenAI 子类：把非标准推理增量保留到 ``additional_kwargs``。"""

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ) -> ChatGenerationChunk | None:
        generation_chunk = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        if generation_chunk is None:
            return None
        message = generation_chunk.message
        if not isinstance(message, AIMessageChunk):
            return generation_chunk
        for delta in _delta_dicts(chunk):
            for field in REASONING_DELTA_FIELDS:
                value = delta.get(field)
                if isinstance(value, str) and value:
                    message.additional_kwargs[field] = value
        return generation_chunk


def _delta_dicts(chunk: dict) -> list[dict[str, Any]]:
    """Raw ``choices[*].delta`` mappings for both streaming call shapes."""

    nested = chunk.get("chunk")
    choices = chunk.get("choices") or (nested.get("choices") if isinstance(nested, dict) else None) or []
    deltas: list[dict[str, Any]] = []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta")
        if isinstance(delta, dict):
            deltas.append(delta)
    return deltas
