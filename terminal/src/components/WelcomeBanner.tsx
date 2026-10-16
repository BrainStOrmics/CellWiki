import { Box, Text } from "ink";
import type { ReactNode } from "react";

import { VERSION } from "../cli-args";
import type { TuiState } from "../controller";
import { truncateToWidth } from "../render/text";
import type { Theme } from "../theme/themes";

// The mascot is traced from the reference art at 24x24 pixels and drawn with
// half blocks: two vertical pixels per terminal cell.
const MASCOT_PIXELS = [
  "000000000000000000000000",
  "000000000000000000000000",
  "000000011000001100000000",
  "000000151000151000000000",
  "000001551333155100000000",
  "000023111111111132000000",
  "000074111111111143000000",
  "000033111111111143200000",
  "000033111111111143200000",
  "000074111111111143000000",
  "000074122211222143000000",
  "000074161211612143000000",
  "000074121211212143000000",
  "000023411155111432000000",
  "000002345511554320000000",
  "000000754344341500000000",
  "000000215454451170000000",
  "000000714414441110000000",
  "000000141314414112000000",
  "000007141511515117000000",
  "000071411111111411700000",
  "000074771117111241100000",
  "000000007170712000000000",
  "000000000000000000000000",
];

const MASCOT_COLORS: Record<string, string | null> = {
  "0": null,
  "1": "#454545",
  "2": "#f2e3b3",
  "3": "#e8402a",
  "4": "#96231c",
  "5": "#6b3a2c",
  "6": "#ffffff",
  "7": "#8a8a8a",
};

const MASCOT_WIDTH = MASCOT_PIXELS[0]?.length ?? 24;

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
  const showArt =
    width >= MASCOT_WIDTH + 28 && maxRows >= artRows + 2;
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
            {renderMascot(theme)}
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

function renderMascot(theme: Theme): ReactNode[] {
  const body = theme.dark ? "#454545" : "#2b2b2b";
  const edge = theme.dark ? "#8a8a8a" : "#6b6b6b";
  const colorFor = (index: string | undefined): string | null => {
    const key = index ?? "0";
    if (key === "1") {
      return body;
    }
    if (key === "7") {
      return edge;
    }
    return MASCOT_COLORS[key] ?? null;
  };

  const rows: ReactNode[] = [];
  for (let y = 0; y < MASCOT_PIXELS.length; y += 2) {
    const topRow = MASCOT_PIXELS[y] ?? "";
    const bottomRow = MASCOT_PIXELS[y + 1] ?? "";
    const cells: ReactNode[] = [];
    for (let x = 0; x < MASCOT_WIDTH; x += 1) {
      const top = colorFor(topRow[x]);
      const bottom = colorFor(bottomRow[x]);
      if (!top && !bottom) {
        cells.push(<Text key={`${x}`}> </Text>);
      } else if (top && !bottom) {
        cells.push(
          <Text key={`${x}`} color={top}>
            ▀
          </Text>,
        );
      } else if (!top && bottom) {
        cells.push(
          <Text key={`${x}`} color={bottom}>
            ▄
          </Text>,
        );
      } else {
        cells.push(
          <Text
            key={`${x}`}
            color={top ?? undefined}
            backgroundColor={bottom ?? undefined}
          >
            ▀
          </Text>,
        );
      }
    }
    rows.push(<Text key={`mascot-${y}`}>{cells}</Text>);
  }
  return rows;
}
