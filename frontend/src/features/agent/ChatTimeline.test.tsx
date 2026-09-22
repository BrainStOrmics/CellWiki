import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatTimeline, chatTurns } from "./ChatTimeline";
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

  it("没有任何用户消息时不渲染这条轨", () => {
    const { container } = renderTimeline([message("agent", "只有开场白")]);
    expect(container.querySelector(".chat-timeline")).toBeNull();
  });
});
