import { Box, Text } from "ink";

import type { TuiState } from "../controller";

export function StatusBar({ state }: { state: TuiState }) {
  const parts = ["cellwiki", `model ${state.modelLabel}`];
  if (state.threadTitle) {
    parts.push(truncateDisplayWidth(state.threadTitle, 12));
  }
  parts.push(`run ${state.runStatus}`);
  if (state.contextLabel) {
    parts.push(state.contextLabel);
  }
  if (state.usageLabel) {
    parts.push(state.usageLabel);
  }
  if (state.queue.length > 0) {
    parts.push(`queued ${state.queue.length}`);
  }
  if (state.pendingDiffId && !state.gate) {
    parts.push(`diff ${state.pendingDiffId} (/diff)`);
  }
  if (state.verbose) {
    parts.push("verbose");
  }
  return (
    <Box marginTop={1}>
      <Text dimColor>{parts.join("  ·  ")}</Text>
    </Box>
  );
}

function truncateDisplayWidth(value: string, limit: number): string {
  let width = 0;
  let result = "";
  for (const character of value) {
    width += isWide(character) ? 2 : 1;
    if (width > limit) {
      return `${result}…`;
    }
    result += character;
  }
  return result;
}

function isWide(character: string): boolean {
  const code = character.codePointAt(0) ?? 0;
  return (
    (code >= 0x1100 && code <= 0x115f) ||
    (code >= 0x2e80 && code <= 0xa4cf) ||
    (code >= 0xac00 && code <= 0xd7a3) ||
    (code >= 0xf900 && code <= 0xfaff) ||
    (code >= 0xfe30 && code <= 0xfe6f) ||
    (code >= 0xff00 && code <= 0xff60) ||
    (code >= 0xffe0 && code <= 0xffe6)
  );
}
