import { Box, Text } from "ink";

import type { TuiState } from "../controller";
import { displayWidth, truncateToWidth } from "../render/text";
import type { Theme } from "../theme/themes";

interface StatusPart {
  text: string;
  optional?: boolean;
}

export function StatusBar({
  state,
  width = 80,
  theme,
}: {
  state: TuiState;
  width?: number;
  theme: Theme;
}) {
  const parts: StatusPart[] = [
    { text: "cellwiki" },
    { text: `model ${state.modelLabel}` },
  ];
  if (state.threadTitle) {
    parts.push({ text: truncateToWidth(state.threadTitle, 12), optional: true });
  }
  parts.push({ text: `run ${state.runStatus}` });
  if (state.contextLabel) {
    parts.push({ text: state.contextLabel });
  }
  if (state.usageLabel) {
    parts.push({ text: state.usageLabel, optional: true });
  }
  if (state.queue.length > 0) {
    parts.push({ text: `queued ${state.queue.length}`, optional: true });
  }
  if (state.pendingDiffId && !state.gate) {
    parts.push({
      text: `diff ${state.pendingDiffId} (/diff)`,
      optional: true,
    });
  }
  if (state.verbose) {
    parts.push({ text: "verbose", optional: true });
  }

  let text = joinParts(parts);
  while (displayWidth(text) > width - 1) {
    const index = lastOptionalIndex(parts);
    if (index < 0) {
      break;
    }
    parts.splice(index, 1);
    text = joinParts(parts);
  }

  return (
    <Box marginTop={1}>
      <Text color={theme.tokens.inactive}>
        {truncateToWidth(text, Math.max(1, width - 1))}
      </Text>
    </Box>
  );
}

function joinParts(parts: StatusPart[]): string {
  return parts.map((part) => part.text).join("  ·  ");
}

function lastOptionalIndex(parts: StatusPart[]): number {
  for (let index = parts.length - 1; index >= 0; index -= 1) {
    if (parts[index]?.optional) {
      return index;
    }
  }
  return -1;
}
