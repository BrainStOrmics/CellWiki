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
    }, 200);
    return () => clearInterval(timer);
  }, [busy]);

  const spinner = FRAMES[frame % FRAMES.length] ?? FRAMES[0];
  const reasoningTail =
    state.reasoning
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .at(-1) ?? "";

  return (
    <Box flexDirection="column">
      {state.reasoning ? (
        <Text dimColor>
          {state.verbose
            ? `✻ ${state.reasoning.split("\n").slice(-12).join("\n")}`
            : `✻ Thinking… ${reasoningTail.slice(-120)}`}
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
