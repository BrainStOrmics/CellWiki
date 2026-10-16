import { Box, Text, useApp, useInput } from "ink";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
} from "react";

import type { TuiController } from "../controller";
import { useSpinnerFrame } from "../render/spinner";
import { truncateToWidth } from "../render/text";
import { useTerminalSize, type TerminalSize } from "../render/use-terminal-size";
import {
  buildLiveLines,
  gateLayout,
  toVisualLines,
  windowLines,
} from "../render/viewport";
import { Composer } from "./Composer";
import { GateView } from "./GateView";
import { LiveView } from "./LiveView";
import { StatusBar } from "./StatusBar";
import { TranscriptView, toneColor } from "./TranscriptView";

export type RenderMode = "fullscreen" | "classic";

export interface AppProps {
  controller: TuiController;
  mode?: RenderMode;
  viewport?: TerminalSize;
}

export function App({ controller, mode = "fullscreen", viewport }: AppProps) {
  const state = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
  );
  const { exit } = useApp();
  const size = useTerminalSize(viewport);
  const busy = state.runId !== null || state.tools.length > 0;
  const spinner = useSpinnerFrame(mode === "fullscreen" && busy);
  const [scrollOffset, setScrollOffset] = useState(0);
  const [composerRows, setComposerRows] = useState(1);
  const handleComposerRows = useCallback(
    (rows: number) => setComposerRows(rows),
    [],
  );
  const handleSubmitted = useCallback(() => setScrollOffset(0), []);

  useEffect(() => {
    void controller.connect();
  }, [controller]);

  useEffect(() => {
    if (state.exitRequested) {
      exit();
    }
  }, [state.exitRequested, exit]);

  useEffect(() => {
    if (state.gate) {
      setScrollOffset(0);
    }
  }, [state.gate]);

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

  const layout = state.gate ? gateLayout(state.gate, size.rows) : null;
  const gateRows = layout?.rows ?? 0;
  const transcriptRows = Math.max(3, size.rows - 2 - gateRows - composerRows);
  const page = Math.max(1, Math.floor(transcriptRows / 2));

  const allLines = useMemo(
    () => [
      ...toVisualLines(state.transcript, size.columns),
      ...buildLiveLines(state, spinner, size.columns),
    ],
    [
      state.transcript,
      state.reasoning,
      state.streaming,
      state.tools,
      state.runId,
      state.verbose,
      spinner,
      size.columns,
    ],
  );
  const maxOffset = Math.max(
    0,
    allLines.length - Math.max(1, transcriptRows - 1),
  );
  const offset = Math.min(scrollOffset, maxOffset);

  useEffect(() => {
    if (offset !== scrollOffset) {
      setScrollOffset(offset);
    }
  }, [offset, scrollOffset]);

  useInput(
    (_input, key) => {
      if (key.pageUp) {
        setScrollOffset(Math.min(maxOffset, offset + page));
      } else if (key.pageDown) {
        setScrollOffset(Math.max(0, offset - page));
      } else if (key.ctrl && key.home) {
        setScrollOffset(maxOffset);
      } else if (key.ctrl && key.end) {
        setScrollOffset(0);
      }
    },
    {
      isActive:
        mode === "fullscreen" &&
        state.connected &&
        state.versionMismatch === null,
    },
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

  if (mode === "classic") {
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
        <Composer controller={controller} state={state} width={size.columns} />
        <StatusBar state={state} width={size.columns} />
      </Box>
    );
  }

  const showHint = offset > 0;
  const windowRows = showHint ? Math.max(1, transcriptRows - 1) : transcriptRows;
  const view = windowLines(allLines, windowRows, offset);
  const padding = Math.max(0, windowRows - view.lines.length);
  const hintText = `↓ ${offset} newer line${offset === 1 ? "" : "s"} · PgDn or Ctrl+End to follow`;

  return (
    <Box flexDirection="column" height={size.rows}>
      <Box
        flexDirection="column"
        height={transcriptRows}
        flexShrink={0}
        overflow="hidden"
      >
        {showHint ? (
          <Text dimColor>{truncateToWidth(hintText, size.columns)}</Text>
        ) : null}
        {Array.from({ length: padding }, (_, index) => (
          <Text key={`padding-${index}`}> </Text>
        ))}
        {view.lines.map((line, index) => (
          <Text
            key={`${index}-${line.text}`}
            color={toneColor(line.tone)}
            dimColor={line.tone === "dim"}
          >
            {line.text}
          </Text>
        ))}
      </Box>
      {state.gate && layout ? (
        <Box
          height={layout.rows}
          flexShrink={0}
          overflow="hidden"
          flexDirection="column"
        >
          <GateView
            gate={state.gate}
            width={size.columns}
            previewLines={layout.previewLines}
            maxOptions={layout.maxOptions}
            marginTop={0}
          />
        </Box>
      ) : null}
      <Box height={composerRows} flexShrink={0} overflow="hidden">
        <Composer
          controller={controller}
          state={state}
          width={size.columns}
          maxRows={Math.max(1, size.rows - 6)}
          onRowsChange={handleComposerRows}
          onSubmitted={handleSubmitted}
        />
      </Box>
      <Box height={2} flexShrink={0}>
        <StatusBar state={state} width={size.columns} />
      </Box>
    </Box>
  );
}
