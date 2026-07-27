# =============================================================================
# 请求上下文测试 —— 验证 HTTP 请求追踪功能
# =============================================================================

"""Tests for request context middleware and request tracing."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from cellwiki.api.request_context import RequestContextMiddleware


def test_request_context_middleware_adds_request_id_header():
    """Verify that RequestContextMiddleware adds X-Request-ID header to responses."""
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    
    @app.get("/test")
    def test_endpoint():
        return {"message": "ok"}
    
    client = TestClient(app)
    response = client.get("/test")
    
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert response.headers["X-Request-ID"].startswith("req_")


def test_request_context_middleware_generates_unique_ids():
    """Verify that each request gets a unique request_id."""
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    
    @app.get("/test")
    def test_endpoint():
        return {"message": "ok"}
    
    client = TestClient(app)
    
    response1 = client.get("/test")
    response2 = client.get("/test")
    
    request_id1 = response1.headers["X-Request-ID"]
    request_id2 = response2.headers["X-Request-ID"]
    
    assert request_id1 != request_id2
