import { describe, expect, it } from "vitest";
import { ProductApiError } from "../lib/product-api";
import { agentRequestFailure } from "./AppShell";
import appShellSource from "./AppShell.tsx?raw";

function sliceBetween(source: string, start: string, end: string): string {
  const from = source.indexOf(start);
  expect(from, `missing ${start}`).toBeGreaterThan(-1);
  const to = source.indexOf(end, from + start.length);
  expect(to, `missing ${end} after ${start}`).toBeGreaterThan(-1);
  return source.slice(from + start.length, to);
}

describe("agent request error presentation", () => {
  it("preserves Product API details instead of reporting the runtime offline", () => {
    const result = agentRequestFailure(
      new ProductApiError(
        "another AgentRuntimeManager already owns this project",
        503,
      ),
      "runtime offline",
    );

    expect(result).toEqual({
      text: "another AgentRuntimeManager already owns this project",
      meta: "AGENT REQUEST FAILED · HTTP 503",
      code: null,
    });
  });

  it("keeps the offline guidance for transport failures", () => {
    expect(agentRequestFailure(new TypeError("Failed to fetch"), "runtime offline"))
      .toEqual({ text: "runtime offline", meta: "RUNTIME OFFLINE", code: null });
  });

  it("交出后端的稳定判别码，让调用方按类别而不是按文案分流", () => {
    const result = agentRequestFailure(
      new ProductApiError(
        "run r1 has no usable checkpoint",
        409,
        { detail: { code: "checkpoint_missing", message: "run r1 has no usable checkpoint" } },
        "checkpoint_missing",
      ),
      "runtime offline",
    );

    expect(result.code).toBe("checkpoint_missing");
    expect(result.meta).toBe("AGENT REQUEST FAILED · HTTP 409");
  });
});

describe("agent error vocabulary", () => {
  it("为后端每一个错误分类都准备了用户可读文案", () => {
    // domain/runs.py 的 AgentErrorType 是十个值的封闭集合。reducer 对拿不到的码回落到
    // provider 原文，所以漏一个条目就会静默地把实测交接问题 E 放回来。
    const codes = [
      "input",
      "authentication",
      "permission",
      "rate_limit",
      "timeout",
      "budget",
      "structured_output",
      "approval",
      "conflict",
      "system",
    ];
    const block = sliceBetween(appShellSource, "errorTypes: {", "},");
    for (const code of codes) {
      expect(block, code).toContain(`${code}: t("chat.error.${code}")`);
    }
  });
});
