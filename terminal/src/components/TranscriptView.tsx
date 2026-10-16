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

export function toneColor(tone: Tone | undefined): string | undefined {
  return tone ? TONE_COLORS[tone] : undefined;
}

export function TranscriptView({ lines }: { lines: TranscriptLine[] }) {
  return (
    <Static items={lines}>
      {(line) => (
        <Text
          key={line.id}
          color={toneColor(line.tone)}
          dimColor={line.tone === "dim"}
        >
          {line.text}
        </Text>
      )}
    </Static>
  );
}
