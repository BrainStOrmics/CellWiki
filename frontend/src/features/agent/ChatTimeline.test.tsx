import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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
  it("刻度长度跟着该轮问答字数走，短轮最 12px、长轮封顶 28px", () => {
    expect(dashWidth({ index: 0, question: "问", answer: "" })).toBe(12);
    expect(dashWidth({ index: 0, question: "问".repeat(200), answer: "答".repeat(200) })).toBe(28);
    const middle = dashWidth({ index: 0, question: "问".repeat(100), answer: "答".repeat(100) });
    expect(middle).toBeGreaterThan(12);
    expect(middle).toBeLessThan(28);
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

  it("长轮的刻度更长（宽度按内容量内联）", () => {
    const { container } = renderTimeline([
      message("user", "短问题"),
      message("agent", "短回答"),
      message("user", `长问题${"等等".repeat(120)}`),
      message("agent", `长回答${"细节".repeat(120)}`),
    ]);

    const dashes = [...container.querySelectorAll<HTMLElement>(".chat-timeline-dash")];
    expect(dashes).toHaveLength(2);
    const [short, long] = dashes.map((node) => Number.parseFloat(node.style.width));
    expect(short).toBe(12);
    expect(long).toBe(28);
  });

  it("没有任何用户消息时不渲染这条轨", () => {
    const { container } = renderTimeline([message("agent", "只有开场白")]);
    expect(container.querySelector(".chat-timeline")).toBeNull();
  });
});
