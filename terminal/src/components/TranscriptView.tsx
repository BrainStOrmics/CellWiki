import { Box, Static, Text } from "ink";

import type { Tone, TranscriptLine } from "../controller";
import { displayWidth, padToWidth, wrapToWidth } from "../render/text";
import { transcriptPrefix } from "../render/viewport";

const TONE_COLORS: Record<Tone, string | undefined> = {
  user: "cyan",
  assistant: undefined,
  tool: "gray",
  error: "red",
  dim: undefined,
  success: "green",
  warning: "yellow",
};

export function toneColor(tone: Tone | undefined): string | undefined {
  return tone ? TONE_COLORS[tone] : undefined;
}

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
        const prefix = transcriptPrefix(line.tone);
        const bodyWidth = Math.max(1, width - displayWidth(prefix));
        const wrapped = wrapToWidth(line.text, bodyWidth);
        return (
          <Box key={line.id} flexDirection="column">
            {wrapped.map((text, index) => {
              const lead = index === 0 ? prefix : prefix ? "  " : "";
              const value = `${lead}${text}`;
              if (line.tone === "user") {
                return (
                  <Text key={`${line.id}-${index}`} backgroundColor="gray">
                    {padToWidth(value, Math.max(1, width - 1))}
                  </Text>
                );
              }
              return (
                <Text
                  key={`${line.id}-${index}`}
                  color={toneColor(line.tone)}
                  dimColor={line.tone === "dim"}
                >
                  {value}
                </Text>
              );
            })}
          </Box>
        );
      }}
    </Static>
  );
}
