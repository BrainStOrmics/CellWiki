# =============================================================================
# 供应商目录服务测试 —— 目录 CRUD、密钥隔离、legacy 导入与 run 级解析
# =============================================================================
# 契约重点：
# 1. key 永不进入目录文档与 public_view；错误信息可被 scrub_secrets 清洗。
# 2. 目录为空时 resolve() 返回 None（调用方回退 legacy .env 配置链）。
# 3. 首次加载把 legacy 单供应商配置一次性导入为 source=legacy 的 default。
# 4. 悬空 default_selection（供应商/模型被删禁）在加载与更新时被修复/清除。
# =============================================================================

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cellwiki.domain.model_providers import (
    LEGACY_PROVIDER_ID,
    ModelSelection,
    ProviderModel,
)
from cellwiki.services.model_catalog import (
    ModelCatalogError,
    ModelCatalogService,
    ProviderNotFoundError,
)


class FakeSecretEntry:
    """字典版凭据条目替身（CredentialStore 协议）。"""

    def __init__(self, store: dict[str, str], entry: str):
        self._store = store
        self._entry = entry

    def get(self) -> str | None:
        return self._store.get(self._entry)

    def set(self, value: str) -> bool:
        self._store[self._entry] = value
        return True

    def delete(self) -> bool:
        self._store.pop(self._entry, None)
        return True


@pytest.fixture()
def secrets() -> dict[str, str]:
    return {}


@pytest.fixture()
def service(tmp_path: Path, secrets: dict[str, str]) -> ModelCatalogService:
    return ModelCatalogService(
        tmp_path,
        prefer_system_store=True,
        credential_factory=lambda entry: FakeSecretEntry(secrets, entry),
    )


def _provider_kwargs(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "name": "Gateway A",
        "base_url": "https://gw.example.com/v1",
        "protocol": "chat_completions",
        "models": [ProviderModel(id="model-a1"), ProviderModel(id="model-a2")],
    }
    kwargs.update(overrides)
    return kwargs


# ---------------------------------------------------------------------------
# CRUD 与脱敏
# ---------------------------------------------------------------------------
def test_create_and_public_view_hides_key(
    service: ModelCatalogService, secrets: dict[str, str]
) -> None:
    provider = service.create_provider(**_provider_kwargs(), api_key="sk-secret-1234")

    view = service.public_view()
    assert view["default_selection"] is None
    record = view["providers"][0]
    assert record["id"] == provider.id == "gateway-a"
    assert record["api_key_configured"] is True
    assert record["api_key_hint"] == "••••1234"
    assert "sk-secret-1234" not in json.dumps(view, ensure_ascii=False)
    assert secrets[f"provider.{provider.id}"] == "sk-secret-1234"

    catalog_text = service.catalog_path.read_text(encoding="utf-8")
    assert "sk-secret-1234" not in catalog_text


def test_create_rejects_bad_or_duplicate_id(service: ModelCatalogService) -> None:
    service.create_provider(**_provider_kwargs(), provider_id="gateway-a")
    with pytest.raises(ModelCatalogError, match="already exists"):
        service.create_provider(**_provider_kwargs(name="Other"), provider_id="gateway-a")
    with pytest.raises(ModelCatalogError, match="provider id"):
        service.create_provider(**_provider_kwargs(name="Other"), provider_id="Bad Id!")


def test_slugify_from_name(service: ModelCatalogService) -> None:
    provider = service.create_provider(**_provider_kwargs(name="OpenRouter Test"))
    assert provider.id == "openrouter-test"


def test_update_partial_and_key_semantics(service: ModelCatalogService) -> None:
    service.create_provider(
        **_provider_kwargs(), provider_id="gw", api_key="sk-original"
    )

    service.update_provider("gw", name="Gateway Renamed")
    updated = service.update_provider("gw", api_key=None)  # None = 保留已存 key
    assert updated.name == "Gateway Renamed"
    assert service.resolve(ModelSelection(provider_id="gw", model_id="model-a1")) is not None

    service.update_provider("gw", clear_api_key=True)
    spec = service.resolve(ModelSelection(provider_id="gw", model_id="model-a1"))
    assert spec is not None
    assert spec.api_key == ""


