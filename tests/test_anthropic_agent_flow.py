# =============================================================================
# 原生 Anthropic 协调器链路 —— 桩级集成测试（无 key 的替代验证）
# =============================================================================
# 用本地 Messages API 桩（stdlib HTTP server）走真实链路：目录解析 →
# build_coordinator_model → ChatAnthropicWithRootClient → deepagents 协调器 →
# 真实工作区工具 → tool_result 回传 → 最终回答。
#
# 验证的是 CellWiki 的接线：协议分发、工具 schema 翻译、工具结果往返、
# harness profile 与工具边界在 Anthropic 请求里的实际形态。**不代表真实
# 供应商行为**——真实 tool_use 往返与 thinking 需要 key 的沙箱 smoke
# （design/active/2026-09-13-anthropic-protocol-adapter.md）。
# =============================================================================

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cellwiki.domain.contracts import WikiAgentContext
from cellwiki.domain.model_providers import ModelSelection, ProviderModel
from cellwiki.domain.runs import AgentRunStatus, RunBudget
from cellwiki.services.agent_runtime import AgentRuntimeManager
from cellwiki.services.model_catalog import ModelCatalogService

FINAL_TEXT = "The page lists FOXP3 and IL2RA."


class _AnthropicStub:
    """Minimal Messages API stub: tool_use on the first call, text afterwards."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:  # noqa: N802 - stdlib 命名
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length) or b"{}")
                stub.requests.append(payload)
                content, stop_reason = stub._reply(payload)
                data = json.dumps(
                    {
                        "id": "msg_stub",
                        "type": "message",
                        "role": "assistant",
                        "model": payload.get("model", "claude-stub"),
                        "content": content,
                        "stop_reason": stop_reason,
                        "stop_sequence": None,
                        "usage": {"input_tokens": 12, "output_tokens": 8},
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, fmt: str, *args) -> None:  # noqa: A003
                return None

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def _reply(self, payload: dict) -> tuple[list[dict], str]:
        for message in payload.get("messages", []):
            content = message.get("content")
            if isinstance(content, list) and any(
                isinstance(block, dict) and block.get("type") == "tool_result"
                for block in content
            ):
                return [{"type": "text", "text": FINAL_TEXT}], "end_turn"
        return (
            [
                {
                    "type": "tool_use",
                    "id": "toolu_stub_1",
                    "name": "read_file",
                    "input": {"path": "wiki/cell_types/regulatory_t_cell.md"},
                }
            ],
            "tool_use",
        )

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def _seed_workspace(root: Path) -> None:
    (root / "schema.md").write_text(
        "```yaml cellwiki-schema\n"
        "schema_version: 1\n"
        "pages:\n"
        "  cell_type:\n"
        "    path: wiki/cell_types/{id}.md\n"
        "    identity: standard_name\n"
        "    frontmatter:\n"
        "      required:\n"
        "        standard_name: {type: string}\n"
        "        display_name: {type: string}\n"
        "    sections: {required: []}\n"
        "    references: {required: false}\n"
        "    links: {check: false}\n"
        "```\n",
        encoding="utf-8",
    )
    page = root / "wiki" / "cell_types" / "regulatory_t_cell.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        "---\nstandard_name: regulatory_t_cell\ndisplay_name: Regulatory T cell\n---\n\n"
        "# Regulatory T cell\n\nFOXP3 and IL2RA are the core markers.\n",
        encoding="utf-8",
    )


def _wait_terminal(manager: AgentRuntimeManager, run_id: str, timeout: float = 60.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = manager.store.get_run(run_id)
        if run.status in {
            AgentRunStatus.SUCCEEDED,
            AgentRunStatus.FAILED,
            AgentRunStatus.CANCELLED,
            AgentRunStatus.UNFINISHED,
        }:
            return run
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not reach a terminal status in time")


def _tool_names(payload: dict) -> set[str]:
    return {
        str(tool.get("name"))
        for tool in payload.get("tools", [])
        if isinstance(tool, dict)
    }


def test_anthropic_coordinator_run_round_trips_tool_use_through_stub(tmp_path: Path) -> None:
    _seed_workspace(tmp_path)
    stub = _AnthropicStub()
    stub.start()
    try:
        catalog = ModelCatalogService(tmp_path)
        catalog.create_provider(
            provider_id="stub-claude",
            name="Stub Claude",
            base_url=stub.base_url,
            protocol="anthropic",
            models=[ProviderModel(id="claude-stub-model")],
            api_key="sk-ant-stub",
        )
        spec = catalog.resolve(
            ModelSelection(provider_id="stub-claude", model_id="claude-stub-model")
        )
        assert spec is not None

        manager = AgentRuntimeManager(tmp_path, model_catalog=catalog)
        try:
            thread_id = "thread_anthropic_stub"
            manager.store.create_thread(thread_id)
            run, _replayed = manager.start_idempotent(
                thread_id=thread_id,
                message="Which markers does the regulatory T cell page list?",
                context=WikiAgentContext(project_id="cellwiki", thread_id=thread_id),
                budget=RunBudget(max_model_calls=6, max_runtime_seconds=90),
                model_spec=spec,
                model_name=spec.model_id,
            )
            done = _wait_terminal(manager, run.run_id)
            events = manager.store.list_events(run.run_id)
            messages = manager.store.list_messages(thread_id)
        finally:
            manager.close()
    finally:
        stub.stop()

    detail = f"status={done.status} error={done.error_message} events={[e.type.value for e in events]}"
    assert done.status == AgentRunStatus.SUCCEEDED, detail
    assert done.model_name == "claude-stub-model"
    assert done.model_provider_id == "stub-claude"

    # 第一轮模型请求：Anthropic 原生形状的工具与系统提示都到位
    assert len(stub.requests) >= 2, f"expected a tool round trip, got {len(stub.requests)} calls"
    first = stub.requests[0]
    names = _tool_names(first)
    assert "read_file" in names
    assert not {"execute", "bash", "write_todos", "task"} & names
    assert "CewiPilot" in str(first.get("system", ""))
    assert "CellWiki tool boundary" in str(first.get("system", ""))

    # 第二轮请求携带真实工具执行结果（读到了种子页面）
    second = stub.requests[1]
    assert "FOXP3" in json.dumps(second.get("messages", []), ensure_ascii=False)

    # 最终回答进入线程 transcript
    assert any(
        message["role"] == "assistant" and FINAL_TEXT in str(message["content"])
        for message in messages
    ), messages
