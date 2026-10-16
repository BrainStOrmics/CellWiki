import { Box, Text, useInput } from "ink";
import { useEffect, useMemo, useRef, useState } from "react";

import { filterCommands } from "../commands";
import type { TuiController, TuiState } from "../controller";
import { displayWidth, truncateToWidth } from "../render/text";

export interface ComposerProps {
  controller: TuiController;
  state: TuiState;
  width?: number;
  maxRows?: number;
  onRowsChange?: (rows: number) => void;
  onSubmitted?: () => void;
  onValueChange?: (value: string) => void;
  onScroll?: (delta: number) => void;
}

interface MentionMatch {
  start: number;
  query: string;
}

function activeMention(value: string): MentionMatch | null {
  const at = value.lastIndexOf("@");
  if (at < 0) {
    return null;
  }
  const tail = value.slice(at + 1);
  if (tail.includes(" ") || tail.includes("\n")) {
    return null;
  }
  return { start: at, query: tail };
}

export function Composer({
  controller,
  state,
  width = 80,
  maxRows = 12,
  onRowsChange,
  onSubmitted,
  onValueChange,
  onScroll,
}: ComposerProps) {
  const [value, setValue] = useState("");
  const [menuIndex, setMenuIndex] = useState(0);
  const [history, setHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const valueRef = useRef("");
  const updateValue = (
    next: string | ((current: string) => string),
  ): void => {
    const resolved =
      typeof next === "function" ? next(valueRef.current) : next;
    valueRef.current = resolved;
    setValue(resolved);
    onValueChange?.(resolved);
  };

  const gate = state.gate;
  const slashMatches = useMemo(
    () =>
      !gate && value.startsWith("/") && !value.includes(" ")
        ? filterCommands(value)
        : [],
    [gate, value],
  );
  const mention = useMemo(
    () => (!gate ? activeMention(value) : null),
    [gate, value],
  );
  const mentionMatches = useMemo(
    () => (mention ? controller.mentionCandidates(mention.query) : []),
    [controller, mention],
  );
  const menuItems: string[] =
    slashMatches.length > 0 ? slashMatches : mentionMatches;
  const menuKind: "slash" | "mention" | null =
    slashMatches.length > 0
      ? "slash"
      : mentionMatches.length > 0
        ? "mention"
        : null;

  const lines = value.split("\n");
  const extraLines = Math.max(0, lines.length - 1);
  const visibleExtraLines = Math.min(extraLines, 2);
  const overflowLine = extraLines > visibleExtraLines ? 1 : 0;
  const contentRows = 1 + visibleExtraLines + overflowLine;
  const queueRows = state.queue.length > 0 ? 1 : 0;
  // Two extra rows for the input box borders.
  const baseRows = contentRows + 2 + queueRows;
  const menuCapacity = menuKind
    ? Math.max(0, Math.max(1, maxRows) - baseRows - 1)
    : 0;
  const visibleMenuCount = Math.min(menuItems.length, 6, menuCapacity);
  const activeMenu = menuKind && visibleMenuCount > 0 ? menuKind : null;
  const menuIndexSafe =
    menuItems.length > 0 ? Math.min(menuIndex, menuItems.length - 1) : 0;
  const menuStart = Math.min(
    Math.max(0, menuIndexSafe - Math.floor(visibleMenuCount / 2)),
    Math.max(0, menuItems.length - visibleMenuCount),
  );
  const visibleMenuItems = menuItems.slice(
    menuStart,
    menuStart + visibleMenuCount,
  );
  const menuRows = activeMenu ? 1 + visibleMenuCount : 0;
  const rows = Math.min(baseRows + menuRows, Math.max(1, maxRows));

  useEffect(() => {
    onRowsChange?.(rows);
  }, [rows, onRowsChange]);

  const completeMenu = (): void => {
    const item = menuItems[menuIndexSafe];
    if (!item) {
      return;
    }
    const current = valueRef.current;
    if (menuKind === "slash") {
      updateValue(`${item} `);
    } else if (mention) {
      updateValue(`${current.slice(0, mention.start)}@${item} `);
    }
    setMenuIndex(0);
  };

  const submitCurrent = (): void => {
    const current = valueRef.current;
    if (activeMenu) {
      const item = menuItems[menuIndexSafe];
      const exactSlash =
        activeMenu === "slash" &&
        item !== undefined &&
        current.trim() === item;
      if (!exactSlash) {
        completeMenu();
        return;
      }
    }
    const message = current;
    updateValue("");
    setMenuIndex(0);
    setHistoryIndex(-1);
    if (message.trim()) {
      setHistory((historyItems) => [...historyItems, message]);
      onSubmitted?.();
      void controller.submit(message);
    }
  };

  const navigateHistory = (direction: -1 | 1): void => {
    if (history.length === 0) {
      return;
    }
    if (direction < 0) {
      const next =
        historyIndex < 0
          ? history.length - 1
          : Math.max(0, historyIndex - 1);
      setHistoryIndex(next);
      updateValue(history[next] ?? "");
      return;
    }
    if (historyIndex < 0) {
      return;
    }
    const next = historyIndex + 1;
    if (next >= history.length) {
      setHistoryIndex(-1);
      updateValue("");
      return;
    }
    setHistoryIndex(next);
    updateValue(history[next] ?? "");
  };

  useInput((input, key) => {
    if (key.escape) {
      void controller.escape();
      return;
    }
    if (key.ctrl && input === "o") {
      controller.toggleVerbose();
      return;
    }
    if (gate?.kind === "diff") {
      if (input === "1" || input === "2" || input === "3") {
        void controller.submit(input);
      }
      return;
    }
    if (key.return) {
      const current = valueRef.current;
      if (current.endsWith("\\") && !current.endsWith("\\\\")) {
        updateValue(`${current.slice(0, -1)}\n`);
        return;
      }
      submitCurrent();
      return;
    }
    if (key.tab && activeMenu) {
      completeMenu();
      return;
    }
    if (key.upArrow) {
      if (gate?.kind === "question") {
        return;
      }
      if (activeMenu && menuItems.length > 0) {
        setMenuIndex(
          (current) => (current - 1 + menuItems.length) % menuItems.length,
        );
        return;
      }
      if (onScroll) {
        onScroll(-1);
        return;
      }
      navigateHistory(-1);
      return;
    }
    if (key.downArrow) {
      if (gate?.kind === "question") {
        return;
      }
      if (activeMenu && menuItems.length > 0) {
        setMenuIndex((current) => (current + 1) % menuItems.length);
        return;
      }
      if (onScroll) {
        onScroll(1);
        return;
      }
      navigateHistory(1);
      return;
    }
    if (key.ctrl && input === "p") {
      navigateHistory(-1);
      return;
    }
    if (key.ctrl && input === "n") {
      navigateHistory(1);
      return;
    }
    if (key.ctrl && input === "u") {
      if (state.queue.length > 0) {
        const queued = controller.withdrawQueued();
        if (queued) {
          updateValue(queued);
        }
      }
      return;
    }
    if (key.backspace || key.delete) {
      updateValue((current) => current.slice(0, -1));
      return;
    }
    if (key.ctrl || key.meta) {
      return;
    }
    if (input && !input.includes("\u001b")) {
      const normalized = input.replace(/\r/g, "\n");
      const newlineIndex = normalized.indexOf("\n");
      if (newlineIndex >= 0) {
        const text = normalized.slice(0, newlineIndex);
        if (text) {
          updateValue((current) => current + text);
        }
        submitCurrent();
        const rest = normalized.slice(newlineIndex + 1);
        if (rest) {
          updateValue(rest);
        }
        return;
      }
      updateValue((current) => current + input);
    }
  });

  const innerWidth = Math.max(4, width - 4);
  const title = truncateToWidth(
    state.threadTitle || workspaceLabel(state.workspace),
    Math.max(4, innerWidth - 8),
  );
  const titleWidth = displayWidth(title);
  const topBorder =
    title && titleWidth + 5 <= width
      ? `╭${"─".repeat(Math.max(1, width - titleWidth - 5))} ${title} ─╮`
      : `╭${"─".repeat(Math.max(0, width - 2))}╮`;
  const bottomBorder = `╰${"─".repeat(Math.max(0, width - 2))}╯`;
  const prompt = "❯ ";
  const promptColor = gate ? "yellow" : "green";
  const firstLine = truncateToWidth(
    lines[0] ?? "",
    Math.max(1, innerWidth - displayWidth(prompt) - 1),
  );
  const firstPad = Math.max(
    0,
    innerWidth - displayWidth(prompt) - displayWidth(firstLine) - 1,
  );
  const framedRow = (content: string, key: string) => {
    const text = truncateToWidth(content, innerWidth);
    const pad = Math.max(0, innerWidth - displayWidth(text));
    return (
      <Text key={key} dimColor>
        {"│ "}
        {text}
        {" ".repeat(pad)}
        {" │"}
      </Text>
    );
  };

  return (
    <Box flexDirection="column">
      {activeMenu ? (
        <Menu
          title={activeMenu === "slash" ? "commands" : "files"}
          items={visibleMenuItems}
          index={menuIndexSafe - menuStart}
          width={width}
        />
      ) : null}
      {state.queue.length > 0 ? (
        <Text dimColor>
          {truncateToWidth(
            `${state.queue.length} queued · Ctrl+U to withdraw`,
            width,
          )}
        </Text>
      ) : null}
      <Text dimColor>{topBorder}</Text>
      <Text>
        <Text dimColor>{"│ "}</Text>
        <Text color={promptColor}>{prompt}</Text>
        <Text>{firstLine}</Text>
        <Text dimColor>▌</Text>
        <Text dimColor>
          {" ".repeat(firstPad)}
          {" │"}
        </Text>
      </Text>
      {lines
        .slice(1, 1 + visibleExtraLines)
        .map((line, index) =>
          framedRow(`... ${line}`, `line-${index}`),
        )}
      {overflowLine > 0
        ? framedRow(
            `... (+${extraLines - visibleExtraLines} more lines)`,
            "overflow",
          )
        : null}
      <Text dimColor>{bottomBorder}</Text>
    </Box>
  );
}

function Menu({
  title,
  items,
  index,
  width,
}: {
  title: string;
  items: string[];
  index: number;
  width: number;
}) {
  return (
    <Box flexDirection="column">
      <Text dimColor>{title}</Text>
      {items.map((item, itemIndex) => (
        <Text key={item} color={itemIndex === index ? "cyan" : undefined}>
          {truncateToWidth(`${itemIndex === index ? "❯ " : "  "}${item}`, width)}
        </Text>
      ))}
    </Box>
  );
}

function workspaceLabel(workspace: string): string {
  const parts = workspace.split(/[\\/]/).filter(Boolean);
  return parts.at(-1) ?? workspace;
}
