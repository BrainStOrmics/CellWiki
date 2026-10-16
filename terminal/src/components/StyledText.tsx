import { Text } from "ink";

import { toneColor } from "../render/tone";
import type { VisualLine } from "../render/viewport";

export function StyledText({ line }: { line: VisualLine }) {
  const segments = line.segments ?? [{ text: line.text }];
  return (
    <Text color={toneColor(line.tone)} dimColor={line.tone === "dim"}>
      {segments.map((segment, index) => (
        <Text
          key={`${index}-${segment.text}`}
          bold={segment.bold}
          italic={segment.italic}
          dimColor={segment.dim}
          underline={segment.underline}
          color={segment.color}
        >
          {segment.text}
        </Text>
      ))}
    </Text>
  );
}
