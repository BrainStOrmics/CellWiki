"""Single-call current-page query path with formal answer validation."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable

from langchain_core.messages import HumanMessage, SystemMessage

from cellwiki.adapters.openai_model import build_openai_chat_model
from cellwiki.agent.tools import build_final_answer_tool
from cellwiki.config import settings
from cellwiki.domain.contracts import AgentAnswer, WikiAgentContext
from cellwiki.domain.runs import AgentEventType
from cellwiki.services.agent_runtime_types import AgentInput, RuntimeSignalLike
from cellwiki.services.query import FormalQueryService


PAGE_QUERY_PROMPT = """Answer the user's question only from the supplied published CellWiki page.
Use the exact page_id in every citation, and copy each citation locator as one exact
contiguous substring from the page. Do not search other pages, infer unpublished knowledge,
or claim that any product action ran. Call submit_agent_answer exactly once."""


class PageQueryRouter:
    """Select the fast path only when the current page is the complete requested scope."""

    _CROSS_SCOPE_MARKERS = (
        "所有页面",
        "全库",
        "整个知识库",
        "比较",
        "跨页面",
        "其他细胞",
        "论文",
        "文献",
        "外部",
        "search",
        "compare",
        "all pages",
        "ingest",
        "lint",
        "摄取",
        "导入",
        "检查质量",
        "修复",
        "app",
        "application",
        "软件",
        "按钮",
        "设置",
        "怎么使用",
        "如何使用",
        "agent",
        "运行详情",
    )

    def should_handle(self, message: str, context: WikiAgentContext) -> bool:
        normalized = message.lower()
        return bool(
            context.page_id
            and not context.source_id
            and not any(marker in normalized for marker in self._CROSS_SCOPE_MARKERS)
        )


class PageQueryExecutionAdapter:
    """Read one formal page and produce one validated model response."""

    MAX_PAGE_CHARS = 24_000

    def __init__(
        self,
        project_root: Path,
        *,
        model_factory: Callable[[], Any] | None = None,
    ):
        self.project_root = Path(project_root).resolve()
        self.model_factory = model_factory or (
            lambda: build_openai_chat_model(settings, purpose="page_query")
        )

    def execute(
        self,
        *,
        thread_id: str,
        message: AgentInput,
        context: WikiAgentContext,
    ) -> Iterable[RuntimeSignalLike]:
        if not context.page_id:
            raise ValueError("page query requires page_id")
        query = FormalQueryService(self.project_root)
        page = query.read_page(context.page_id)
        yield RuntimeSignalLike(
            type=AgentEventType.PROGRESS,
            message="Reading the current Wiki page.",
            progress=20,
            data={
                "activity_code": "reading_page",
                "label_args": {"page_id": context.page_id},
            },
        )

        question, history = _question_and_history(message)
        page_context = _bounded_page_context(
            page.markdown,
            question,
            selected_text=context.selected_text,
            limit=self.MAX_PAGE_CHARS,
        )

        model = self.model_factory()
        try:
            final_tool = build_final_answer_tool(self.project_root)
            # Qwen thinking mode rejects required/object tool selection. `auto`
            # preserves the single-request fast path while the prompt, parser,
            # and FormalAnswerGate still enforce the typed answer contract.
            bound = model.bind_tools([final_tool], tool_choice="auto")
            response = bound.invoke(
                [
                    SystemMessage(content=PAGE_QUERY_PROMPT),
                    HumanMessage(
                        content=(
                            f"Recent observable conversation:\n{history}\n\n"
                            f"page_id: {page.page_id}\n"
                            f"knowledge_version: {page.knowledge_version}\n\n"
                            f"{page_context}\n\nQuestion:\n{question}"
                        )
                    ),
                ]
            )
            candidate = _candidate_from_response(response, page_markdown=page.markdown)
            validated = query.validate_answer(candidate)
            usage = getattr(response, "usage_metadata", None) or {}
            yield RuntimeSignalLike(
                type=AgentEventType.FINAL_RESPONSE,
                message=validated.answer,
                data=validated.model_dump(mode="json"),
                model_call_id=str(getattr(response, "id", None) or f"page_{uuid.uuid4().hex}"),
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
            )
        finally:
            client = getattr(model, "root_client", None)
            close = getattr(client, "close", None)
            if close is not None:
                close()

    def close(self) -> None:
        return None

    def delete_thread(self, thread_id: str) -> None:
        return None


def _question_and_history(message: AgentInput) -> tuple[str, str]:
    if isinstance(message, str):
        return message, ""
    if isinstance(message, list):
        current = next(
            (
                str(item.get("content", ""))
                for item in reversed(message)
                if item.get("role") == "user"
            ),
            "",
        )
        prior = message[:-1] if message and message[-1].get("role") == "user" else message
        history = "\n".join(
            f"{item.get('role', 'user')}: {item.get('content', '')}" for item in prior
        )
        return current, history
    raise ValueError("page query cannot resume from a graph command")


def _candidate_from_response(response: Any, *, page_markdown: str = "") -> AgentAnswer:
    tool_calls = getattr(response, "tool_calls", None) or []
    for call in tool_calls:
        if call.get("name") == "submit_agent_answer":
            return _candidate_from_payload(
                call.get("args") or {},
                page_markdown=page_markdown,
            )
    content = getattr(response, "content", "")
    if isinstance(content, list):
        content = "".join(
            str(block.get("text", "")) if isinstance(block, dict) else str(block)
            for block in content
        )
    try:
        return _candidate_from_payload(
            json.loads(str(content)),
            page_markdown=page_markdown,
        )
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise ValueError("page query model did not return submit_agent_answer") from error


def _candidate_from_payload(payload: Any, *, page_markdown: str = "") -> AgentAnswer:
    """Normalize provider-added fields before crossing the domain boundary."""

    if not isinstance(payload, dict):
        raise TypeError("page query answer payload must be an object")
    citations: list[dict[str, Any]] = []
    for item in payload.get("citations") or []:
        if not isinstance(item, dict):
            continue
        locator_candidates = [
            str(value).strip()[:1_000]
            for value in (item.get("locator"), item.get("quote"), item.get("section"))
            if value
        ]
        locator = next(
            (
                value
                for value in locator_candidates
                if value.lower() in page_markdown.lower()
            ),
            locator_candidates[0] if locator_candidates else None,
        )
        source_id = item.get("source_id")
        if isinstance(source_id, list):
            source_id = ", ".join(str(value) for value in source_id if value)
        citations.append(
            {
                "page_id": item.get("page_id"),
                "source_id": source_id,
                "locator": locator,
                "evidence_id": item.get("evidence_id"),
            }
        )
    allowed = {
        key: payload[key]
        for key in (
            "answer",
            "confidence",
            "missing_evidence",
            "knowledge_scope",
            "knowledge_version",
        )
        if key in payload
    }
    return AgentAnswer.model_validate({**allowed, "citations": citations})


def _bounded_page_context(
    markdown: str,
    question: str,
    *,
    selected_text: str | None,
    limit: int,
) -> str:
    if not selected_text and len(markdown) <= limit:
        return markdown

    prefix = f"Selected text:\n{selected_text}\n\n" if selected_text else ""
    remaining = max(0, limit - len(prefix))
    sections = [
        section.strip()
        for section in re.split(r"(?=^#{1,6}\s)", markdown, flags=re.MULTILINE)
        if section.strip()
    ]
    terms = {
        term
        for term in re.findall(r"[\w-]{2,}", question.lower())
        if term not in {"what", "which", "this", "that", "page"}
    }
    ranked = sorted(
        enumerate(sections),
        key=lambda item: (
            -sum(term in item[1].lower() for term in terms),
            item[0],
        ),
    )
    selected_sections: list[tuple[int, str]] = []
    used = 0
    for index, section in ranked:
        if used >= remaining:
            break
        portion = section[: remaining - used]
        selected_sections.append((index, portion))
        used += len(portion) + 2
    selected_sections.sort(key=lambda item: item[0])
    joined = "\n\n".join(section for _, section in selected_sections)
    return f"{prefix}{joined}"


__all__ = ["PAGE_QUERY_PROMPT", "PageQueryExecutionAdapter", "PageQueryRouter"]
