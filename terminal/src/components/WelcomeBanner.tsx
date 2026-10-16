import { Box, Text } from "ink";
import type { ReactNode } from "react";

import { VERSION } from "../cli-args";
import type { TuiState } from "../controller";
import { truncateToWidth } from "../render/text";
import type { Theme } from "../theme/themes";

// Claude Code style mascot: one solid color, blocky pixels, details cut out.
const MASCOT_PIXELS = [
  "0000000000000000",
  "0001100001100000",
  "0011110011110000",
  "0011111111110000",
  "0011111111110000",
  "0111111111111000",
  "0110011110011000",
  "0110011110011000",
  "0111111111111000",
  "0111110011111000",
  "0011111111110000",
  "0000111111000000",
  "0000111111000000",
  "0000111111110000",
  "0000110011000000",
  "0000000000000000",
];

const MASCOT_COLOR = "#e5484d";
const MASCOT_WIDTH = MASCOT_PIXELS[0]?.length ?? 16;

export function WelcomeBanner({
  state,
  theme,
  width,
  maxRows,
}: {
  state: TuiState;
  theme: Theme;
  width: number;
  maxRows: number;
}) {
  if (maxRows < 4) {
    return null;
  }
  const artRows = Math.ceil(MASCOT_PIXELS.length / 2);
  const showArt = width >= MASCOT_WIDTH + 28 && maxRows >= artRows + 2;
  const textWidth = Math.max(8, width - (showArt ? MASCOT_WIDTH + 4 : 2));
  const session = Boolean(state.modelSelection?.model_id);
  const modelLabel = state.modelLabel || "unknown";
  const hint = `| Using ${modelLabel} (from ${
    session ? "this session" : "the model catalog"
  }) · /model`;

  return (
    <Box flexDirection="column">
      <Box flexDirection="row">
        {showArt ? (
          <Box flexDirection="column" marginRight={2}>
            {renderMascot()}
          </Box>
        ) : null}
        <Box flexDirection="column">
          <Text bold color={theme.tokens.claude}>
            CellWiki v{VERSION}
          </Text>
          <Text>{truncateToWidth(modelLabel, textWidth)}</Text>
          <Text color={theme.tokens.inactive}>
            {truncateToWidth(state.workspace, textWidth)}
          </Text>
        </Box>
      </Box>
      <Text color={theme.tokens.inactive}>{truncateToWidth(hint, width)}</Text>
    </Box>
  );
}

function renderMascot(): ReactNode[] {
  const rows: ReactNode[] = [];
  for (let y = 0; y < MASCOT_PIXELS.length; y += 2) {
    const topRow = MASCOT_PIXELS[y] ?? "";
    const bottomRow = MASCOT_PIXELS[y + 1] ?? "";
    const cells: ReactNode[] = [];
    for (let x = 0; x < MASCOT_WIDTH; x += 1) {
      const top = topRow[x] === "1";
      const bottom = bottomRow[x] === "1";
      if (!top && !bottom) {
        cells.push(<Text key={`${x}`}> </Text>);
      } else if (top && bottom) {
        cells.push(
          <Text key={`${x}`} color={MASCOT_COLOR}>
            █
          </Text>,
        );
      } else if (top) {
        cells.push(
          <Text key={`${x}`} color={MASCOT_COLOR}>
            ▀
          </Text>,
        );
      } else {
        cells.push(
          <Text key={`${x}`} color={MASCOT_COLOR}>
            ▄
          </Text>,
        );
      }
    }
    rows.push(<Text key={`mascot-${y}`}>{cells}</Text>);
  }
  return rows;
}
