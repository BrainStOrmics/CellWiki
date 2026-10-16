import { describe, expect, it } from "vitest";

import { redactSecrets } from "../src/redact";

describe("redactSecrets", () => {
  it("redacts credential assignments in diff lines", () => {
    expect(redactSecrets("+OPENAI_API_KEY=sk-123\n+note=1")).toBe(
      "+OPENAI_API_KEY=<redacted>\n+note=1",
    );
    expect(redactSecrets("+password: hunter2")).toBe("+password: <redacted>");
  });
});
