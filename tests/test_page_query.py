from __future__ import annotations

from pathlib import Path
import time

from langchain_core.messages import AIMessage

from cellwiki.domain.contracts import WikiAgentContext
from cellwiki.domain.runs import AgentEventType, AgentRunStatus
from cellwiki.services.agent_runtime import AgentRuntimeManager
from cellwiki.services.operations import bind_agent_run
from cellwiki.services.page_query import PageQueryExecutionAdapter, PageQueryRouter


class _BoundModel:
    def __init__(self):
        self.root_client = type("Client", (), {"close": lambda self: None})()

    def bind_tools(self, tools, *, tool_choice):
        assert tool_choice == "auto"
        return self

    def invoke(self, messages):
        assert "CD3D marker" in str(messages[-1].content)
        return AIMessage(
            id="page_call_1",
            content="",
            tool_calls=[
                {
                    "name": "submit_agent_answer",
                    "args": {
                        "answer": "CD3D is listed as a marker.",
                        "citations": [
                            {
                                "page_id": "t_cell",
                                "section": "CD3D marker",
                                "quote": "CD3D | positive",
                            }
                        ],
                        "confidence": "high",
                        "missing_evidence": [],
                        "knowledge_scope": "formal",
                    },
                    "id": "tool_answer_1",
                }
            ],
            usage_metadata={"input_tokens": 120, "output_tokens": 30, "total_tokens": 150},
        )


def test_page_query_adapter_reads_current_page_and_uses_one_model_call(tmp_path: Path):
    page = tmp_path / "wiki" / "cell_types" / "t_cell.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\ndisplay_name: T cell\n---\n\n# T cell\nCD3D marker", encoding="utf-8")
    adapter = PageQueryExecutionAdapter(tmp_path, model_factory=lambda: _BoundModel())

    with bind_agent_run("run_page_query"):
        signals = list(
            adapter.execute(
                thread_id="run_page_query",
                message=[{"role": "user", "content": "这个页面有什么标记？"}],
                context=WikiAgentContext(
                    project_id="cellwiki",
                    page_id="t_cell",
                    thread_id="thread_page_query",
                ),
            )
        )

    final = next(signal for signal in signals if signal.type is AgentEventType.FINAL_RESPONSE)
    assert final.message == "CD3D is listed as a marker."
    assert final.data["verification_level"] == "page"
    assert final.data["confidence"] == "high"
    assert final.data["citations"][0]["locator"] == "CD3D marker"
    assert final.model_call_id == "page_call_1"
    assert final.input_tokens == 120
    assert final.output_tokens == 30


def test_manager_routes_current_page_question_outside_langgraph(tmp_path: Path):
    page = tmp_path / "wiki" / "cell_types" / "t_cell.md"
    page.parent.mkdir(parents=True)
    page.write_text("# T cell\nCD3D marker", encoding="utf-8")

    class _ForbiddenCoordinator:
        def execute(self, *, thread_id, message, context):
            raise AssertionError("current-page fast path must not enter LangGraph")

        def close(self):
            return None

        def delete_thread(self, thread_id):
            return None

    page_adapter = PageQueryExecutionAdapter(tmp_path, model_factory=lambda: _BoundModel())
    manager = AgentRuntimeManager(
        tmp_path,
        adapter=_ForbiddenCoordinator(),
        page_query_adapter=page_adapter,
    )
    try:
        run = manager.start(
            thread_id="thread_fast_page",
            message="What marker is listed?",
            context=WikiAgentContext(
                project_id="cellwiki",
                page_id="t_cell",
                thread_id="thread_fast_page",
            ),
        )
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current = manager.store.get_run(run.run_id)
            if current.status in {AgentRunStatus.SUCCEEDED, AgentRunStatus.FAILED}:
                break
            time.sleep(0.01)

        assert current.status is AgentRunStatus.SUCCEEDED
        assert current.model_role == "page-query"
        assert current.usage.model_calls == 1
        assert current.usage.tool_calls_started == 0
        assert {span.kind for span in manager.store.list_spans(run.run_id)} == {
            "router",
            "model",
        }
    finally:
        manager.close()


def test_page_query_router_leaves_product_help_for_the_coordinator():
    context = WikiAgentContext(project_id="cellwiki", page_id="t_cell")
    router = PageQueryRouter()

    assert router.should_handle("这个页面有哪些 marker？", context)
    assert not router.should_handle("APP 的运行详情怎么使用？", context)
