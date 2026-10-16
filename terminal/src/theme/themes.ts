import type { Tone } from "../controller";

export interface ThemeTokens {
  /** Primary brand accent: spinner, assistant bullet, picker cursor, titles. */
  claude: string;
  /** Secondary text such as hints, timestamps and disabled items. */
  inactive: string;
  /** Faint borders. */
  subtle: string;
  /** Autocomplete and menu selection accent. */
  suggestion: string;
  error: string;
  success: string;
  warning: string;
  diffAdded: string;
  diffRemoved: string;
  /** Inline code and code blocks. */
  code: string;
  userMessageBackground: string;
  /** Text drawn on top of a colored background. */
  inverseText: string;
  tool: string;
  thinking: string;
}

export interface Theme {
  id: string;
  label: string;
  description: string;
  dark: boolean;
  tokens: ThemeTokens;
}

export const THEME_PRESETS: Theme[] = [
  {
    id: "dark",
    label: "Dark",
    description: "default dark terminal",
    dark: true,
    tokens: {
      claude: "#B1B9F9",
      inactive: "gray",
      subtle: "#4b5563",
      suggestion: "#7dd3fc",
      error: "#f87171",
      success: "#4ade80",
      warning: "#fbbf24",
      diffAdded: "#4ade80",
      diffRemoved: "#f87171",
      code: "#B1B9F9",
      userMessageBackground: "#3a3a3a",
      inverseText: "#f5f5f5",
      tool: "gray",
      thinking: "gray",
    },
  },
  {
    id: "light",
    label: "Light",
    description: "light terminal background",
    dark: false,
    tokens: {
      claude: "#7C3AED",
      inactive: "#6b7280",
      subtle: "#d1d5db",
      suggestion: "#1d4ed8",
      error: "#b91c1c",
      success: "#15803d",
      warning: "#b45309",
      diffAdded: "#15803d",
      diffRemoved: "#b91c1c",
      code: "#6D28D9",
      userMessageBackground: "#e5e7eb",
      inverseText: "#111827",
      tool: "#6b7280",
      thinking: "#6b7280",
    },
  },
  {
    id: "dark-daltonized",
    label: "Dark daltonized",
    description: "dark, red/green replaced by blue/amber",
    dark: true,
    tokens: {
      claude: "#a78bfa",
      inactive: "gray",
      subtle: "#4b5563",
      suggestion: "#60a5fa",
      error: "#fbbf24",
      success: "#60a5fa",
      warning: "#f472b6",
      diffAdded: "#60a5fa",
      diffRemoved: "#fbbf24",
      code: "#93c5fd",
      userMessageBackground: "#3a3a3a",
      inverseText: "#f5f5f5",
      tool: "gray",
      thinking: "gray",
    },
  },
  {
    id: "light-daltonized",
    label: "Light daltonized",
    description: "light, red/green replaced by blue/amber",
    dark: false,
    tokens: {
      claude: "#7c3aed",
      inactive: "#6b7280",
      subtle: "#d1d5db",
      suggestion: "#1d4ed8",
      error: "#b45309",
      success: "#1d4ed8",
      warning: "#a21caf",
      diffAdded: "#1d4ed8",
      diffRemoved: "#b45309",
      code: "#1d4ed8",
      userMessageBackground: "#e5e7eb",
      inverseText: "#111827",
      tool: "#6b7280",
      thinking: "#6b7280",
    },
  },
  {
    id: "dark-ansi",
    label: "Dark ANSI",
    description: "dark, 16 ANSI colors only",
    dark: true,
    tokens: {
      claude: "cyanBright",
      inactive: "gray",
      subtle: "gray",
      suggestion: "cyan",
      error: "redBright",
      success: "greenBright",
      warning: "yellowBright",
      diffAdded: "greenBright",
      diffRemoved: "redBright",
      code: "cyan",
      userMessageBackground: "blackBright",
      inverseText: "white",
      tool: "gray",
      thinking: "gray",
    },
  },
  {
    id: "light-ansi",
    label: "Light ANSI",
    description: "light, 16 ANSI colors only",
    dark: false,
    tokens: {
      claude: "blue",
      inactive: "gray",
      subtle: "gray",
      suggestion: "blueBright",
      error: "red",
      success: "green",
      warning: "yellow",
      diffAdded: "green",
      diffRemoved: "red",
      code: "blue",
      userMessageBackground: "whiteBright",
      inverseText: "black",
      tool: "gray",
      thinking: "gray",
    },
  },
];

export const DEFAULT_THEME_ID = "auto";

export function themeChoices(
  env: NodeJS.ProcessEnv = process.env,
): Theme[] {
  const resolved = resolveTheme("auto", env);
  return [
    {
      ...resolved,
      id: "auto",
      label: "Auto",
      description: "follow the terminal background",
    },
    ...THEME_PRESETS,
  ];
}

export function isLightBackground(
  env: NodeJS.ProcessEnv = process.env,
): boolean {
  const colorfgbg = env.COLORFGBG ?? "";
  const parts = colorfgbg.split(";").filter(Boolean);
  const background = Number(parts.at(-1));
  if (!Number.isFinite(background) || background < 0) {
    return false;
  }
  return background >= 7;
}

export function resolveTheme(
  id: string,
  env: NodeJS.ProcessEnv = process.env,
): Theme {
  if (id === "auto") {
    return findTheme(isLightBackground(env) ? "light" : "dark");
  }
  return findTheme(id);
}

export function findTheme(id: string): Theme {
  return (
    THEME_PRESETS.find((theme) => theme.id === id) ??
    THEME_PRESETS.find((theme) => theme.id === "dark")!
  );
}

export function toneColor(
  theme: Theme,
  tone: Tone | undefined,
): string | undefined {
  switch (tone) {
    case "user":
      return theme.tokens.suggestion;
    case "tool":
      return theme.tokens.tool;
    case "error":
      return theme.tokens.error;
    case "success":
      return theme.tokens.success;
    case "warning":
      return theme.tokens.warning;
    case "dim":
      return undefined;
    default:
      return undefined;
  }
}
