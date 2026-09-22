"""Regression tests for the single compaction owner and declared model window."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deepagents.middleware.summarization import SummarizationMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from cellwiki.agent.app import build_wiki_agent


class _BuildOnlyModel(BaseChatModel):
    """Minimal model used to compile the real CellWiki graph."""

    @property
    def _llm_type(self) -> str:
        return "cellwiki-build-only"

    def _get_ls_params(self, **kwargs: Any) -> dict[str, str]:
        return {"ls_provider": "openai", "ls_model_name": "build-only"}

    def bind_tools(self, tools: Any, **kwargs: Any) -> "_BuildOnlyModel":
        return self

    def _bind_tools(self, tools: Any, **kwargs: Any) -> "_BuildOnlyModel":
        return self

    def _generate(
        self,
        messages: Any,
        stop: Any = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="done"))]
        )


def _middleware_names(handler: Any) -> set[str]:
    """Walk LangChain's composed model-call handler and collect middleware names."""

    found: set[str] = set()
    seen: set[int] = set()

    def walk(current: Any) -> None:
        if current is None or id(current) in seen:
            return
        seen.add(id(current))
        qualname = str(getattr(current, "__qualname__", "") or "")
        if "Middleware" in qualname:
            found.add(qualname.split(".", 1)[0])
        function = getattr(current, "__func__", current)
        closure = getattr(function, "__closure__", None) or ()
        freevars = getattr(getattr(function, "__code__", None), "co_freevars", ())
        for name, cell in zip(freevars, closure):
            if name not in {"outer", "inner", "handler", "handlers"}:
                continue
            value = cell.cell_contents
            if callable(value):
                walk(value)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    walk(item)

    walk(handler)
    return found


def test_compiled_graph_has_cellwiki_as_the_only_compaction_owner(tmp_path: Path) -> None:
    """唯一压缩决策者 = CellWiki 压缩中间件；框架摘要中间件仍被排除。

    2026-09-22 对齐工作后语义收窄：压缩**决策**归 CellWiki 中间件，runtime
    仍是模型转录的唯一**写入者**。两个 CellWiki 中间件都必须在线。
    """

    graph = build_wiki_agent(
        tmp_path,
        model=_BuildOnlyModel(),
        checkpointer=None,
    )
    model_node = graph.nodes["model"].bound
    closure = dict(
        zip(
            model_node.func.__code__.co_freevars,
            model_node.func.__closure__ or (),
        )
    )
    wrap_handler = closure["wrap_model_call_handler"].cell_contents

    middleware_names = _middleware_names(wrap_handler)
    assert SummarizationMiddleware.__name__ not in middleware_names
    assert not any("Summarization" in name for name in middleware_names)
    assert "_CellWikiToolBoundaryMiddleware" in middleware_names
    assert "CellWikiCompactionMiddleware" in middleware_names
