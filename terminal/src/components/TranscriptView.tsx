import { Static, Text } from "ink";

import type { Tone, TranscriptLine } from "../controller";

const TONE_COLORS: Record<Tone, string | undefined> = {
  user: "cyan",
  assistant: undefined,
  tool: "gray",
  error: "red",
  dim: undefined,
  success: "green",
  warning: "yellow",
};

export function TranscriptView({ lines }: { lines: TranscriptLine[] }) {
  return (
    <Static items={lines}>
      {(line) => (
        <Text
          key={line.id}
          color={line.tone ? TONE_COLORS[line.tone] : undefined}
          dimColor={line.tone === "dim"}
        >
          {line.text}
        </Text>
      )}
    </Static>
  );
}
