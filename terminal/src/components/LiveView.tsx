import { Box } from "ink";

import type { TuiState } from "../controller";
import { useSpinnerFrame } from "../render/spinner";
import { buildLiveLines } from "../render/viewport";
import type { Theme } from "../theme/themes";
import { StyledText } from "./StyledText";

export function LiveView({
  state,
  width = 80,
  theme,
}: {
  state: TuiState;
  width?: number;
  theme: Theme;
}) {
  const busy = state.runId !== null || state.tools.length > 0;
  const spinner = useSpinnerFrame(busy);
  const lines = buildLiveLines(state, spinner, width, theme);
  if (lines.length === 0) {
    return null;
  }
  return (
    <Box flexDirection="column">
      {lines.map((line, index) => (
        <StyledText key={`${index}-${line.text}`} line={line} theme={theme} />
      ))}
    </Box>
  );
}
