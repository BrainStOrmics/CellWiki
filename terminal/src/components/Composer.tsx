import { Box, Text, useInput } from "ink";
import { useMemo, useState } from "react";

import { filterCommands } from "../commands";
import type { TuiController, TuiState } from "../controller";

export interface ComposerProps {
  controller: TuiController;
  state: TuiState;
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

export function Composer({ controller, state }: ComposerProps) {
  const [value, setValue] = useState("");
  const [menuIndex, setMenuIndex] = useState(0);
  const [history, setHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);

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

  const completeMenu = (): void => {
    const item = menuItems[menuIndex];
    if (!item) {
      return;
    }
    if (menuKind === "slash") {
      setValue(`${item} `);
    } else if (mention) {
      setValue(`${value.slice(0, mention.start)}@${item} `);
    }
    setMenuIndex(0);
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
      if (value.endsWith("\\") && !value.endsWith("\\\\")) {
        setValue((current) => `${current.slice(0, -1)}\n`);
        return;
      }
      if (menuKind) {
        completeMenu();
        return;
      }
      const message = value;
      setValue("");
      setMenuIndex(0);
      setHistoryIndex(-1);
      if (message.trim()) {
        setHistory((current) => [...current, message]);
        void controller.submit(message);
      }
      return;
    }
    if (key.tab && menuKind) {
      completeMenu();
      return;
    }
    if (key.upArrow) {
      if (menuKind && menuItems.length > 0) {
        setMenuIndex(
          (current) => (current - 1 + menuItems.length) % menuItems.length,
        );
        return;
      }
      if (!value && state.queue.length > 0) {
        const queued = controller.withdrawQueued();
        if (queued) {
          setValue(queued);
        }
        return;
      }
      if (history.length > 0) {
        const next =
          historyIndex < 0
            ? history.length - 1
            : Math.max(0, historyIndex - 1);
        setHistoryIndex(next);
        setValue(history[next] ?? "");
      }
      return;
    }
    if (key.downArrow) {
      if (menuKind && menuItems.length > 0) {
        setMenuIndex((current) => (current + 1) % menuItems.length);
        return;
      }
      if (historyIndex >= 0) {
        const next = historyIndex + 1;
        if (next >= history.length) {
          setHistoryIndex(-1);
          setValue("");
        } else {
          setHistoryIndex(next);
          setValue(history[next] ?? "");
        }
      }
      return;
    }
    if (key.backspace || key.delete) {
      setValue((current) => current.slice(0, -1));
      return;
    }
    if (key.ctrl || key.meta) {
      return;
    }
    if (input && !input.includes("\u001b")) {
      setValue((current) => current + input);
    }
  });

  const prompt = gate
    ? gate.kind === "diff"
      ? "approval (1/2/3, esc later)> "
      : "answer (esc skip)> "
    : state.runId
      ? "(running - enter queues)> "
      : "> ";
  const lines = value.split("\n");

  return (
    <Box flexDirection="column">
      {menuKind ? (
        <Menu
          title={menuKind === "slash" ? "commands" : "files"}
          items={menuItems}
          index={menuIndex}
        />
      ) : null}
      {state.queue.length > 0 ? (
        <Text dimColor>
          {state.queue.length} queued · up to withdraw
        </Text>
      ) : null}
      <Box>
        <Text color={gate ? "yellow" : "green"}>{prompt}</Text>
        <Text>{lines[0] ?? ""}</Text>
        <Text dimColor>▌</Text>
      </Box>
      {lines.slice(1).map((line, index) => (
        <Text key={`line-${index}`} dimColor>
          {"... "}
          {line}
        </Text>
      ))}
    </Box>
  );
}

function Menu({
  title,
  items,
  index,
}: {
  title: string;
  items: string[];
  index: number;
}) {
  return (
    <Box flexDirection="column">
      <Text dimColor>{title}</Text>
      {items.slice(0, 6).map((item, itemIndex) => (
        <Text key={item} color={itemIndex === index ? "cyan" : undefined}>
          {itemIndex === index ? "❯ " : "  "}
          {item}
        </Text>
      ))}
    </Box>
  );
}
