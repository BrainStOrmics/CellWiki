# =============================================================================
# 原生 Anthropic 协调器链路 —— 桩级集成测试（无 key 的替代验证）
# =============================================================================
# 用本地 Messages API 桩（stdlib HTTP server）走真实链路：目录解析 →
# build_coordinator_model → ChatAnthropicWithRootClient → deepagents 协调器 →
# 真实工作区工具 → tool_result 回传 → 最终回答。
#
# 验证的是 CellWiki 的接线：协议分发、工具 schema 翻译、工具结果往返、
# harness profile 与工具边界在 Anthropic 请求里的实际形态。
#
# 2026-09-15 起协调器对 Anthropic 协议也逐 token 流式，桩因此实现 Messages
# API 的 SSE 形状：正文拆成多个 text_delta，首轮额外带一个 thinking 块，
# 用来验证 thinking 增量真的走到 reasoning_delta。**不代表真实供应商行为**
# ——真实 tool_use 往返与 thinking 需要 key 的沙箱 smoke
# （design/archive/2026-09-15-three-protocol-token-streaming.md）。
# =============================================================================

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tests.schema_helpers import minimal_schema_contract, valid_cell_type_page
from cellwiki.domain.contracts import WikiAgentContext
from cellwiki.domain.model_providers import ModelSelection, ProviderModel
from cellwiki.domain.runs import AgentEventType, AgentRunStatus, RunBudget
from cellwiki.services.agent_runtime import AgentRuntimeManager
from cellwiki.services.model_catalog import ModelCatalogService

FINAL_TEXT = "The page lists FOXP3 and IL2RA."


class _AnthropicStub:
    """Minimal Messages API stub: tool_use on the first call, text afterwards.

    同时实现非流式 JSON 与 ``stream: true`` 的 SSE 两种形状：协调器自
    2026-09-15 起默认流式，桩必须按 Messages API 的事件序列回答，才能覆盖
    "正文多个 text_delta + thinking 增量 + tool_use 分片" 的真实接线。
    """

    THINKING_TEXT = "先读页面再回答。"
    # 正文拆成两段：流式接线正常时事件流里会出现两条 message_delta。
    TEXT_CHUNKS = ("The page lists ", "FOXP3 and IL2RA.")

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
                model = str(payload.get("model", "claude-stub"))
                if payload.get("stream"):
                    data = stub._sse(content, stop_reason, model)
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                data = json.dumps(
                    {
                        "id": "msg_stub",
                        "type": "message",
                        "role": "assistant",
                        "model": model,
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
                return (
                    [
                        {"type": "text", "text": self.TEXT_CHUNKS[0]},
                        {"type": "text", "text": self.TEXT_CHUNKS[1]},
                    ],
                    "end_turn",
                )
        return (
            [
                {
                    "type": "thinking",
                    "thinking": self.THINKING_TEXT,
                    "signature": "stub-signature",
                },
                {
                    "type": "tool_use",
                    "id": "toolu_stub_1",
                    "name": "read_file",
                    "input": {"path": "wiki/cell_types/regulatory_t_cell.md"},
                },
            ],
            "tool_use",
        )

    def _sse(self, content: list[dict], stop_reason: str, model: str) -> bytes:
        """Serialize one stub reply as the Messages API SSE event sequence."""

        events: list[tuple[str, dict]] = [
            (
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": "msg_stub",
                        "type": "message",
                        "role": "assistant",
                        "model": model,
                        "content": [],
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": {"input_tokens": 12, "output_tokens": 0},
                    },
                },
            )
        ]
        for index, block in enumerate(content):
            block_type = block.get("type")
            if block_type == "thinking":
                events.append(
                    (
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": index,
                            "content_block": {
                                "type": "thinking",
                                "thinking": "",
                                "signature": "",
                            },
                        },
                    )
                )
                events.append(
                    (
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": index,
                            "delta": {
                                "type": "thinking_delta",
                                "thinking": str(block.get("thinking") or ""),
                            },
                        },
                    )
                )
                events.append(
                    (
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": index,
                            "delta": {
                                "type": "signature_delta",
                                "signature": str(block.get("signature") or ""),
                            },
                        },
                    )
                )
            elif block_type == "tool_use":
                events.append(
                    (
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": index,
                            "content_block": {
                                "type": "tool_use",
                                "id": block.get("id"),
                                "name": block.get("name"),
                                "input": {},
                            },
                        },
                    )
                )
                events.append(
                    (
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": index,
                            "delta": {
                                "type": "input_json_delta",
                                "partial_json": json.dumps(block.get("input") or {}),
                            },
                        },
                    )
                )
            else:
                events.append(
                    (
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": index,
                            "content_block": {"type": "text", "text": ""},
                        },
                    )
                )
                events.append(
                    (
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": index,
                            "delta": {
                                "type": "text_delta",
                                "text": str(block.get("text") or ""),
                            },
                        },
                    )
                )
            events.append(
                (
                    "content_block_stop",
                    {"type": "content_block_stop", "index": index},
                )
            )
        events.append(
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                    "usage": {"output_tokens": 8},
                },
            )
        )
        events.append(("message_stop", {"type": "message_stop"}))
        return "".join(
            f"event: {name}\ndata: {json.dumps(payload)}\n\n"
            for name, payload in events
        ).encode()

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
    (root / "schema.md").write_text(minimal_schema_contract(), encoding="utf-8")
    page = root / "wiki" / "cell_types" / "regulatory_t_cell.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        valid_cell_type_page(
            standard_name="regulatory_t_cell",
            display_name="Regulatory T cell",
            body_suffix="FOXP3 and IL2RA are the core markers.\n",
        ),
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

    # 2026-09-15 起 Anthropic 协调器也走流式请求：请求体带 stream=true，
    # 正文与 thinking 都以增量事件落地（thinking 不再是整块或缺失）。
    assert all(request.get("stream") is True for request in stub.requests)
    message_deltas = [
        event for event in events if event.type == AgentEventType.MESSAGE_DELTA
    ]
    reasoning_deltas = [
        event for event in events if event.type == AgentEventType.REASONING_DELTA
    ]
    assert len(message_deltas) > 1, [event.type.value for event in events]
    assert "".join(event.message for event in message_deltas) == FINAL_TEXT
    assert [event.message for event in reasoning_deltas] == [_AnthropicStub.THINKING_TEXT]

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
