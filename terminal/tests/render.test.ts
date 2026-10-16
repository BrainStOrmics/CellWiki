import { describe, expect, it } from "vitest";

import {
  displayWidth,
  padToWidth,
  truncateToWidth,
  wrapToWidth,
} from "../src/render/text";
import { formatRelativeTime } from "../src/render/time";
import { renderInline, renderMarkdown } from "../src/render/markdown";
import {
  buildLiveLines,
  gateLayout,
  toVisualLines,
  windowLines,
} from "../src/render/viewport";

describe("text helpers", () => {
  it("measures CJK width as two cells", () => {
    expect(displayWidth("ab")).toBe(2);
    expect(displayWidth("中文")).toBe(4);
  });

  it("truncates inside the requested width", () => {
    expect(truncateToWidth("abcdef", 4)).toBe("abc…");
    expect(displayWidth(truncateToWidth("中文中文", 5))).toBeLessThanOrEqual(5);
    expect(truncateToWidth("short", 10)).toBe("short");
  });

  it("wraps long lines and keeps empty lines", () => {
    expect(wrapToWidth("abcdef", 4)).toEqual(["abcd", "ef"]);
    expect(wrapToWidth("a\n\nb", 4)).toEqual(["a", "", "b"]);
    expect(wrapToWidth("", 4)).toEqual([""]);
  });

  it("pads a row for a full-width background", () => {
    expect(padToWidth("❯ hi", 6)).toBe("❯ hi  ");
    expect(displayWidth(padToWidth("中文", 6))).toBe(6);
    expect(padToWidth("toolong", 3)).toBe("toolong");
  });
});

describe("transcript visual lines", () => {
  it("prefixes user and assistant lines and indents continuations", () => {
    const visual = toVisualLines(
      [
        { text: "hello", tone: "user" },
        { text: "abcdefghij", tone: "assistant" },
      ],
      8,
    );
    expect(visual.map((line) => line.text)).toEqual([
      "❯ hello",
      "● abcdef",
      "  ghij",
    ]);
  });
});

describe("markdown rendering", () => {
  it("styles inline emphasis, code and links", () => {
    expect(renderInline("**bold** and `code` and [link](https://x)")).toEqual([
      { text: "bold", bold: true },
      { text: " and " },
      { text: "code", dim: true },
      { text: " and " },
      { text: "link", underline: true },
    ]);
  });

  it("keeps python dunder identifiers intact", () => {
    expect(renderInline("call __init__ now")).toEqual([
      { text: "call __init__ now" },
    ]);
  });

  it("renders headings, bullets, quotes and code fences", () => {
    const lines = renderMarkdown(
      "# Title\n- item\n> note\n```\nraw **code**\n```\nafter",
    );
    expect(
      lines.map((line) => line.segments.map((segment) => segment.text).join("")),
    ).toEqual(["Title", "• item", "│ note", "raw **code**", "after"]);
  });

  it("strips markdown markers from assistant visual lines", () => {
    const visual = toVisualLines(
      [{ text: "**能看到:** 只有 thread", tone: "assistant" }],
      40,
    );
    expect(visual[0]?.text).toBe("● 能看到: 只有 thread");
    expect(visual[0]?.segments?.some((segment) => segment.bold)).toBe(true);
  });
});

describe("relative time", () => {
  const now = Date.parse("2026-10-16T12:00:00Z");

  it("formats recent and older timestamps", () => {
    expect(formatRelativeTime("2026-10-16T11:59:30Z", now)).toBe("just now");
    expect(formatRelativeTime("2026-10-16T11:30:00Z", now)).toBe("30 min ago");
    expect(formatRelativeTime("2026-10-15T12:00:00Z", now)).toBe("1 day ago");
    expect(formatRelativeTime("2026-10-01T12:00:00Z", now)).toBe("2 weeks ago");
    expect(formatRelativeTime(null, now)).toBe("unknown");
  });
});

describe("viewport", () => {
  const lines = Array.from({ length: 10 }, (_, index) => ({
    text: `line ${index}`,
  }));

  it("shows the tail when following", () => {
    const view = windowLines(lines, 3, 0);
    expect(view.lines.map((line) => line.text)).toEqual([
      "line 7",
      "line 8",
      "line 9",
    ]);
    expect(view.hiddenAbove).toBe(7);
    expect(view.hiddenBelow).toBe(0);
  });

  it("scrolls up and clamps both ends", () => {
    const view = windowLines(lines, 3, 4);
    expect(view.lines.map((line) => line.text)).toEqual([
      "line 3",
      "line 4",
      "line 5",
    ]);
    expect(view.hiddenBelow).toBe(4);
    const clamped = windowLines(lines, 3, 99);
    expect(clamped.lines.map((line) => line.text)).toEqual([
      "line 0",
      "line 1",
      "line 2",
    ]);
    expect(clamped.hiddenBelow).toBe(7);
  });
});

describe("live region", () => {
  it("keeps long reasoning compact", () => {
    const live = buildLiveLines(
      {
        reasoning: "x".repeat(5_000),
        streaming: "",
        tools: [],
        runId: "run_1",
        verbose: false,
      },
      "⠋",
      40,
    );
    expect(live.length).toBeLessThanOrEqual(4);
    expect(live[0]?.text).toContain("Thinking…");
    expect(live.map((line) => line.text).join("").length).toBeLessThan(300);
  });

  it("wraps streaming text and lists running tools", () => {
    const live = buildLiveLines(
      {
        reasoning: "",
        streaming: "hello world",
        tools: [{ id: "tool_1", summary: "read_file x.md" }],
        runId: "run_1",
        verbose: false,
      },
      "⠋",
      8,
    );
    expect(live.map((line) => line.text).join("")).toContain("read_file");
    expect(live.some((line) => line.text.includes("hello"))).toBe(true);
  });
});

describe("gate layout", () => {
  it("budgets a long diff inside the terminal", () => {
    const patch = Array.from({ length: 60 }, (_, index) => `+line ${index}`).join(
      "\n",
    );
    const layout = gateLayout(
      { kind: "diff", runId: "run_1", diffId: "diff_1", patch },
      24,
    );
    expect(layout.rows).toBeLessThanOrEqual(18);
    expect(layout.previewLines).toBeGreaterThan(0);
    expect(layout.previewLines).toBeLessThan(60);
  });

  it("caps question options", () => {
    const options = Array.from({ length: 20 }, (_, index) => ({
      label: `option ${index}`,
    }));
    const layout = gateLayout(
      {
        kind: "question",
        runId: "run_1",
        question: { run_id: "run_1", question: "pick one", options },
      },
      16,
    );
    expect(layout.rows).toBeLessThanOrEqual(10);
    expect(layout.maxOptions).toBeLessThan(20);
  });
});
