import { Box, Text } from "ink";

import { VERSION } from "../cli-args";
import type { TuiState } from "../controller";
import { truncateToWidth } from "../render/text";
import type { Theme } from "../theme/themes";

interface CatSegment {
  text: string;
  role: "body" | "eye" | "ruff";
}

// Terminal mascot: the black cat with the red ruff and amber eyes.
const CAT_ART: CatSegment[][] = [
  [{ text: "    /\\_/\\    ", role: "body" }],
  [
    { text: "   ( ", role: "body" },
    { text: "◉", role: "eye" },
    { text: "   ", role: "body" },
    { text: "◉", role: "eye" },
    { text: " )   ", role: "body" },
  ],
  [{ text: "    >  ^  <    ", role: "body" }],
  [{ text: "  ▄▀▄▀▄▀▄▀▄  ", role: "ruff" }],
  [{ text: "   ▐█████▌   ", role: "body" }],
  [{ text: "    ▀▀ ▀▀    ", role: "body" }],
];

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
  const showArt = maxRows >= 8 && width >= 40;
  const textWidth = Math.max(8, width - (showArt ? 18 : 2));
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
            {CAT_ART.map((line, index) => (
              <Text key={`cat-${index}`}>
                {line.map((segment, segmentIndex) => (
                  <Text
                    key={`${index}-${segmentIndex}`}
                    color={roleColor(theme, segment.role)}
                  >
                    {segment.text}
                  </Text>
                ))}
              </Text>
            ))}
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

function roleColor(
  theme: Theme,
  role: CatSegment["role"],
): string | undefined {
  switch (role) {
    case "eye":
      return theme.tokens.warning;
    case "ruff":
      return theme.tokens.error;
    default:
      return theme.tokens.inactive;
  }
}
