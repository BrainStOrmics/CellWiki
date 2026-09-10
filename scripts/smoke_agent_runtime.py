"""Opt-in real-model smoke test for Deep Agents, SQLite runs, and stable events."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from cellwiki.config import settings
from cellwiki.domain.contracts import WikiAgentContext
from cellwiki.domain.runs import AgentEventType, AgentRunStatus, RunBudget
from cellwiki.evaluation import cited_paths
from cellwiki.services.agent_runtime import AgentRuntimeManager


ROOT = Path(__file__).resolve().parents[1]
TERMINAL = {
    AgentRunStatus.SUCCEEDED,
    AgentRunStatus.WAITING_APPROVAL,
    AgentRunStatus.REJECTED,
    AgentRunStatus.FAILED,
    AgentRunStatus.CANCELLED,
    # 预算或时长耗尽会落到 unfinished；不收进终态集合的话，这里只能等到外层
    # 超时才取消，报告会把一次可判定的失败说成超时。
    AgentRunStatus.UNFINISHED,
}


def _pick_page(workspace: Path) -> str:
    """Choose a real page to query instead of trusting a hard-coded page id."""

    pages = sorted((workspace / "wiki" / "cell_types").glob("*.md"))
    if not pages:
        raise SystemExit(f"no wiki/cell_types/*.md under {workspace}; nothing to query")
    return pages[0].relative_to(workspace).as_posix()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        type=Path,
        default=settings.workspace_root,
        help="Knowledge-base workspace this read-only smoke run may read.",
    )
    args = parser.parse_args()
    workspace = Path(args.workspace).resolve()
    # 应用根不是知识库：真模型在这里拥有整个源码仓库的写权限，冒烟测试不能把它
    # 当成被测工作区。
    if workspace == ROOT.resolve():
        raise SystemExit(
            "refusing to smoke against the application root; pass --workspace <knowledge base>"
        )
    if not settings.openai_api_key:
        raise SystemExit("OPENAI_API_KEY is required for the opt-in real-model smoke")
    page = _pick_page(workspace)

    manager = AgentRuntimeManager(workspace)
    try:
        thread_id = f"smoke_{int(time.time())}"
        run = manager.start(
            thread_id=thread_id,
            message=(
                f"只读查询：简要说明 {page} 这一页记录了什么，"
                "并在回答里写出你依据的工作区文件路径。不要修改任何文件。"
            ),
            context=WikiAgentContext(
                project_id="cellwiki",
                page_id=Path(page).stem,
                thread_id=thread_id,
            ),
            budget=RunBudget(max_model_calls=6, max_runtime_seconds=150, max_retries=1),
        )
        deadline = time.monotonic() + 160
        while time.monotonic() < deadline:
            current = manager.store.get_run(run.run_id)
            if current.status in TERMINAL:
                break
            time.sleep(0.2)
        else:
            manager.cancel(run.run_id)
            raise SystemExit("Agent runtime smoke test exceeded its outer timeout")

        events = manager.store.list_events(run.run_id)
        final = next(
            (event for event in reversed(events) if event.type == AgentEventType.FINAL_RESPONSE),
            None,
        )
        # 当前合同：最终回答是纯文本，完整正文在事件的 message 上；引用即工作区
        # 相对路径，所以判据是把路径从正文里抽出来，再核对它们真的存在。
        answer = final.message if final else ""
        cited = cited_paths(answer)
        missing = [path for path in cited if not (workspace / path).is_file()]
        final_summary = {
            "answer_chars": len(answer),
            "cited_paths": cited,
            "missing_paths": missing,
        } if final else None
        print(json.dumps({
            "workspace": str(workspace),
            "run_id": run.run_id,
            "status": current.status.value,
            "error_type": current.error_type.value if current.error_type else None,
            "usage": current.usage.model_dump(mode="json"),
            "event_types": [event.type.value for event in events],
            "final_response": final_summary,
        }, ensure_ascii=False, indent=2))
        if current.status != AgentRunStatus.SUCCEEDED or final is None or not cited or missing:
            raise SystemExit(
                "Agent runtime smoke test did not produce a grounded final response"
            )
    finally:
        manager.close()


if __name__ == "__main__":
    main()
