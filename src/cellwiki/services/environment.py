# =============================================================================
# 环境设置服务 —— 桌面可编辑的 CellWiki 设置的安全、最小持久化
# =============================================================================

"""Safe, minimal persistence for desktop-editable CellWiki settings."""

from __future__ import annotations

import json
import os
from pathlib import Path
from time import perf_counter
from typing import Any

from cellwiki.domain.model_provider import (
    OPENAI_PROTOCOL_CHAT_COMPLETIONS,
    normalize_openai_protocol,
)
from cellwiki.services.credentials import CredentialStore


# 默认配置值，用于初始化 .env 文件
_DEFAULTS = {
    "OPENAI_API_KEY": "",
    "OPENAI_BASE_URL": "",
    "OPENAI_MODEL": "qwen3.6-plus",
    "OPENAI_API_PROTOCOL": OPENAI_PROTOCOL_CHAT_COMPLETIONS,
    "LOG_LEVEL": "INFO",
    "APP_LANGUAGE": "zh-CN",
    "ENABLE_AGENT_MEMORY": "false",
    "ENABLE_EXTERNAL_RESEARCH": "false",
    "MEMORY_RECALL_TOKEN_BUDGET": "800",
}
# 用户可编辑的配置键
_EDITABLE_KEYS = tuple(_DEFAULTS)
# 运行时使用的完整默认配置（包含运行时专用键）
_RUNTIME_DEFAULTS = {
    **_DEFAULTS,
    "OPENAI_REQUEST_TIMEOUT_SECONDS": "90",
    "INGEST_CHUNK_TIMEOUT_SECONDS": "210",
    "INGEST_MAX_ATTEMPTS": "3",
    "INGEST_MAX_CONCURRENCY": "1",
    "INGEST_MAX_OUTPUT_TOKENS": "5000",
}
_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