def test_delete_clears_default_selection(service: ModelCatalogService) -> None:
    service.create_provider(**_provider_kwargs(), provider_id="gw")
    service.set_default_selection(ModelSelection(provider_id="gw", model_id="model-a1"))
    assert service.public_view()["default_selection"] == {
        "provider_id": "gw",
        "model_id": "model-a1",
    }

    service.delete_provider("gw")
    assert service.public_view()["default_selection"] is None
    assert service.resolve() is None
    with pytest.raises(ProviderNotFoundError):
        service.delete_provider("gw")


def test_disabling_defaulted_model_clears_default(service: ModelCatalogService) -> None:
    service.create_provider(**_provider_kwargs(), provider_id="gw")
    service.set_default_selection(ModelSelection(provider_id="gw", model_id="model-a1"))

    service.update_provider(
        "gw",
        models=[ProviderModel(id="model-a1", enabled=False), ProviderModel(id="model-a2")],
    )
    assert service.public_view()["default_selection"] is None


# ---------------------------------------------------------------------------
# 解析链
# ---------------------------------------------------------------------------
def test_resolve_none_when_catalog_empty(service: ModelCatalogService) -> None:
    assert service.resolve() is None


def test_resolve_explicit_selection_errors(service: ModelCatalogService) -> None:
    service.create_provider(**_provider_kwargs(), provider_id="gw", api_key="sk-1")
    service.create_provider(
        **_provider_kwargs(name="Disabled", enabled=False), provider_id="off", api_key="sk-2"
    )

    with pytest.raises(ProviderNotFoundError):
        service.resolve(ModelSelection(provider_id="missing", model_id="m"))
    with pytest.raises(ModelCatalogError, match="disabled"):
        service.resolve(ModelSelection(provider_id="off", model_id="model-a1"))
    with pytest.raises(ModelCatalogError, match="no model"):
        service.resolve(ModelSelection(provider_id="gw", model_id="nope"))
    with pytest.raises(ModelCatalogError, match="disabled"):
        service.update_provider(
            "gw",
            models=[ProviderModel(id="model-a1", enabled=False), ProviderModel(id="model-a2")],
        )
        service.resolve(ModelSelection(provider_id="gw", model_id="model-a1"))


def test_resolve_without_key_returns_spec_with_empty_key(service: ModelCatalogService) -> None:
    """缺 key 不是解析层错误：构建期（build_model_from_spec）才校验。"""
    service.create_provider(**_provider_kwargs(), provider_id="gw")
    spec = service.resolve(ModelSelection(provider_id="gw", model_id="model-a1"))
    assert spec is not None
    assert spec.api_key == ""


def test_default_selection_validation(service: ModelCatalogService) -> None:
    service.create_provider(**_provider_kwargs(), provider_id="gw")
    with pytest.raises(ModelCatalogError, match="no enabled model"):
        service.set_default_selection(ModelSelection(provider_id="gw", model_id="nope"))
    service.set_default_selection(ModelSelection(provider_id="gw", model_id="model-a2"))
    assert service.public_view()["default_selection"]["model_id"] == "model-a2"


def test_dangling_default_repaired_on_load(
    service: ModelCatalogService, tmp_path: Path
) -> None:
    service.create_provider(**_provider_kwargs(), provider_id="gw")
    service.set_default_selection(ModelSelection(provider_id="gw", model_id="model-a1"))
    document = json.loads(service.catalog_path.read_text(encoding="utf-8"))
    document["providers"] = []  # 模拟外部手改把供应商删掉
    service.catalog_path.write_text(json.dumps(document), encoding="utf-8")

    assert service.resolve() is None
    assert service.public_view()["default_selection"] is None
    assert service.load().providers == []


def test_corrupt_catalog_fails_loudly(service: ModelCatalogService) -> None:
    service.catalog_path.parent.mkdir(parents=True, exist_ok=True)
    service.catalog_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ModelCatalogError, match="invalid"):
        service.public_view()


