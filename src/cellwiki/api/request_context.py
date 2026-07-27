# =============================================================================
# 请求上下文中间件 —— 为每个 HTTP 请求注入追踪 ID
# =============================================================================
# 通过中间件为每个请求生成唯一的 request_id，并绑定到日志上下文，
# 使所有后端日志都能关联到具体的 HTTP 请求。
# =============================================================================

"""Request context middleware for HTTP request tracing.

Generates a unique request_id for each HTTP request and binds it to the
logging context, enabling correlation of backend logs with specific requests.
"""

from __future__ import annotations

import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from cellwiki.services.logging_context import log_context


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Middleware that injects request_id into logging context for each request."""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate a unique request ID
        request_id = f"req_{uuid.uuid4().hex[:12]}"
        
        # Bind request_id to logging context for the duration of this request
        with log_context(request_id=request_id):
            response = await call_next(request)
            # Add request_id to response headers for client-side correlation
            response.headers["X-Request-ID"] = request_id
            return response