# ---------------------------------------------------------------------------
# EnvironmentSettingsService —— 环境设置服务
# 桌面可编辑的 CellWiki 设置的安全、最小持久化。
# 支持编辑 .env 文件中的指定键，同时保留注释和未知值。
# 支持通过操作系统凭据存储（CredentialStore）管理敏感信息（如 API 密钥）。
# ---------------------------------------------------------------------------
class EnvironmentSettingsService:
    """Edit only supported `.env` keys while preserving comments and unknown values."""

    def __init__(
        self,
        project_root: Path,
        *,
        secret_store: CredentialStore | None = None,
        prefer_system_store: bool | None = None,
    ):
        self.env_path = Path(project_root).resolve() / ".env"
        self.prefer_system_store = (
            os.getenv("CELLWIKI_PACKAGED") == "1"
            if prefer_system_store is None
            else prefer_system_store
        )
        self.secret_store = secret_store or (
            CredentialStore(project_root) if self.prefer_system_store else None
        )

    def public_settings(self) -> dict[str, Any]:
        """Return provider settings without ever returning the stored API key."""
        values = self._effective_values()
        api_key = values["OPENAI_API_KEY"]
        return {
            "openai_base_url": values["OPENAI_BASE_URL"],
            "openai_model": values["OPENAI_MODEL"],
            "openai_api_protocol": values["OPENAI_API_PROTOCOL"],
            "openai_api_key_configured": bool(api_key),
            "openai_api_key_hint": self._mask_secret(api_key),
            "secret_storage": "system" if self._system_secret() else "env",
            "log_level": values["LOG_LEVEL"],
            "app_language": values["APP_LANGUAGE"],
            "enable_agent_memory": self._bool(values["ENABLE_AGENT_MEMORY"]),
            "enable_external_research": self._bool(values["ENABLE_EXTERNAL_RESEARCH"]),
            "memory_recall_token_budget": self._integer(
                values["MEMORY_RECALL_TOKEN_BUDGET"], default=800
            ),
        }

    def runtime_environment(self) -> dict[str, str]:
        """Return the project-authoritative environment used to bootstrap a sidecar.

        This internal boundary intentionally includes the provider secret. Callers
        may inject it into a child process but must never serialize it to the UI or
        logs. Explicit defaults prevent a launcher working directory's stale `.env`
        from silently overriding the desktop settings page.
        """

        values = dict(_RUNTIME_DEFAULTS)
        values.update(self._read_values(allowed_keys=frozenset(_RUNTIME_DEFAULTS)))
        system_secret = self._system_secret()
        if system_secret:
            values["OPENAI_API_KEY"] = system_secret
        return values

    def update(
        self,
        *,
        openai_base_url: str,
        openai_model: str,
        openai_api_key: str | None,
        clear_openai_api_key: bool,
        log_level: str,
        app_language: str,
        openai_api_protocol: str | None = None,
        enable_agent_memory: bool = False,
        enable_external_research: bool = False,
        memory_recall_token_budget: int = 800,
    ) -> bool:
        """Persist a validated settings draft and report whether runtime restart is needed."""
        current = self._effective_values()
        normalized = {
            "OPENAI_BASE_URL": self._single_line(openai_base_url.strip(), "base URL"),
            "OPENAI_MODEL": self._single_line(openai_model.strip(), "model"),
            "OPENAI_API_PROTOCOL": (
                current["OPENAI_API_PROTOCOL"]
                if openai_api_protocol is None
                else normalize_openai_protocol(openai_api_protocol)
            ),
            "LOG_LEVEL": log_level.strip().upper(),
            "APP_LANGUAGE": app_language.strip(),
            "ENABLE_AGENT_MEMORY": "true" if enable_agent_memory else "false",
            "ENABLE_EXTERNAL_RESEARCH": "true" if enable_external_research else "false",
            "MEMORY_RECALL_TOKEN_BUDGET": str(memory_recall_token_budget),
        }
        if not normalized["OPENAI_MODEL"]:
            raise ValueError("model name is required")
        if normalized["LOG_LEVEL"] not in _LOG_LEVELS:
            raise ValueError("log level must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
        if normalized["APP_LANGUAGE"] not in {"zh-CN", "en"}:
            raise ValueError("app language must be zh-CN or en")
        if not 128 <= memory_recall_token_budget <= 4000:
            raise ValueError("memory recall token budget must be between 128 and 4000")

        if clear_openai_api_key:
            normalized["OPENAI_API_KEY"] = ""
            if self.secret_store is not None:
                self.secret_store.delete()
        elif openai_api_key is not None and openai_api_key.strip():
            normalized["OPENAI_API_KEY"] = self._single_line(
                openai_api_key.strip(), "API key"
            )
        else:
            # A blank password field means "keep the configured secret", matching desktop settings UX.
            normalized["OPENAI_API_KEY"] = current["OPENAI_API_KEY"]

        # React applies language live; only Python runtime changes require an Agent restart.
        runtime_changed = any(
            current[key] != normalized[key]
            for key in (
                "OPENAI_API_KEY",
                "OPENAI_BASE_URL",
                "OPENAI_MODEL",
                "OPENAI_API_PROTOCOL",
                "LOG_LEVEL",
                "ENABLE_AGENT_MEMORY",
                "ENABLE_EXTERNAL_RESEARCH",
                "MEMORY_RECALL_TOKEN_BUDGET",
            )
        )
        persisted = dict(normalized)
        if (
            self.secret_store is not None
            and normalized["OPENAI_API_KEY"]
            and self.secret_store.set(normalized["OPENAI_API_KEY"])
        ):
            # The runtime still compares the effective secret above, but release
            # configuration never duplicates a vault secret into plaintext `.env`.
            persisted["OPENAI_API_KEY"] = ""
        self._write_values(persisted)
        return runtime_changed

    def test_connection(
        self,
        *,
        openai_base_url: str,
        openai_model: str,
        openai_api_key: str | None,
        openai_api_protocol: str | None = None,
    ) -> dict[str, Any]:
        """Verify the selected protocol and JSON mode without persisting the draft."""
        current = self._effective_values()
        api_key = (openai_api_key or "").strip() or current["OPENAI_API_KEY"]
        base_url = self._single_line(openai_base_url.strip(), "base URL")
        model_name = self._single_line(openai_model.strip(), "model")
        if not api_key:
            raise ValueError("an API key is required before testing the provider")
        if not model_name:
            raise ValueError("model name is required")
        protocol = normalize_openai_protocol(
            openai_api_protocol or current["OPENAI_API_PROTOCOL"]
        )

        started = perf_counter()
        model = None
        try:
            # Import after the sidecar has installed the project-scoped environment;
            # importing Settings at Module load would resurrect stale launcher values.
            from cellwiki.adapters.openai_model import build_openai_chat_model
            from cellwiki.config import Settings

            configuration = Settings(
                _env_file=None,
                openai_api_key=api_key,
                openai_base_url=base_url,
                openai_model=model_name,
                openai_api_protocol=protocol,
                openai_request_timeout_seconds=20,
            )
            model = build_openai_chat_model(
                configuration,
                timeout_seconds=20,
                max_retries=0,
                purpose="structured",
            )
            response = model.invoke(
                "Return only this JSON object: {\"status\":\"CELLWIKI_OK\"}",
                response_format={"type": "json_object"},
                max_completion_tokens=80,
            )
            parsed = json.loads(response.text)
            if parsed != {"status": "CELLWIKI_OK"}:
                raise RuntimeError("provider did not satisfy the CellWiki JSON contract")
        except Exception as error:
            # Provider errors are useful, but a badly behaved SDK must not echo the secret to the UI.
            message = str(error).replace(api_key, "***")
            raise RuntimeError(message[:600]) from None
        finally:
            # The settings page may run this probe repeatedly; each temporary
            # LangChain client owns an HTTP pool that must be released promptly.
            if model is not None:
                model.root_client.close()
        return {
            "ok": True,
            "message": "Provider connection succeeded.",
            "model": model_name,
            "protocol": protocol,
            "structured_output": True,
            "latency_ms": round((perf_counter() - started) * 1000),
        }

    def _effective_values(self) -> dict[str, str]:
        values = dict(_DEFAULTS)
        values.update(self._read_values())
        system_secret = self._system_secret()
        if system_secret:
            values["OPENAI_API_KEY"] = system_secret
        return values

    def _system_secret(self) -> str | None:
        return self.secret_store.get() if self.secret_store is not None else None

    def _read_values(self, *, allowed_keys: frozenset[str] | None = None) -> dict[str, str]:
        if not self.env_path.exists():
            return {}
        allowed = allowed_keys or frozenset(_EDITABLE_KEYS)
        values: dict[str, str] = {}
        for line in self.env_path.read_text(encoding="utf-8").splitlines():
            parsed = self._parse_assignment(line)
            if parsed is None:
                continue
            key, value = parsed
            if key in allowed:
                values[key] = value
        return values

    def _write_values(self, values: dict[str, str]) -> None:
        lines = self.env_path.read_text(encoding="utf-8").splitlines() if self.env_path.exists() else []
        output: list[str] = []
        written: set[str] = set()
        for line in lines:
            parsed = self._parse_assignment(line)
            key = parsed[0] if parsed is not None else None
            if key not in _EDITABLE_KEYS:
                output.append(line)
                continue
            if key in written:
                # Collapse duplicate managed keys so there is one unambiguous runtime value.
                continue
            output.append(f"{key}={self._encode_value(values[key])}")
            written.add(key)

        if output and output[-1] != "":
            output.append("")
        for key in _EDITABLE_KEYS:
            if key not in written:
                output.append(f"{key}={self._encode_value(values[key])}")

        self.env_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.env_path.with_suffix(".env.tmp")
        temporary.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
        temporary.replace(self.env_path)

    @staticmethod
    def _parse_assignment(line: str) -> tuple[str, str] | None:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            return None
        key, raw_value = stripped.split("=", 1)
        key = key.strip()
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            quote = value[0]
            value = value[1:-1]
            if quote == '"':
                value = value.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
        return key, value

    @staticmethod
    def _encode_value(value: str) -> str:
        if not value:
            return ""
        if any(character.isspace() or character in '#"' for character in value):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
            return f'"{escaped}"'
        return value

    @staticmethod
    def _single_line(value: str, label: str) -> str:
        if "\n" in value or "\r" in value:
            raise ValueError(f"{label} must be a single line")
        return value

    @staticmethod
    def _mask_secret(value: str) -> str | None:
        if not value:
            return None
        suffix = value[-4:] if len(value) >= 4 else "configured"
        return f"••••{suffix}"

    @staticmethod
    def _bool(value: str) -> bool:
        return value.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _integer(value: str, *, default: int) -> int:
        try:
            return int(value)
        except ValueError:
            return default
