# =============================================================================
# 安全中间件 —— 打包桌面应用的环回 Bearer Token 认证
# =============================================================================
# 开发模式下使用空 token 保持浏览器本地工作流不受限制；
# 打包后的侧车应用始终从 Tauri 接收非空 token，所有数据变更路由
# 都需要 Bearer token 验证。
# =============================================================================

"""Loopback bearer-token enforcement for packaged desktop mutation routes."""

from __future__ import annotations

import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


# ---------------------------------------------------------------------------
# DesktopTokenMiddleware —— 桌面 Token 认证中间件
# 对每个变更型 Product API 请求要求 per-launch token。
# 开发模式使用空 token，因此保留基于浏览器的本地工作流。
# 打包的侧车始终从 Tauri 接收非空 token。
# 使用 hmac.compare_digest 进行常量时间比较，防止时序攻击。
# GET/HEAD/OPTIONS 请求免于认证（只读操作）。
# ---------------------------------------------------------------------------
class DesktopTokenMiddleware(BaseHTTPMiddleware):
    """Require the per-launch token for every mutating Product API request.

    Development keeps an empty token and therefore preserves browser-based local
    workflows. Packaged sidecars always receive a non-empty token from Tauri.
    """

    def __init__(self, app, *, token: str):
        super().__init__(app)
        self.token = token

    async def dispatch(self, request: Request, call_next):
        # 空 token = 开发模式，或只读方法（GET/HEAD/OPTIONS）免认证
        if not self.token or request.method in {"GET", "HEAD", "OPTIONS"}:
            return await call_next(request)
        # 验证 Bearer token
        provided = request.headers.get("authorization", "")
        expected = f"Bearer {self.token}"
        # 使用 hmac.compare_digest 进行常量时间比较，防止时序攻击
        if not hmac.compare_digest(provided, expected):
            return JSONResponse(
                status_code=401,
                content={"detail": "a valid desktop runtime token is required"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)

