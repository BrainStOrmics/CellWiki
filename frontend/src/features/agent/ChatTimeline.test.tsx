import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatTimeline, chatTurns, currentTurnIndex, dashWidth } from "./ChatTimeline";
import { LanguageProvider } from "../../i18n";
import type { ChatMessage } from "../../types";

afterEach(cleanup);

function message(role: "user" | "agent", text: string): ChatMessage {
  return { role, text };
}

function renderTimeline(messages: ChatMessage[], onJump = vi.fn()) {
  const view = render(
    <LanguageProvider>
      <ChatTimeline messages={messages} onJump={onJump} />
    </LanguageProvider>,
  );
  return { ...view, onJump };
}

describe("chatTurns", () => {
  it("一轮 = 一条用户消息 + 它之后的第一条回答", () => {
    const turns = chatTurns([
      message("agent", "开场白"),
      message("user", "第一问"),
      message("agent", "第一答"),
      message("agent", "补充"),
      message("user", "第二问"),
      message("agent", "第二答"),
    ]);
    expect(turns.map((turn) => [turn.index, turn.question, turn.answer])).toEqual([
      [1, "第一问", "第一答"],
      [4, "第二问", "第二答"],
    ]);
  });

  it("没有回答的最后一轮也出刻度（回答为空）", () => {
    const turns = chatTurns([message("user", "刚发的问题")]);
    expect(turns).toEqual([{ index: 0, question: "刚发的问题", answer: "" }]);
  });
});

describe("dashWidth / currentTurnIndex", () => {
  it("刻度长度只由离当前轮的距离决定：当前最长、紧邻次之、其余等长", () => {
    expect(dashWidth(0)).toBe(30);
    expect(dashWidth(1)).toBe(22);
    expect(dashWidth(2)).toBe(19);
    expect(dashWidth(7)).toBe(16);
    // 没有当前轮时整排等长
    expect(dashWidth(null)).toBe(16);
  });

  it("正在看的那一轮 = 视口顶部之前最近的一条锚点", () => {
    expect(currentTurnIndex([], 24)).toBeNull();
    expect(currentTurnIndex([{ index: 1, top: -300 }, { index: 4, top: 10 }, { index: 7, top: 500 }], 24)).toBe(4);
    // 还没滚过任何一轮（都在视口下方）时不高亮
    expect(currentTurnIndex([{ index: 0, top: 120 }], 24)).toBeNull();
  });
});

describe("ChatTimeline", () => {
  it("只给用户消息出刻度，点击带着那条消息的下标跳转", () => {
    const { onJump } = renderTimeline([
      message("agent", "开场白"),
      message("user", "问题一"),
      message("agent", "回答一"),
      message("user", "问题二"),
    ]);

    const ticks = screen.getAllByRole("button");
    expect(ticks).toHaveLength(2);
    expect(ticks[0]).toHaveAccessibleName(/问题一/);

    fireEvent.click(ticks[1]);
    expect(onJump).toHaveBeenCalledWith(3);
  });

  it("预览截断用户消息与回答，长文加省略号", () => {
    const long = "这".repeat(120);
    const { container } = renderTimeline([
      message("user", long),
      message("agent", long),
    ]);

    const preview = container.querySelector(".chat-timeline-preview") as HTMLElement;
    const [title, answer] = preview.querySelectorAll("b, small");
    expect(title.textContent?.endsWith("…")).toBe(true);
    expect(title.textContent?.length).toBeLessThanOrEqual(43);
    expect(answer.textContent?.endsWith("…")).toBe(true);
    expect(answer.textContent?.length).toBeLessThanOrEqual(65);
  });

  it("当前那枚最长，紧邻的次之，其余等长", async () => {
    // 锚点都在视口顶部之上（jsdom 量不出布局、全是 0）→ 当前轮 = 最后一轮
    const scroller = document.createElement("div");
    // 用户消息在消息数组里的下标：0、2、4
    for (const chatIndex of [0, 2, 4]) {
      const node = document.createElement("div");
      node.dataset.chatIndex = String(chatIndex);
      scroller.appendChild(node);
    }
    const scrollRef = { current: scroller };
    const { container } = render(
      <LanguageProvider>
        <ChatTimeline
          messages={[
            message("user", "第一问"),
            message("agent", "第一答"),
            message("user", "第二问"),
            message("agent", "第二答"),
            message("user", "第三问"),
            message("agent", "第三答"),
          ]}
          onJump={vi.fn()}
          scrollRef={scrollRef}
        />
      </LanguageProvider>,
    );

    await waitFor(() =>
      expect(container.querySelectorAll(".chat-timeline-tick")[2]).toHaveClass("is-current"),
    );
    const widths = [...container.querySelectorAll<HTMLElement>(".chat-timeline-dash")].map(
      (node) => Number.parseFloat(node.style.width),
    );
    // 从远到近：隔两轮 19 → 紧邻 22 → 当前 30
    expect(widths).toEqual([19, 22, 30]);
  });

  it("没有任何用户消息时不渲染这条轨", () => {
    const { container } = renderTimeline([message("agent", "只有开场白")]);
    expect(container.querySelector(".chat-timeline")).toBeNull();
  });
});
