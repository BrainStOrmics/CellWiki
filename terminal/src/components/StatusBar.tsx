import { Box, Text } from "ink";

import type { TuiState } from "../controller";

export function StatusBar({ state }: { state: TuiState }) {
  const parts = ["cellwiki", `model ${state.modelLabel}`];
  if (state.threadTitle) {
    parts.push(state.threadTitle);
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
