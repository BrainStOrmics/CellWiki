import { Text } from "ink";

import type { VisualLine } from "../render/viewport";
import { toneColor, type Theme } from "../theme/themes";

export function StyledText({
  line,
  theme,
}: {
  line: VisualLine;
  theme: Theme;
}) {
  const segments = line.segments ?? [{ text: line.text }];
  return (
    <Text color={toneColor(theme, line.tone)} dimColor={line.tone === "dim"}>
      {segments.map((segment, index) => (
        <Text
          key={`${index}-${segment.text}`}
          bold={segment.bold}
          italic={segment.italic}
          dimColor={segment.dim}
          underline={segment.underline}
          color={
            segment.color ??
            (segment.code
              ? theme.tokens.code
              : segment.accent
                ? theme.tokens.claude
                : undefined)
          }
        >
          {segment.text}
        </Text>
      ))}
    </Text>
  );
}
