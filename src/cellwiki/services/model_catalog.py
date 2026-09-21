# =============================================================================
# 供应商目录服务 —— 多供应商模型配置的持久化、密钥解析与 run 级选择
# =============================================================================
# 目录文档（非密钥）落在 <settings_root>/data/runtime/model_providers.json，
# 与 .env 同一根（跟随 EnvironmentSettingsService 的 settings root 语义）。
# 密钥永不入目录文档：打包环境逐供应商进系统凭据库（CredentialStore
# 多条目），开发环境回落 data/runtime/model_provider_keys.json（gitignored，
# 与开发态 .env 明文同级，不降低现状安全水位）。
# 首次加载且目录文件不存在时，把 legacy .env 单供应商配置一次性导入为
# source=legacy 的 "default" 供应商；目录为空时运行时回退 legacy 配置链，
# e2e / 测试 / 既有桌面流程因此零改动。
# =============================================================================

"""Provider catalog persistence, secret resolution, and run-level model selection."""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Callable, Protocol

from cellwiki.domain.model_providers import (
    LEGACY_PROVIDER_ID,
    PROVIDER_ID_PATTERN,
    ModelSelection,
    ProviderCatalog,
    ProviderConfig,
    ProviderModel,
    ResolvedModelSpec,
)
from cellwiki.domain.model_provider import WIRE_PROTOCOL_ANTHROPIC
from cellwiki.services.credentials import CredentialStore
from cellwiki.services.environment import EnvironmentSettingsService


class ModelCatalogError(ValueError):
    """目录校验或解析失败；API 层映射为 422。"""


class ProviderNotFoundError(ModelCatalogError):
    """选择或操作引用了不存在的供应商；API 层映射为 404。"""


def _optional_positive_int(value: object, *, label: str) -> int | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = int(raw)
    except ValueError as error:
        raise ModelCatalogError(f"{label} must be an integer") from error
    if parsed <= 0:
        raise ModelCatalogError(f"{label} must be positive")
    return parsed


# 密钥条目协议：CredentialStore 与测试替身都满足该形状（结构化类型）。
class _SecretEntry(Protocol):
    def get(self) -> str | None: ...

    def set(self, value: str) -> bool: ...

    def delete(self) -> bool: ...


