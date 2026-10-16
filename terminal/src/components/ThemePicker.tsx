import { Box, Text, useInput } from "ink";

import type { TuiController, TuiState } from "../controller";
import { truncateToWidth } from "../render/text";
import type { TerminalSize } from "../render/use-terminal-size";

export interface ThemePickerProps {
  controller: TuiController;
  state: TuiState;
  size: TerminalSize;
  fullscreen: boolean;
}

export function ThemePicker({
  controller,
  state,
  size,
  fullscreen,
}: ThemePickerProps) {
  const picker = state.picker;
  const choices = controller.themeChoices();

  useInput((_input, key) => {
    if (!picker || picker.kind !== "theme") {
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
  });

  if (!picker || picker.kind !== "theme") {
    return null;
  }

  const rows = fullscreen ? size.rows : Math.min(size.rows, 20);
  const width = size.columns;
  const index = Math.min(picker.index, choices.length - 1);
  const visibleCount = Math.max(1, Math.floor(Math.max(2, rows - 4) / 2));
  const start = clamp(
    index - Math.floor(visibleCount / 2),
    0,
    Math.max(0, choices.length - visibleCount),
  );
  const visible = choices.slice(start, start + visibleCount);

  return (
    <Box flexDirection="column" height={fullscreen ? rows : undefined}>
      <Text bold color={state.theme.tokens.claude}>
        Select theme
      </Text>
      {visible.map((choice, offset) => {
        const itemIndex = start + offset;
        const selected = itemIndex === index;
        const current = choice.id === state.themeId;
        return (
          <Box key={choice.id} flexDirection="column">
            <Text color={selected ? state.theme.tokens.claude : undefined}>
              {truncateToWidth(
                `${selected ? "❯ " : "  "}${choice.label}${
                  current ? " (current)" : ""
                }`,
                width,
              )}
            </Text>
            <Text color={state.theme.tokens.inactive}>
              <Text color={choice.tokens.claude}>●</Text>
              <Text color={choice.tokens.success}>●</Text>
              <Text color={choice.tokens.error}>●</Text>
              <Text color={choice.tokens.warning}>●</Text>
              {` ${choice.description} · ${choice.id}`}
            </Text>
          </Box>
        );
      })}
      <Text color={state.theme.tokens.inactive}>
        {truncateToWidth("↑/↓ preview · Enter apply · Esc cancel", width)}
      </Text>
    </Box>
  );
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum);
}
