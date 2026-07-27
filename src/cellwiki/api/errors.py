# =============================================================================
# 错误报告 API —— 接收和持久化前端错误报告
# =============================================================================
# 提供 POST /api/errors 端点接收前端错误报告，并将其持久化到
# data/runtime/errors/ 目录，便于后续分析和诊断导出。
# =============================================================================

"""Error reporting API for receiving and persisting frontend error reports.

Provides POST /api/errors endpoint that receives error reports from the
frontend and persists them to data/runtime/errors/ for later analysis.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field


class ErrorContext(BaseModel):
    """Context information for an error report."""
    url: str
    userAgent: str
    threadId: str | None = None
    runId: str | None = None
    requestId: str | None = None
    appVersion: str | None = None


class ErrorReport(BaseModel):
    """Error report submitted from the frontend."""
    timestamp: str
    errorType: str = Field(..., pattern="^(uncaught|unhandledrejection|react|api|manual)$")
    message: str
    stack: str | None = None
    context: ErrorContext
    metadata: dict[str, Any] | None = None


class ErrorRepository:
    """Persist error reports to data/runtime/errors/ directory."""
    
    def __init__(self, project_root: Path):
        self.directory = Path(project_root) / "data" / "runtime" / "errors"
        self.directory.mkdir(parents=True, exist_ok=True)
    
    def save(self, report: ErrorReport) -> str:
        """Save an error report and return its ID."""
        error_id = f"err_{uuid.uuid4().hex[:12]}"
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        filename = f"{timestamp}-{error_id}.json"
        
        error_data = {
            "error_id": error_id,
            "received_at": datetime.now(UTC).isoformat(),
            **report.model_dump(mode="json"),
        }
        
        error_path = self.directory / filename
        error_path.write_text(json.dumps(error_data, indent=2, ensure_ascii=False), encoding="utf-8")
        
        return error_id
    
    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """List recent error reports."""
        if not self.directory.exists():
            return []
        
        error_files = sorted(self.directory.glob("*.json"), reverse=True)[:limit]
        errors = []
        for error_file in error_files:
            try:
                error_data = json.loads(error_file.read_text(encoding="utf-8"))
                errors.append(error_data)
            except Exception:
                # Skip corrupted error files
                continue
        
        return errors


def create_error_router(project_root: Path) -> APIRouter:
    """Create error reporting router with proper project root binding."""
    router = APIRouter(prefix="/api/errors", tags=["errors"])
    repository = ErrorRepository(project_root)
    
    @router.post("", status_code=status.HTTP_201_CREATED)
    def report_error(report: ErrorReport) -> dict[str, str]:
        """Receive and persist a frontend error report."""
        error_id = repository.save(report)
        return {"error_id": error_id, "status": "received"}
    
    @router.get("")
    def list_errors(limit: int = 50) -> list[dict[str, Any]]:
        """List recent error reports for debugging."""
        return repository.list_recent(limit=limit)
    
    return router
