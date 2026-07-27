import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AgentProcessTrace } from "./AgentProcessTrace";
import type { AgentProcessStep } from "../../types";

const steps: AgentProcessStep[] = [{
  event_id: "event_tool",
  run_id: "run_trace",
  thread_id: "thread_trace",
  sequence: 1,
  type: "tool_completed",
  message: "读取当前 Wiki 页面",
  data: { tool_name: "read_wiki_page" },
  created_at: "2026-07-22T00:00:00Z",
  phase: "completed",
}];

describe("AgentProcessTrace", () => {
  it("opens while live and collapses after completion", () => {
    const { container, rerender } = render(
      <AgentProcessTrace
        steps={steps}
        live
        title="Agent 过程"
        liveLabel="正在执行"
        completedLabel="已完成"
        emptyLabel="暂无过程"
      />,
    );
    const details = container.querySelector("details") as HTMLDetailsElement;
    expect(details.open).toBe(true);
    expect(screen.getByText("读取当前 Wiki 页面")).toBeVisible();

    rerender(
      <AgentProcessTrace
        steps={steps}
        live={false}
        title="Agent 过程"
        liveLabel="正在执行"
        completedLabel="已完成"
        emptyLabel="暂无过程"
      />,
    );
    expect(details.open).toBe(false);
  });

  it("marks failed process steps", () => {
    const failed = [{ ...steps[0], phase: "failed" as const, message: "工具调用失败" }];
    const { container } = render(
      <AgentProcessTrace
        steps={failed}
        live={false}
        title="Agent 过程"
        liveLabel="正在执行"
        completedLabel="已完成"
        emptyLabel="暂无过程"
      />,
    );

    expect(container.querySelector(".agent-process-step.failed")).not.toBeNull();
  });
});
