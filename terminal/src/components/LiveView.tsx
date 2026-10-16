import { Box, Text } from "ink";

import type { TuiState } from "../controller";
import { useSpinnerFrame } from "../render/spinner";
import { buildLiveLines } from "../render/viewport";
import { toneColor } from "./TranscriptView";

export function LiveView({
  state,
  width = 80,
}: {
  state: TuiState;
  width?: number;
}) {
  const busy = state.runId !== null || state.tools.length > 0;
  const spinner = useSpinnerFrame(busy);
  const lines = buildLiveLines(state, spinner, width);
  if (lines.length === 0) {
    return null;
  }
  return (
    <Box flexDirection="column">
      {lines.map((line, index) => (
        <Text
          key={`${index}-${line.text}`}
          color={toneColor(line.tone)}
          dimColor={line.tone === "dim"}
        >
          {line.text}
        </Text>
      ))}
    </Box>
  );
}
