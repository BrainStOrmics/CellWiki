import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

import { DEFAULT_THEME_ID } from "./themes";

export interface ThemeStore {
  load(): string | null;
  save(themeId: string): void;
}

export function defaultThemeConfigPath(): string {
  return join(homedir(), ".cellwiki", "tui.json");
}

export function createThemeStore(
  filePath: string = defaultThemeConfigPath(),
): ThemeStore {
  return {
    load(): string | null {
      try {
        const payload = JSON.parse(readFileSync(filePath, "utf8")) as {
          theme?: unknown;
        };
        return typeof payload.theme === "string" && payload.theme
          ? payload.theme
          : null;
      } catch {
        return null;
      }
    },
    save(themeId: string): void {
      try {
        mkdirSync(dirname(filePath), { recursive: true });
        writeFileSync(
          filePath,
          `${JSON.stringify({ theme: themeId }, null, 2)}\n`,
          "utf8",
        );
      } catch {
        // Persisting the theme is best effort.
      }
    },
  };
}

export function initialThemeId(
  store: ThemeStore,
  env: NodeJS.ProcessEnv = process.env,
): string {
  const fromEnv = (env.CELLWIKI_TUI_THEME ?? "").trim();
  if (fromEnv) {
    return fromEnv;
  }
  return store.load() ?? DEFAULT_THEME_ID;
}
