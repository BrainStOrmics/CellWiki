# =============================================================================
# 供应商目录合约 —— 多供应商模型配置与 run 级模型选择
# =============================================================================
# 设置页可配置 n 个供应商（每个含 base_url / 协议 / n 个模型），运行时按
# run 解析“当前模型”。密钥永不落在本文件描述的目录文档里：打包环境逐
# 供应商存系统凭据库，开发环境存运行时密钥文件（见
# services/model_catalog.py）。ResolvedModelSpec 持有明文 key，只允许在
# 进程内传给模型工厂，禁止持久化或序列化到任何 API 响应/日志。
# =============================================================================

"""Provider catalog contracts for multi-provider model selection."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator

from cellwiki.domain.contracts import ContractModel
from cellwiki.domain.model_provider import (
    WIRE_PROTOCOL_CHAT_COMPLETIONS,
    normalize_wire_protocol,
)

# 供应商 id：小写 slug（凭据库条目名 + API 路径段），不允许路径分隔符。
PROVIDER_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

# legacy .env 单供应商导入的固定 id；目录为空时运行时仍回退 legacy 配置链。
LEGACY_PROVIDER_ID = "default"

CATALOG_VERSION = 1


class ProviderModel(ContractModel):
    """供应商目录里的一个可调用模型。"""

    id: str                          # wire 模型名（请求里发送的 model 值）
    display_name: str | None = None  # 展示名；缺省用 id
    enabled: bool = True
    # Provider-declared maximum input capacity. None means "not declared";
    # prompt budgeting then uses one conservative fallback, never model-name
    # inference. The UI exposes this field so users can replace the fallback.
    max_input_tokens: int | None = Field(default=None, ge=8_000, le=2_000_000)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped or "\n" in stripped or "\r" in stripped:
            raise ValueError("model id must be a non-empty single line")
        if len(stripped) > 300:
            raise ValueError("model id must be at most 300 characters")
        return stripped

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped or "\n" in stripped or "\r" in stripped:
            raise ValueError("display name must be a non-empty single line")
        if len(stripped) > 120:
            raise ValueError("display name must be at most 120 characters")
        return stripped


class ProviderConfig(ContractModel):
    """一个模型供应商及其模型清单（不含密钥）。"""

    id: str
    name: str
    base_url: str = ""               # 空 = 使用 SDK 默认端点
    protocol: str = WIRE_PROTOCOL_CHAT_COMPLETIONS
    enabled: bool = True
    models: list[ProviderModel] = Field(default_factory=list)
    request_overrides: dict[str, Any] = Field(default_factory=dict)
    source: str = "user"             # user | legacy（.env 导入）

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not PROVIDER_ID_PATTERN.fullmatch(value):
            raise ValueError(
                "provider id must match ^[a-z0-9][a-z0-9._-]{0,63}$"
            )
        return value

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped or "\n" in stripped or "\r" in stripped:
            raise ValueError("provider name must be a non-empty single line")
        if len(stripped) > 120:
            raise ValueError("provider name must be at most 120 characters")
        return stripped

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            return ""
        if any(character.isspace() for character in stripped):
            raise ValueError("base URL must not contain whitespace")
        parsed = urlparse(stripped)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base URL must be an absolute http(s) URL")
        return stripped

    @field_validator("protocol")
    @classmethod
    def validate_protocol(cls, value: str) -> str:
        return normalize_wire_protocol(value)

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        if value not in {"user", "legacy"}:
            raise ValueError("provider source must be user or legacy")
        return value

    @field_validator("request_overrides")
    @classmethod
    def validate_request_overrides(cls, value: dict[str, Any]) -> dict[str, Any]:
        for key, item in value.items():
            if not key.strip():
                raise ValueError("request override keys must be non-empty")
            try:
                json.dumps(item)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"request override {key!r} must be JSON-serializable"
                ) from error
        return value

    @model_validator(mode="after")
    def validate_unique_models(self) -> "ProviderConfig":
        ids = [model.id for model in self.models]
        if len(ids) != len(set(ids)):
            raise ValueError("model ids must be unique within a provider")
        return self


class ModelSelection(ContractModel):
    """一次模型选择：供应商 id + 模型 id。"""

    provider_id: str
    model_id: str


class ProviderCatalog(ContractModel):
    """目录磁盘文档（非密钥）：data/runtime/model_providers.json 的形状。"""

    version: int = CATALOG_VERSION
    default_selection: ModelSelection | None = None
    providers: list[ProviderConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_providers(self) -> "ProviderCatalog":
        ids = [provider.id for provider in self.providers]
        if len(ids) != len(set(ids)):
            raise ValueError("provider ids must be unique in the catalog")
        return self


@dataclass(frozen=True)
class ResolvedModelSpec:
    """一次 run 完整解析出的模型构建输入。

    持有明文 API key：仅供模型工厂在进程内消费，禁止持久化、打印或进入
    API 响应。repr 已脱敏，防止误入日志。
    """

    provider_id: str
    model_id: str
    base_url: str
    protocol: str
    api_key: str
    request_overrides: dict[str, Any]
    max_input_tokens: int | None = None

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"ResolvedModelSpec(provider_id={self.provider_id!r}, "
            f"model_id={self.model_id!r}, base_url={self.base_url!r}, "
            f"protocol={self.protocol!r}, api_key=***, "
            f"request_overrides={list(self.request_overrides)!r}, "
            f"max_input_tokens={self.max_input_tokens!r})"
        )
