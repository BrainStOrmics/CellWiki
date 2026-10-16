import { describe, expect, it } from "vitest";

import {
  classicFromEnv,
  hasClassicFlag,
  parseWorkspaceArg,
} from "../src/cli-args";

describe("cli arguments", () => {
  it("parses the workspace argument", () => {
    expect(parseWorkspaceArg(["--workspace", "/tmp/wiki"])).toBe("/tmp/wiki");
    expect(parseWorkspaceArg(["--workspace=/tmp/wiki"])).toBe("/tmp/wiki");
    expect(parseWorkspaceArg([])).toBeNull();
  });

  it("detects the classic renderer flag", () => {
    expect(hasClassicFlag(["--classic"])).toBe(true);
    expect(hasClassicFlag([])).toBe(false);
  });

  it("reads CELLWIKI_TUI_CLASSIC values", () => {
    expect(classicFromEnv({ CELLWIKI_TUI_CLASSIC: "1" })).toBe(true);
    expect(classicFromEnv({ CELLWIKI_TUI_CLASSIC: "true" })).toBe(true);
    expect(classicFromEnv({ CELLWIKI_TUI_CLASSIC: "0" })).toBe(false);
    expect(classicFromEnv({})).toBe(false);
  });
});
