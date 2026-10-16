import { describe, expect, it } from "vitest";

import { SseParser } from "../src/api/sse";

describe("SseParser", () => {
  it("parses chunked events and ignores keep-alives", () => {
    const parser = new SseParser();
    expect(
      parser.push(': keep-alive\n\nid: 1\nevent: message_delta\ndata: {"sequence":1,'),
    ).toEqual([]);
    expect(parser.push('"type":"message_delta"}\n\n')).toEqual([
      { sequence: 1, type: "message_delta" },
    ]);
  });

  it("joins multi-line data and flushes at finish", () => {
    const parser = new SseParser();
    expect(parser.push('data: {"a":\n')).toEqual([]);
    expect(parser.push("data: 1}")).toEqual([]);
    expect(parser.finish()).toEqual([{ a: 1 }]);
  });

  it("rejects invalid JSON", () => {
    const parser = new SseParser();
    expect(() => parser.push("data: not-json\n\n")).toThrow(
      "invalid SSE JSON",
    );
  });
});
