"""Native Anthropic Messages API model construction for provider catalog entries."""

from __future__ import annotations

from functools import cached_property
from typing import Any, Literal

import anthropic
import httpx
from langchain_anthropic import ChatAnthropic
from pydantic import SecretStr

from cellwiki.domain.model_providers import ResolvedModelSpec

__all__ = [
    "ANTHROPIC_DEFAULT_BASE_URL",
    "ANTHROPIC_VERSION",
    "ChatAnthropicWithRootClient",
    "build_anthropic_model_from_spec",
    "fetch_anthropic_models",
]

ANTHROPIC_DEFAULT_BASE_URL = "https://api.anthropic.com"
# 未显式配置超时时的兜底值（与 build_anthropic_model_from_spec 的默认一致）。
ANTHROPIC_DEFAULT_TIMEOUT_SECONDS = 90.0
# ChatAnthropic 的 SDK 会自行发送该头；只有裸 httpx 拉取 /v1/models 需要手写。
ANTHROPIC_VERSION = "2023-06-01"

# 保留键：provider 身份（key 只许发往所属 base_url）与运行时生命周期
# （超时/重试/流式开关由 run 设置与看门狗拥有）不允许被目录配置覆盖。
_RESERVED_OVERRIDE_KEYS = frozenset(
    {
        "model",
        "model_name",
        "api_key",
        "anthropic_api_key",
        "base_url",
        "anthropic_api_url",
        "timeout",
        "default_request_timeout",
        "max_retries",
        "streaming",
        "disable_streaming",
        "stream_usage",
    }
)
_ANTHROPIC_FIELD_NAMES = frozenset(ChatAnthropic.model_fields)


class ChatAnthropicWithRootClient(ChatAnthropic):
    """ChatAnthropic with the runtime's ``root_client`` handle contract.

    ``agent_runtime`` 的看门狗强制断连与结构化抽取的取消监视都以
    ``model.root_client.close()`` 为契约（ChatOpenAI 自带该属性）。
    ChatAnthropic 没有，这里用 SDK 客户端补上；``getattr`` 兜底逻辑因此
    对两种协议行为一致，而 agent_runtime.py 无需改动。

    连接池必须每个实例独占：``langchain_anthropic._client_utils`` 用
    ``lru_cache`` 按 (base_url, timeout, proxy) 缓存 httpx 客户端，默认所有
    ChatAnthropic 实例共用同一个连接池。运行时的取消与空闲看门狗正是靠
    ``root_client.close()`` 断开挂起的流，一旦共享，一次强制断连会让同进程里
    后续每个 ChatAnthropic 实例的请求都立刻抛
    ``Cannot send a request, as the client has been closed``（2026-09-15
    三协议流式验证实测：一次断连之后所有 anthropic run 全部失败）。这里用
    相同参数自建连接池，断连语义回到"只断开这一个 run"。
    """

    @cached_property
    def _client(self) -> anthropic.Client:
        params = dict(self._client_params)
        timeout = params.pop("timeout", None)
        http_client = anthropic.DefaultHttpxClient(
            base_url=params["base_url"] or ANTHROPIC_DEFAULT_BASE_URL,
            timeout=(
                timeout if timeout is not None else ANTHROPIC_DEFAULT_TIMEOUT_SECONDS
            ),
        )
        return anthropic.Client(http_client=http_client, **params)

    @cached_property
    def _async_client(self) -> anthropic.AsyncClient:
        params = dict(self._client_params)
        timeout = params.pop("timeout", None)
        http_client = anthropic.DefaultAsyncHttpxClient(
            base_url=params["base_url"] or ANTHROPIC_DEFAULT_BASE_URL,
            timeout=(
                timeout if timeout is not None else ANTHROPIC_DEFAULT_TIMEOUT_SECONDS
            ),
        )
        return anthropic.AsyncClient(http_client=http_client, **params)

    @property
    def root_client(self) -> Any:
        return self._client


def build_anthropic_model_from_spec(
    spec: ResolvedModelSpec,
    *,
    timeout_seconds: float | None = None,
    max_retries: int = 1,
    disable_streaming: bool | Literal["tool_calling"] = "tool_calling",
    stream_usage: bool | None = None,
) -> ChatAnthropic:
    """Build one native Anthropic Messages API chat model from a resolved selection.

    ``request_overrides`` 中命中 ChatAnthropic 字段名的键（如 ``thinking``、
    ``max_tokens``、``temperature``）作为构造参数显式传入；其余键经
    ``model_kwargs`` 随请求体下发——语义等价于 OpenAI 路径的 ``extra_body``
    逃生门。保留键（身份/超时/重试/流式）显式拒绝。
    """

    if not spec.api_key:
        raise RuntimeError(f"provider {spec.provider_id} has no API key configured")

    overrides = dict(spec.request_overrides)
    # cache_mode is a CellWiki policy switch, not an Anthropic request field.
    overrides.pop("cache_mode", None)
    reserved = sorted(_RESERVED_OVERRIDE_KEYS & overrides.keys())
    if reserved:
        raise ValueError(
            f"request override {reserved[0]!r} is reserved: provider identity, "
            "timeout, retry, and streaming fields are owned by the runtime"
        )

    options: dict[str, Any] = {
        "model": spec.model_id,
        "api_key": SecretStr(spec.api_key),
        "base_url": spec.base_url or ANTHROPIC_DEFAULT_BASE_URL,
        "temperature": 0,
        # anthropic SDK 的 timeout 是 float（非 httpx.Timeout）；客户端实例
        # 不共享，无需 ChatOpenAI 路径的不可哈希技巧。
        "timeout": float(timeout_seconds or 90.0),
        "max_retries": max_retries,
        "disable_streaming": disable_streaming,
        "stream_usage": stream_usage if stream_usage is not None else True,
    }
    extra_body: dict[str, Any] = {}
    for key, value in overrides.items():
        if key in _ANTHROPIC_FIELD_NAMES:
            options[key] = value
        else:
            extra_body[key] = value
    return ChatAnthropicWithRootClient(**options, model_kwargs=extra_body)


def fetch_anthropic_models(
    base_url: str,
    api_key: str,
    *,
    timeout_seconds: float = 15.0,
) -> list[str]:
    """Fetch the model list from an Anthropic endpoint's ``/v1/models``.

    仅供后端代理调用：key 只随本请求发往该供应商自身的 base_url。base_url
    遵循 SDK 语义（API 根；官方端点可留空取默认值），端点路径为 ``/v1/models``。
    """

    if not api_key:
        raise RuntimeError("an API key is required to fetch models")
    root = (base_url or ANTHROPIC_DEFAULT_BASE_URL).rstrip("/")
    url = f"{root}/v1/models"
    try:
        response = httpx.get(
            url,
            headers={"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION},
            params={"limit": 1000},
            timeout=httpx.Timeout(timeout_seconds),
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as error:
        # 供应商错误可能回显请求头/URL；出栈前把 key 从消息里洗掉。
        raise RuntimeError(str(error).replace(api_key, "***")[:600]) from None
    entries = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        raise RuntimeError("provider returned an unexpected /models payload shape")
    return sorted(
        {
            str(entry.get("id")).strip()
            for entry in entries
            if isinstance(entry, dict) and str(entry.get("id") or "").strip()
        }
    )
