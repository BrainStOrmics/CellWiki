"""HTTP adapter for the independent annotation evidence capability."""

import hmac
import logging
from typing import Callable

from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from cellwiki.domain.annotation import AnnotationRequest, AnnotationResponse
from cellwiki.services.annotation_support import AnnotationSupportService, AnnotationUnavailable

logger = logging.getLogger(__name__)
ANNOTATION_PATH = "/api/v1/annotation-support"


def error_response(request_id: str | None, code: str, status: int) -> JSONResponse:
    messages = {
        "INVALID_REQUEST": "Invalid annotation request.",
        "UNAUTHORIZED": "A valid annotation service token is required.",
        "SERVICE_DISABLED": "Annotation service token is not configured.",
        "KNOWLEDGE_BUSY": "Knowledge is being updated or awaits approval.",
        "KNOWLEDGE_UNAVAILABLE": "Committed knowledge cannot be reliably queried.",
        "INTERNAL_ERROR": "Annotation service failed.",
    }
    return JSONResponse(
        status_code=status,
        content={"request_id": request_id, "error": {
            "code": code, "message": messages[code], "retryable": status >= 500,
        }},
        headers={"Retry-After": "5"} if code == "KNOWLEDGE_BUSY" else {},
    )


def create_annotation_router(service: AnnotationSupportService, token: str) -> APIRouter:
    class AnnotationRoute(APIRoute):
        def get_route_handler(self) -> Callable:
            handler = super().get_route_handler()

            async def handle(request: Request):
                request_id = None
                if not token:
                    return error_response(None, "SERVICE_DISABLED", 503)
                supplied = request.headers.get("authorization", "").encode("utf-8")
                expected = f"Bearer {token}".encode("utf-8")
                if not hmac.compare_digest(supplied, expected):
                    return error_response(None, "UNAUTHORIZED", 401)
                try:
                    body = await request.body()
                    if len(body) > 64_000:
                        return error_response(None, "INVALID_REQUEST", 400)
                    payload = await request.json()
                    if isinstance(payload, dict):
                        value = payload.get("request_id")
                        if isinstance(value, str) and len(value) <= 128:
                            request_id = value
                    response = await handler(request)
                    logger.info("annotation query completed request_id=%r", request_id)
                    return response
                except (RequestValidationError, ValueError):
                    return error_response(request_id, "INVALID_REQUEST", 400)
                except AnnotationUnavailable as error:
                    return error_response(request_id, error.code, 503)
                except Exception:
                    logger.error("annotation query failed request_id=%r", request_id)
                    return error_response(request_id, "INTERNAL_ERROR", 500)

            return handle

    router = APIRouter(route_class=AnnotationRoute)

    @router.post(ANNOTATION_PATH, response_model=AnnotationResponse)
    def annotation_support(payload: AnnotationRequest) -> AnnotationResponse:
        return service.query(payload)

    return router
