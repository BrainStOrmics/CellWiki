import { Box, Static, Text } from "ink";

import type { TranscriptLine } from "../controller";
import { padToWidth } from "../render/text";
import { toVisualLines } from "../render/viewport";
import { StyledText } from "./StyledText";

export function TranscriptView({
  lines,
  width = 80,
}: {
  lines: TranscriptLine[];
  width?: number;
}) {
  return (
    <Static items={lines}>
      {(line) => {
        const visual = toVisualLines([line], width);
        return (
          <Box key={line.id} flexDirection="column">
            {visual.map((visualLine, index) =>
              visualLine.tone === "user" ? (
                <Text key={index} backgroundColor="gray">
                  {padToWidth(visualLine.text, Math.max(1, width - 1))}
                </Text>
              ) : (
                <StyledText key={index} line={visualLine} />
              ),
            )}
          </Box>
        );
      }}
    </Static>
  );
}
