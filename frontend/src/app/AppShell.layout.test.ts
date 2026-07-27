import { describe, expect, it } from "vitest";
import appShellSource from "./AppShell.tsx?raw";

describe("Agent sidebar layout", () => {
  it("does not render a standalone timeline outside the message process trace", () => {
    expect(appShellSource).not.toContain("agent-timeline");
    expect(appShellSource).not.toContain("agentTimeline");
  });
});
