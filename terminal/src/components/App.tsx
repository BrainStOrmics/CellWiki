import { Box, Text, useApp, useInput } from "ink";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

import type { TuiController } from "../controller";
import { useSpinnerFrame } from "../render/spinner";
import { padToWidth, truncateToWidth } from "../render/text";
import { useTerminalSize, type TerminalSize } from "../render/use-terminal-size";
import { useThrottledSnapshot } from "../render/use-throttled-snapshot";
import {
  buildLiveLines,
  gateLayout,
  toVisualLines,
  windowLines,
  type VisualLine,
} from "../render/viewport";
import { Composer } from "./Composer";
import { GateView } from "./GateView";
import { LiveView } from "./LiveView";
import { ModelPicker } from "./ModelPicker";
import { SessionPicker } from "./SessionPicker";
import { StatusBar } from "./StatusBar";
import { StyledText } from "./StyledText";
import { ThemePicker } from "./ThemePicker";
import { TranscriptView } from "./TranscriptView";
import { WelcomeBanner } from "./WelcomeBanner";

export type RenderMode = "fullscreen" | "classic";

export interface AppProps {
  controller: TuiController;
  mode?: RenderMode;
  viewport?: TerminalSize;
}

export function App({ controller, mode = "fullscreen", viewport }: AppProps) {
  const liveState = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
  );
  const immediate =
    !liveState.connected ||
    liveState.gate !== null ||
    liveState.picker !== null ||
    liveState.versionMismatch !== null ||
    liveState.exitRequested;
  const streaming = Boolean(liveState.streaming || liveState.reasoning);
  const state = useThrottledSnapshot(
    liveState,
    immediate || !streaming ? 0 : liveState.streaming ? 100 : 250,
  );
  const { exit } = useApp();
  const size = useTerminalSize(viewport);
  const busy = state.runId !== null || state.tools.length > 0;
  const [scrollOffset, setScrollOffset] = useState(0);
  const spinner = useSpinnerFrame(
    mode === "fullscreen" && busy && !state.gate && scrollOffset === 0,
    mode === "fullscreen" ? 1000 : 200,
  );
  const [composerRows, setComposerRows] = useState(1);
  const [composerText, setComposerText] = useState("");
  const handleComposerRows = useCallback(
    (rows: number) => setComposerRows(rows),
    [],
  );
  const handleSubmitted = useCallback(() => setScrollOffset(0), []);
  const maxOffsetRef = useRef(0);
  const handleScroll = useCallback((delta: number) => {
    setScrollOffset((value) =>
      Math.min(Math.max(0, value - delta), maxOffsetRef.current),
    );
  }, []);

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
      ...toVisualLines(state.transcript, size.columns, state.theme),
      ...buildLiveLines(state, spinner, size.columns, state.theme),
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
      state.theme,
    ],
  );
  const [frozenLines, setFrozenLines] = useState<VisualLine[] | null>(null);
  useEffect(() => {
    if (scrollOffset > 0 && frozenLines === null) {
      setFrozenLines(allLines);
      return;
    }
    if (scrollOffset === 0 && frozenLines !== null) {
      setFrozenLines(null);
    }
  }, [scrollOffset, frozenLines, allLines]);
  const displayLines = frozenLines ?? allLines;
  const maxOffset = Math.max(
    0,
    displayLines.length - Math.max(1, transcriptRows - 1),
  );
  const offset = Math.min(scrollOffset, maxOffset);

  useEffect(() => {
    maxOffsetRef.current = maxOffset;
  }, [maxOffset]);

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
        state.picker === null &&
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

  if (state.picker) {
    if (state.picker.kind === "theme") {
      return (
        <ThemePicker
          controller={controller}
          state={state}
          size={size}
          fullscreen={mode === "fullscreen"}
        />
      );
    }
    if (state.picker.kind === "model") {
      return (
        <ModelPicker
          controller={controller}
          state={state}
          size={size}
          fullscreen={mode === "fullscreen"}
        />
      );
    }
    return (
      <SessionPicker
        controller={controller}
        state={state}
        size={size}
        fullscreen={mode === "fullscreen"}
        theme={state.theme}
      />
    );
  }

  if (mode === "classic") {
    return (
      <Box flexDirection="column">
        {state.welcome ? (
          <WelcomeBanner
            state={state}
            theme={state.theme}
            width={size.columns}
            maxRows={8}
          />
        ) : null}
        <TranscriptView
          lines={state.transcript}
          width={size.columns}
          theme={state.theme}
        />
        <LiveView state={state} theme={state.theme} />
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
        {state.gate ? (
          <GateView
            gate={state.gate}
            allowSelect={composerText.length === 0}
            onSelect={(index) => {
              void controller.submit(String(index + 1));
            }}
            theme={state.theme}
          />
        ) : null}
        <Composer
          controller={controller}
          state={state}
          width={size.columns}
          onValueChange={setComposerText}
          disabled={state.gate?.kind === "diff"}
          theme={state.theme}
        />
        <StatusBar state={state} width={size.columns} theme={state.theme} />
      </Box>
    );
  }

  const showHint = offset > 0;
  const windowRows = showHint ? Math.max(1, transcriptRows - 1) : transcriptRows;
  const view = windowLines(displayLines, windowRows, offset);
  const padding = Math.max(0, windowRows - view.lines.length);
  const newLineCount = Math.max(0, allLines.length - displayLines.length);
  const hintText = `${
    newLineCount > 0 ? `+${newLineCount} new · ` : ""
  }↓ ${offset} newer line${offset === 1 ? "" : "s"} · PgDn or Ctrl+End to follow`;

  return (
    <Box flexDirection="column" height={size.rows}>
      <Box
        flexDirection="column"
        height={transcriptRows}
        flexShrink={0}
        overflow="hidden"
      >
        {state.welcome ? (
          <WelcomeBanner
            state={state}
            theme={state.theme}
            width={size.columns}
            maxRows={transcriptRows}
          />
        ) : (
          <>
            {showHint ? (
              <Text dimColor>{truncateToWidth(hintText, size.columns)}</Text>
            ) : null}
            {Array.from({ length: padding }, (_, index) => (
              <Text key={`padding-${index}`}> </Text>
            ))}
            {view.lines.map((line, index) =>
              line.tone === "user" ? (
                <Text
                  key={`${index}-${line.text}`}
                  backgroundColor={state.theme.tokens.userMessageBackground}
                  color={state.theme.tokens.inverseText}
                >
                  {padToWidth(line.text, Math.max(1, size.columns - 1))}
                </Text>
              ) : (
                <StyledText
                  key={`${index}-${line.text}`}
                  line={line}
                  theme={state.theme}
                />
              ),
            )}
          </>
        )}
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
            allowSelect={composerText.length === 0}
            onSelect={(index) => {
              void controller.submit(String(index + 1));
            }}
            theme={state.theme}
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
          onValueChange={setComposerText}
          onScroll={handleScroll}
          disabled={state.gate?.kind === "diff"}
          theme={state.theme}
        />
      </Box>
      <Box height={2} flexShrink={0}>
        <StatusBar state={state} width={size.columns} theme={state.theme} />
      </Box>
    </Box>
  );
}
