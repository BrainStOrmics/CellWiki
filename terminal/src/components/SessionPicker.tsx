import { Box, Text, useInput } from "ink";
import { useMemo } from "react";

import {
  filterThreads,
  type TuiController,
  type TuiState,
} from "../controller";
import { truncateToWidth } from "../render/text";
import { formatRelativeTime } from "../render/time";
import type { TerminalSize } from "../render/use-terminal-size";

export interface SessionPickerProps {
  controller: TuiController;
  state: TuiState;
  size: TerminalSize;
  fullscreen: boolean;
}

export function SessionPicker({
  controller,
  state,
  size,
  fullscreen,
}: SessionPickerProps) {
  const picker = state.picker;
  const query = picker?.query ?? "";
  const threads = useMemo(
    () => filterThreads(state.threads, query),
    [state.threads, query],
  );

  useInput((input, key) => {
    if (!picker) {
      return;
    }
    if (key.escape) {
      controller.closePicker();
      return;
    }
    if (key.return) {
      void controller.confirmPicker();
      return;
    }
    if (key.upArrow) {
      controller.movePicker(-1);
      return;
    }
    if (key.downArrow) {
      controller.movePicker(1);
      return;
    }
    if (key.backspace || key.delete) {
      controller.setPickerQuery(picker.query.slice(0, -1));
      return;
    }
    if (key.ctrl || key.meta || key.tab) {
      return;
    }
    if (input && !input.includes("\u001b")) {
      const text = input.replace(/[\r\n]/g, "");
      if (text) {
        controller.setPickerQuery(picker.query + text);
      }
    }
  });

  if (!picker) {
    return null;
  }

  const rows = fullscreen ? size.rows : Math.min(size.rows, 16);
  const width = size.columns;
  const index =
    threads.length > 0 ? Math.min(picker.index, threads.length - 1) : 0;
  const visibleCount = Math.max(1, Math.floor(Math.max(2, rows - 7) / 2));
  const start = clamp(
    index - Math.floor(visibleCount / 2),
    0,
    Math.max(0, threads.length - visibleCount),
  );
  const visible = threads.slice(start, start + visibleCount);

  return (
    <Box flexDirection="column" height={fullscreen ? rows : undefined}>
      <Text bold>Resume session</Text>
      <Box
        borderStyle="round"
        borderColor="gray"
        width={Math.max(12, width - 2)}
        paddingX={1}
      >
        <Text dimColor>⌕ </Text>
        <Text>{truncateToWidth(query, Math.max(4, width - 8))}</Text>
        <Text dimColor>▌</Text>
      </Box>
      <Text dimColor>{truncateToWidth(workspaceLabel(state.workspace), width)}</Text>
      {visible.length === 0 ? (
        <Text dimColor>(no matching conversations)</Text>
      ) : null}
      {visible.map((thread, offset) => {
        const itemIndex = start + offset;
        const selected = itemIndex === index;
        const title = thread.title || thread.thread_id;
        const meta = [
          formatRelativeTime(thread.updated_at),
          thread.latest_status ?? "no runs",
          ...(thread.thread_id === state.threadId ? ["current"] : []),
        ].join(" · ");
        return (
          <Box key={thread.thread_id} flexDirection="column">
            <Text color={selected ? "cyan" : undefined}>
              {truncateToWidth(`${selected ? "❯ " : "  "}${title}`, width)}
            </Text>
            <Text dimColor>{truncateToWidth(`  ${meta}`, width)}</Text>
          </Box>
        );
      })}
      <Text dimColor>
        {truncateToWidth(
          "Type to search · ↑/↓ to move · Enter to resume · Esc to cancel",
          width,
        )}
      </Text>
    </Box>
  );
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum);
}

function workspaceLabel(workspace: string): string {
  const parts = workspace.split(/[\\/]/).filter(Boolean);
  return parts.at(-1) ?? workspace;
}
