import { Box, Text, useApp, useInput } from "ink";
import { useEffect, useSyncExternalStore } from "react";

import type { TuiController } from "../controller";
import { Composer } from "./Composer";
import { GateView } from "./GateView";
import { LiveView } from "./LiveView";
import { StatusBar } from "./StatusBar";
import { TranscriptView } from "./TranscriptView";

export interface AppProps {
  controller: TuiController;
}

export function App({ controller }: AppProps) {
  const state = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
  );
  const { exit } = useApp();

  useEffect(() => {
    void controller.connect();
  }, [controller]);

  useEffect(() => {
    if (state.exitRequested) {
      exit();
    }
  }, [state.exitRequested, exit]);

  useInput(
    (input) => {
      if (input === "r") {
        void controller.restart();
      }
      if (input === "q") {
        controller.requestExit();
      }
    },
    { isActive: state.versionMismatch !== null },
  );

  if (state.versionMismatch) {
    return (
      <Box flexDirection="column">
        <Text color="yellow">{state.versionMismatch.message}</Text>
        <Text>r restart daemon · q quit</Text>
      </Box>
    );
  }

  if (!state.connected) {
    return (
      <Text color={state.error ? "red" : "yellow"}>
        {state.error ??
          (state.connecting
            ? "connecting to the CellWiki daemon..."
            : "waiting for the CellWiki daemon...")}
      </Text>
    );
  }

  return (
    <Box flexDirection="column">
      <TranscriptView lines={state.transcript} />
      <LiveView state={state} />
      {state.verbose && state.toolHistory.length > 0 ? (
        <Box flexDirection="column">
          {state.toolHistory.slice(-5).map((tool) => (
            <Text key={`detail-${tool.id}`} dimColor>
              {tool.status === "failed" ? "x" : "+"} {tool.name}:{" "}
              {tool.result ?? tool.summary}
            </Text>
          ))}
        </Box>
      ) : null}
      {state.gate ? <GateView gate={state.gate} /> : null}
      <Composer controller={controller} state={state} />
      <StatusBar state={state} />
    </Box>
  );
}
