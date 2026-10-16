import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import {
  findTheme,
  isLightBackground,
  themeChoices,
  THEME_PRESETS,
} from "../src/theme/themes";
import { createThemeStore, initialThemeId } from "../src/theme/store";

describe("theme presets", () => {
  it("ships the Claude Code preset family", () => {
    expect(THEME_PRESETS.map((theme) => theme.id)).toEqual([
      "dark",
      "light",
      "dark-daltonized",
      "light-daltonized",
      "dark-ansi",
      "light-ansi",
    ]);
  });

  it("falls back to dark for unknown ids", () => {
    expect(findTheme("nope").id).toBe("dark");
  });

  it("detects a light background from COLORFGBG", () => {
    expect(isLightBackground({ COLORFGBG: "0;15" })).toBe(true);
    expect(isLightBackground({ COLORFGBG: "15;0" })).toBe(false);
    expect(isLightBackground({})).toBe(false);
  });

  it("prepends the auto choice resolved for the terminal", () => {
    const choices = themeChoices({ COLORFGBG: "0;15" });
    expect(choices[0]?.id).toBe("auto");
    expect(choices[0]?.dark).toBe(false);
    expect(choices[0]?.tokens.claude).toBe(findTheme("light").tokens.claude);
  });

  it("keeps daltonized error and success distinct from dark", () => {
    const dark = findTheme("dark");
    const daltonized = findTheme("dark-daltonized");
    expect(daltonized.tokens.error).not.toBe(dark.tokens.error);
    expect(daltonized.tokens.success).not.toBe(dark.tokens.success);
  });
});

describe("theme store", () => {
  it("round-trips the saved theme", () => {
    const dir = mkdtempSync(join(tmpdir(), "cellwiki-theme-"));
    const file = join(dir, "tui.json");
    const store = createThemeStore(file);
    expect(store.load()).toBeNull();
    store.save("light-daltonized");
    expect(store.load()).toBe("light-daltonized");
    expect(JSON.parse(readFileSync(file, "utf8"))).toEqual({
      theme: "light-daltonized",
    });
  });

  it("prefers the env override and defaults to auto", () => {
    const store = { load: () => "light", save: () => undefined };
    expect(initialThemeId(store, { CELLWIKI_TUI_THEME: "dark-ansi" })).toBe(
      "dark-ansi",
    );
    expect(initialThemeId(store, {})).toBe("light");
    expect(initialThemeId({ load: () => null, save: () => undefined }, {})).toBe(
      "auto",
    );
  });
});