class ModelCatalogService:
    """Load/save the provider catalog and resolve run-level model selections."""

    def __init__(
        self,
        settings_root: Path,
        *,
        prefer_system_store: bool | None = None,
        credential_factory: Callable[[str], _SecretEntry] | None = None,
    ):
        self.root = Path(settings_root).resolve()
        self.catalog_path = self.root / "data" / "runtime" / "model_providers.json"
        # 开发态密钥回落文件；打包态走凭据库。两者都不进 git。
        self.keys_path = self.root / "data" / "runtime" / "model_provider_keys.json"
        self.prefer_system_store = (
            os.getenv("CELLWIKI_PACKAGED") == "1"
            if prefer_system_store is None
            else prefer_system_store
        )
        self._credential_factory = credential_factory or (
            lambda entry: CredentialStore(self.root, entry=entry)
        )
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # 加载 / 保存
    # ------------------------------------------------------------------
    def load(self) -> ProviderCatalog:
        """Load the catalog, importing legacy `.env` config on first use."""
        with self._lock:
            return self._load_locked()

    def _load_locked(self) -> ProviderCatalog:
        if not self.catalog_path.exists():
            imported = self._import_legacy_locked()
            if imported is not None:
                self._save_locked(imported)
                return imported
            return ProviderCatalog()
        try:
            document = json.loads(self.catalog_path.read_text(encoding="utf-8"))
            catalog = ProviderCatalog.model_validate(document)
        except ModelCatalogError:
            raise
        except Exception as error:
            # 用户手工编辑损坏：显式失败优于静默清空（目录含全部供应商配置）。
            raise ModelCatalogError(
                f"model provider catalog at {self.catalog_path} is invalid: {error}"
            ) from None
        return self._repair_locked(catalog)

    def _repair_locked(self, catalog: ProviderCatalog) -> ProviderCatalog:
        """语义修复：悬空的 default_selection 指向已不存在的供应商/模型时清除。"""
        selection = catalog.default_selection
        if selection is None:
            return catalog
        provider = self._find_provider(catalog, selection.provider_id)
        model_ok = provider is not None and any(
            model.id == selection.model_id for model in provider.models
        )
        if provider is not None and model_ok:
            return catalog
        return catalog.model_copy(update={"default_selection": None})

    def _save_locked(self, catalog: ProviderCatalog) -> None:
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
        payload = catalog.model_dump(mode="json")
        temporary = self.catalog_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(self.catalog_path)

    def _import_legacy_locked(self) -> ProviderCatalog | None:
        """One-time import of the legacy single-provider `.env` configuration."""
        environment = EnvironmentSettingsService(self.root)
        snapshot = environment.provider_import_snapshot()
        model = (snapshot.get("model") or "").strip()
        if not model:
            return None
        provider = ProviderConfig(
            id=LEGACY_PROVIDER_ID,
            name="默认供应商",
            base_url=snapshot.get("base_url", ""),
            protocol=snapshot.get("protocol") or "chat_completions",
            enabled=True,
            models=[
                ProviderModel(
                    id=model,
                    max_input_tokens=_optional_positive_int(
                        snapshot.get("max_input_tokens", ""),
                        label="OPENAI_MAX_INPUT_TOKENS",
                    ),
                )
            ],
            source="legacy",
        )
        api_key = (snapshot.get("api_key") or "").strip()
        if api_key:
            self._write_secret(LEGACY_PROVIDER_ID, api_key)
        return ProviderCatalog(
            default_selection=ModelSelection(
                provider_id=LEGACY_PROVIDER_ID, model_id=model
            ),
            providers=[provider],
        )

    # ------------------------------------------------------------------
    # 密钥（永不进入目录文档与 API 响应）
    # ------------------------------------------------------------------
    def _credential(self, provider_id: str) -> _SecretEntry | None:
        return (
            self._credential_factory(f"provider.{provider_id}")
            if self.prefer_system_store
            else None
        )

    def _read_secret(self, provider_id: str) -> str | None:
        store = self._credential(provider_id)
        if store is not None:
            value = store.get()
            if value:
                return value
        if self.keys_path.exists():
            try:
                keys = json.loads(self.keys_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
            value = keys.get(provider_id)
            if isinstance(value, str) and value:
                return value
        return None

    def _write_secret(self, provider_id: str, value: str) -> None:
        store = self._credential(provider_id)
        if store is not None and store.set(value):
            return
        self.keys_path.parent.mkdir(parents=True, exist_ok=True)
        keys: dict[str, Any] = {}
        if self.keys_path.exists():
            try:
                keys = json.loads(self.keys_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                keys = {}
        keys[provider_id] = value
        temporary = self.keys_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(keys, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.keys_path)

    def _delete_secret(self, provider_id: str) -> None:
        store = self._credential(provider_id)
        if store is not None:
            store.delete()
        if self.keys_path.exists():
            try:
                keys = json.loads(self.keys_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return
            if provider_id in keys:
                keys.pop(provider_id)
                temporary = self.keys_path.with_suffix(".json.tmp")
                temporary.write_text(
                    json.dumps(keys, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                temporary.replace(self.keys_path)

    # ------------------------------------------------------------------
    # 公共视图（脱敏）
    # ------------------------------------------------------------------
    def public_view(self) -> dict[str, Any]:
        """Sanitized catalog for the UI: never includes key material."""
        with self._lock:
            catalog = self._load_locked()
            providers = []
            for provider in catalog.providers:
                key = self._read_secret(provider.id)
                providers.append(
                    {
                        **provider.model_dump(mode="json"),
                        "api_key_configured": bool(key),
                        "api_key_hint": self._mask_secret(key),
                    }
                )
            selection = catalog.default_selection
            return {
                "version": catalog.version,
                "default_selection": (
                    selection.model_dump(mode="json") if selection else None
                ),
                "providers": providers,
            }

    @staticmethod
    def _mask_secret(value: str | None) -> str | None:
        if not value:
            return None
        suffix = value[-4:] if len(value) >= 4 else "configured"
        return f"••••{suffix}"

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def create_provider(
        self,
        *,
        name: str,
        base_url: str = "",
        protocol: str = "chat_completions",
        models: list[ProviderModel] | None = None,
        api_key: str | None = None,
        enabled: bool = True,
        request_overrides: dict[str, Any] | None = None,
        provider_id: str | None = None,
    ) -> ProviderConfig:
        with self._lock:
            catalog = self._load_locked()
            provider_id = provider_id or self._slugify(name)
            if not PROVIDER_ID_PATTERN.fullmatch(provider_id):
                raise ModelCatalogError(
                    "provider id must match ^[a-z0-9][a-z0-9._-]{0,63}$"
                )
            if any(provider.id == provider_id for provider in catalog.providers):
                raise ModelCatalogError(f"provider id already exists: {provider_id}")
            provider = ProviderConfig(
                id=provider_id,
                name=name,
                base_url=base_url,
                protocol=protocol,
                enabled=enabled,
                models=list(models or []),
                request_overrides=dict(request_overrides or {}),
                source="user",
            )
            updated = catalog.model_copy(
                update={"providers": [*catalog.providers, provider]}
            )
            self._save_locked(updated)
            if api_key and api_key.strip():
                self._write_secret(provider_id, api_key.strip())
            return provider

    def update_provider(
        self,
        provider_id: str,
        *,
        name: str | None = None,
        base_url: str | None = None,
        protocol: str | None = None,
        models: list[ProviderModel] | None = None,
        api_key: str | None = None,
        clear_api_key: bool = False,
        enabled: bool | None = None,
        request_overrides: dict[str, Any] | None = None,
    ) -> ProviderConfig:
        """Partial update; `api_key=None` keeps the stored secret.

        禁用供应商或模型时，若 default_selection 指向被禁对象则一并清除，
        避免 run 解析落在不可用配置上。
        """
        with self._lock:
            catalog = self._load_locked()
            provider = self._require_provider(catalog, provider_id)
            updates: dict[str, Any] = {}
            if name is not None:
                updates["name"] = name
            if base_url is not None:
                updates["base_url"] = base_url
            if protocol is not None:
                updates["protocol"] = protocol
            if models is not None:
                updates["models"] = list(models)
            if enabled is not None:
                updates["enabled"] = enabled
            if request_overrides is not None:
                updates["request_overrides"] = dict(request_overrides)
            updated_provider = provider.model_copy(update=updates)
            replaced = [
                updated_provider if item.id == provider_id else item
                for item in catalog.providers
            ]
            selection = catalog.default_selection
            if selection is not None and selection.provider_id == provider_id:
                disabled = updated_provider.enabled is False or not any(
                    model.id == selection.model_id and model.enabled
                    for model in updated_provider.models
                )
                if disabled:
                    selection = None
            updated_catalog = catalog.model_copy(
                update={"providers": replaced, "default_selection": selection}
            )
            # 重校验（frozen 合约在 model_copy 后仍需整体一致：模型 id 唯一等）。
            updated_catalog = ProviderCatalog.model_validate(updated_catalog.model_dump())
            self._save_locked(updated_catalog)
            if clear_api_key:
                self._delete_secret(provider_id)
            elif api_key is not None and api_key.strip():
                self._write_secret(provider_id, api_key.strip())
            return updated_provider

    def delete_provider(self, provider_id: str) -> None:
        with self._lock:
            catalog = self._load_locked()
            self._require_provider(catalog, provider_id)
            remaining = [item for item in catalog.providers if item.id != provider_id]
            selection = catalog.default_selection
            if selection is not None and selection.provider_id == provider_id:
                selection = None
            self._save_locked(
                catalog.model_copy(
                    update={"providers": remaining, "default_selection": selection}
                )
            )
            self._delete_secret(provider_id)

    def set_default_selection(self, selection: ModelSelection | None) -> None:
        """设置（或清除）默认选择；非空时必须指向启用中的供应商与模型。"""
        with self._lock:
            catalog = self._load_locked()
            if selection is not None:
                provider = self._require_provider(catalog, selection.provider_id)
                if not provider.enabled:
                    raise ModelCatalogError(
                        f"provider {provider.id} is disabled and cannot be the default"
                    )
                if not any(
                    model.id == selection.model_id and model.enabled
                    for model in provider.models
                ):
                    raise ModelCatalogError(
                        f"provider {provider.id} has no enabled model {selection.model_id!r}"
                    )
            self._save_locked(catalog.model_copy(update={"default_selection": selection}))

    # ------------------------------------------------------------------
    # run 级解析
    # ------------------------------------------------------------------
    def resolve(self, selection: ModelSelection | None = None) -> ResolvedModelSpec | None:
        """解析一次模型选择为构建输入；无默认且无显式选择时返回 None（legacy 链）。

        显式选择或已配置的默认选择指向缺失/禁用的供应商或模型（结构性错误）时
        抛错——静默回退 legacy 会掩盖坏选择。**缺 API key 不在这里拦截**：
        协议型注入环境（e2e、评测）的 run 不构建真实模型，key 在构建期由
        ``build_model_from_spec`` 校验——与 legacy 链缺 key 时 run 失败的既有
        契约一致。
        """
        with self._lock:
            catalog = self._load_locked()
            explicit = selection is not None
            effective = selection or catalog.default_selection
            if effective is None:
                return None
            provider = self._find_provider(catalog, effective.provider_id)
            if provider is None:
                if explicit:
                    raise ProviderNotFoundError(
                        f"provider {effective.provider_id!r} is not configured"
                    )
                return None  # 悬空默认已被 _repair_locked 清理；防御性兜底。
            if not provider.enabled:
                raise ModelCatalogError(f"provider {provider.id} is disabled")
            model = next(
                (item for item in provider.models if item.id == effective.model_id),
                None,
            )
            if model is None:
                raise ModelCatalogError(
                    f"provider {provider.id} has no model {effective.model_id!r}"
                )
            if not model.enabled:
                raise ModelCatalogError(
                    f"model {effective.model_id!r} of provider {provider.id} is disabled"
                )
            return ResolvedModelSpec(
                provider_id=provider.id,
                model_id=model.id,
                base_url=provider.base_url,
                protocol=provider.protocol,
                api_key=self._read_secret(provider.id) or "",
                request_overrides=dict(provider.request_overrides),
                max_input_tokens=model.max_input_tokens,
            )

    def scrub_secrets(self, message: str) -> str:
        """把所有已配置供应商的 key 从错误信息中替换为 ***。"""
        with self._lock:
            catalog = self._load_locked()
            scrubbed = message
            for provider in catalog.providers:
                key = self._read_secret(provider.id)
                if key:
                    scrubbed = scrubbed.replace(key, "***")
            return scrubbed

    def fetch_models(self, provider_id: str) -> list[str]:
        """后端代理拉取供应商 /models 清单；key 只发往该供应商自己的 base_url。

        Anthropic 供应商允许空 base_url——SDK 语义为官方默认端点
        （``https://api.anthropic.com``），拉取路径为 ``/v1/models``。
        """
        with self._lock:
            provider = self._require_provider(self._load_locked(), provider_id)
            api_key = self._read_secret(provider_id) or ""
        if not provider.base_url and provider.protocol != WIRE_PROTOCOL_ANTHROPIC:
            raise ModelCatalogError(
                "a base URL is required before fetching the model list"
            )
        if not api_key:
            raise ModelCatalogError(
                f"provider {provider_id} has no API key configured"
            )
        # 延迟导入：adapters 依赖 config 单例，避免服务模块加载顺序耦合。
        from cellwiki.adapters.openai_model import fetch_provider_models

        try:
            return fetch_provider_models(
                provider.base_url, api_key, protocol=provider.protocol
            )
        except Exception as error:
            message = self.scrub_secrets(str(error))
            raise ModelCatalogError(message[:600]) from None

    def fetch_models_draft(
        self, *, base_url: str, protocol: str, api_key: str
    ) -> list[str]:
        """后端代理拉取"未保存供应商草稿"的 /models 清单。

        与 ``fetch_models`` 同安全合同：key 只随本次请求发往草稿自己的
        base_url、错误清洗；不读不写目录与密钥存储。草稿字段复用
        ProviderConfig 的域校验（协议枚举、base_url 形状；Anthropic
        允许空 base_url 取官方默认端点）。
        """
        api_key = (api_key or "").strip()
        if not api_key:
            raise ModelCatalogError(
                "an API key is required before fetching the model list"
            )
        provider = ProviderConfig(
            id="draft", name="Draft", base_url=base_url, protocol=protocol
        )
        if not provider.base_url and provider.protocol != WIRE_PROTOCOL_ANTHROPIC:
            raise ModelCatalogError(
                "a base URL is required before fetching the model list"
            )
        # 延迟导入：adapters 依赖 config 单例，避免服务模块加载顺序耦合。
        from cellwiki.adapters.openai_model import fetch_provider_models

        try:
            return fetch_provider_models(
                provider.base_url, api_key, protocol=provider.protocol
            )
        except Exception as error:
            # scrub_secrets 只认识已存密钥；草稿 key 需额外清洗。
            message = self.scrub_secrets(str(error)).replace(api_key, "***")
            raise ModelCatalogError(message[:600]) from None

    def test_provider(
        self, provider_id: str, *, model_id: str | None = None
    ) -> dict[str, Any]:
        """对该供应商已存配置做一次受限连接探测（不持久化、不改状态）。

        key 取自目录密钥存储；缺省探测第一个启用的模型。
        """
        with self._lock:
            provider = self._require_provider(self._load_locked(), provider_id)
            api_key = self._read_secret(provider_id) or ""
        if not api_key:
            raise ModelCatalogError(f"provider {provider_id} has no API key configured")
        if model_id:
            # 点名测哪个就测哪个，不静默换成别的模型：结果会挂在那一行下面，
            # 换成别的模型报的是另一件事的成败。
            model = next((item for item in provider.models if item.id == model_id), None)
            if model is None or not model.enabled:
                raise ModelCatalogError(
                    f"provider {provider_id} has no saved enabled model {model_id};"
                    " save the provider first"
                )
        else:
            model = next((item for item in provider.models if item.enabled), None)
            if model is None:
                raise ModelCatalogError(
                    f"provider {provider_id} has no enabled model to test"
                )
        environment = EnvironmentSettingsService(self.root)
        return environment.test_connection(
            openai_base_url=provider.base_url,
            openai_model=model.id,
            openai_api_key=api_key,
            openai_api_protocol=provider.protocol,
        )

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    @staticmethod
    def _find_provider(catalog: ProviderCatalog, provider_id: str) -> ProviderConfig | None:
        return next(
            (item for item in catalog.providers if item.id == provider_id), None
        )

    def _require_provider(self, catalog: ProviderCatalog, provider_id: str) -> ProviderConfig:
        provider = self._find_provider(catalog, provider_id)
        if provider is None:
            raise ProviderNotFoundError(f"provider {provider_id!r} is not configured")
        return provider

    @staticmethod
    def _slugify(name: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
        slug = slug[:63].strip("-")
        if not slug:
            return "provider"
        if not slug[0].isalnum():
            slug = f"p-{slug}"
        return slug[:63]
