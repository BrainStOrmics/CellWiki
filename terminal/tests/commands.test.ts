import { describe, expect, it } from "vitest";

import { filterCommands, isKnownCommand, parseCommand } from "../src/commands";

describe("commands", () => {
  it("parses a command and its argument", () => {
    expect(parseCommand("/resume 2")).toEqual({ name: "/resume", argument: "2" });
    expect(parseCommand("/status")).toEqual({ name: "/status", argument: "" });
    expect(parseCommand("hello")).toBeNull();
  });

  it("filters slash completions", () => {
    expect(filterCommands("/re")).toEqual(["/resume", "/retry"]);
    expect(filterCommands("/")).toContain("/model");
    expect(filterCommands("/th")).toEqual(["/theme"]);
  });

  it("recognizes known commands", () => {
    expect(isKnownCommand("/context")).toBe(true);
    expect(isKnownCommand("/theme")).toBe(true);
    expect(isKnownCommand("/nope")).toBe(false);
  });
});