# ---------------------------------------------------------------------------
# 密钥与清洗
# ---------------------------------------------------------------------------
def test_scrub_secrets_covers_all_providers(service: ModelCatalogService) -> None:
    service.create_provider(**_provider_kwargs(), provider_id="a", api_key="sk-alpha")
    service.create_provider(
        **_provider_kwargs(name="B"), provider_id="b", api_key="sk-beta"
    )
    message = "request to gateway failed with sk-alpha and sk-beta"
    assert service.scrub_secrets(message) == "request to gateway failed with *** and ***"


def test_dev_fallback_writes_keys_file(tmp_path: Path) -> None:
    service = ModelCatalogService(tmp_path, prefer_system_store=False)
    service.create_provider(**_provider_kwargs(), provider_id="gw", api_key="sk-dev")
    assert service.resolve(ModelSelection(provider_id="gw", model_id="model-a1")) is not None
    keys = json.loads(service.keys_path.read_text(encoding="utf-8"))
    assert keys["gw"] == "sk-dev"
    assert "sk-dev" not in service.catalog_path.read_text(encoding="utf-8")

    service.update_provider("gw", clear_api_key=True)
    assert service.keys_path.exists() is False or "gw" not in json.loads(
        service.keys_path.read_text(encoding="utf-8")
    )


# ---------------------------------------------------------------------------
# legacy .env 一次性导入
# ---------------------------------------------------------------------------
def test_legacy_import_creates_default_provider(
    tmp_path: Path, secrets: dict[str, str]
) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=sk-legacy-key",
                "OPENAI_BASE_URL=https://legacy.example.com/v1",
                "OPENAI_MODEL=qwen3.6-plus",
                "OPENAI_API_PROTOCOL=responses",
            ]
        ),
        encoding="utf-8",
    )
    service = ModelCatalogService(
        tmp_path,
        prefer_system_store=True,
        credential_factory=lambda entry: FakeSecretEntry(secrets, entry),
    )

    view = service.public_view()
    assert len(view["providers"]) == 1
    provider = view["providers"][0]
    assert provider["id"] == LEGACY_PROVIDER_ID
    assert provider["source"] == "legacy"
    assert provider["base_url"] == "https://legacy.example.com/v1"
    assert provider["protocol"] == "responses"
    assert [model["id"] for model in provider["models"]] == ["qwen3.6-plus"]
    assert view["default_selection"] == {
        "provider_id": LEGACY_PROVIDER_ID,
        "model_id": "qwen3.6-plus",
    }
    assert secrets[f"provider.{LEGACY_PROVIDER_ID}"] == "sk-legacy-key"
    assert "sk-legacy-key" not in json.dumps(view)

    resolved = service.resolve()
    assert resolved is not None
    assert resolved.model_id == "qwen3.6-plus"
    assert resolved.api_key == "sk-legacy-key"
    assert resolved.protocol == "responses"
    # .env 原样保留（回滚与回退链依赖它）。
    assert "OPENAI_MODEL=qwen3.6-plus" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_legacy_import_skipped_when_env_has_no_model(tmp_path: Path) -> None:
    service = ModelCatalogService(tmp_path, prefer_system_store=False)
    assert service.public_view()["providers"] == []
    assert service.resolve() is None
    assert not service.catalog_path.exists()


def test_deleted_legacy_provider_stays_deleted(
    tmp_path: Path, secrets: dict[str, str]
) -> None:
    (tmp_path / ".env").write_text("OPENAI_MODEL=qwen3.6-plus\n", encoding="utf-8")
    service = ModelCatalogService(
        tmp_path,
        prefer_system_store=True,
        credential_factory=lambda entry: FakeSecretEntry(secrets, entry),
    )
    service.delete_provider(LEGACY_PROVIDER_ID)

    fresh = ModelCatalogService(
        tmp_path,
        prefer_system_store=True,
        credential_factory=lambda entry: FakeSecretEntry(secrets, entry),
    )
    assert fresh.public_view()["providers"] == []
