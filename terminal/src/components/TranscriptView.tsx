import { Box, Static, Text } from "ink";

import type { TranscriptLine } from "../controller";
import { padToWidth } from "../render/text";
import { toVisualLines } from "../render/viewport";
import type { Theme } from "../theme/themes";
import { StyledText } from "./StyledText";

export function TranscriptView({
  lines,
  width = 80,
  theme,
}: {
  lines: TranscriptLine[];
  width?: number;
  theme: Theme;
}) {
  return (
    <Static items={lines}>
      {(line) => {
        const visual = toVisualLines([line], width, theme);
        return (
          <Box key={line.id} flexDirection="column">
            {visual.map((visualLine, index) =>
              visualLine.tone === "user" ? (
                <Text
                  key={index}
                  backgroundColor={theme.tokens.userMessageBackground}
                  color={theme.tokens.inverseText}
                >
                  {padToWidth(visualLine.text, Math.max(1, width - 1))}
                </Text>
              ) : (
                <StyledText key={index} line={visualLine} theme={theme} />
              ),
            )}
          </Box>
        );
      }}
    </Static>
  );
}
