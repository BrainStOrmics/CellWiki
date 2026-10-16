import type { Tone } from "../controller";

const TONE_COLORS: Record<Tone, string | undefined> = {
  user: "cyan",
  assistant: undefined,
  tool: "gray",
  error: "red",
  dim: undefined,
  success: "green",
  warning: "yellow",
};

export function toneColor(tone: Tone | undefined): string | undefined {
  return tone ? TONE_COLORS[tone] : undefined;
}
