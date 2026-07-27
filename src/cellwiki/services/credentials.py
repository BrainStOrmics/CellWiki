# =============================================================================
# 凭据适配器 —— 打包桌面应用所需的操作系统凭据管理
# =============================================================================

"""Operating-system credential adapter used by packaged desktop settings."""

from __future__ import annotations

import hashlib
from pathlib import Path


# ---------------------------------------------------------------------------
# CredentialStore —— 凭据存储适配器
# 将项目提供商的密钥存储在宿主机的凭据保管库（如 macOS Keychain、
# Windows Credential Manager）中。keyring 后端在最小化系统上可能不可用，
# 调用者收到布尔结果后可以显式回退到开发 .env 适配器。
# 账户名使用项目路径的 SHA256 哈希，确保不同项目使用不同的凭据条目。
# ---------------------------------------------------------------------------
class CredentialStore:
    """Store one project provider secret in the host credential vault.

    Keyring backends can be unavailable on minimal systems. Callers receive a
    boolean result and may fall back to the development `.env` adapter explicitly.
    """

    # 服务名称，用于在操作系统的凭据管理器中标识条目
    service_name = "org.brainstormics.cellwiki"

    def __init__(self, project_root: Path):
        # 使用项目路径的 SHA256 哈希的前 16 个字符作为账户名
        # 确保不同项目的凭据不会冲突
        digest = hashlib.sha256(str(Path(project_root).resolve()).encode()).hexdigest()[:16]
        self.account = f"project-{digest}-openai"

    # 获取凭据，如果 keyring 不可用则返回 None
    def get(self) -> str | None:
        try:
            import keyring

            return keyring.get_password(self.service_name, self.account)
        except Exception:
            return None

    # 设置凭据，成功返回 True，失败返回 False
    def set(self, value: str) -> bool:
        try:
            import keyring

            keyring.set_password(self.service_name, self.account, value)
            return True
        except Exception:
            return False

    # 删除凭据，成功返回 True，失败返回 False
    def delete(self) -> bool:
        try:
            import keyring
            from keyring.errors import PasswordDeleteError

            try:
                keyring.delete_password(self.service_name, self.account)
            except PasswordDeleteError:
                # 如果凭据不存在也视为成功
                pass
            return True
        except Exception:
            return False

