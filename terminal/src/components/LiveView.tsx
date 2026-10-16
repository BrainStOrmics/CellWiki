import { Box, Text } from "ink";
import { useEffect, useState } from "react";

import type { TuiState } from "../controller";

const FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

export function LiveView({ state }: { state: TuiState }) {
  const [frame, setFrame] = useState(0);
  const busy = state.runId !== null || state.tools.length > 0;

  useEffect(() => {
    if (!busy) {
      return;
    }
    const timer = setInterval(() => {
      setFrame((value) => value + 1);
    }, 120);
    return () => clearInterval(timer);
  }, [busy]);

  const spinner = FRAMES[frame % FRAMES.length] ?? FRAMES[0];

  return (
    <Box flexDirection="column">
      {state.reasoning ? (
        <Text dimColor>
          ✻ {state.reasoning}
        </Text>
      ) : null}
      {state.streaming ? <Text>{state.streaming}</Text> : null}
      {state.tools.map((tool) => (
        <Text key={tool.id} color="yellow">
          {spinner} {tool.summary}
        </Text>
      ))}
      {busy && !state.streaming && !state.reasoning && state.tools.length === 0 ? (
        <Text dimColor>
          {spinner} working… (Esc to interrupt)
        </Text>
      ) : null}
    </Box>
  );
}
