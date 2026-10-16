import { Box, Text, useInput } from "ink";
import { useMemo } from "react";

import type { TuiController, TuiState } from "../controller";
import { truncateToWidth } from "../render/text";
import type { TerminalSize } from "../render/use-terminal-size";

export interface ModelPickerProps {
  controller: TuiController;
  state: TuiState;
  size: TerminalSize;
  fullscreen: boolean;
}

export function ModelPicker({
  controller,
  state,
  size,
  fullscreen,
}: ModelPickerProps) {
  const picker = state.picker;
  const query = picker?.kind === "model" ? picker.query : "";
  const items = useMemo(
    () => (picker?.kind === "model" ? controller.modelPickerItems(query) : []),
    [controller, picker?.kind, query],
  );

  useInput((input, key) => {
    if (!picker || picker.kind !== "model") {
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

  if (!picker || picker.kind !== "model") {
    return null;
  }

  const rows = fullscreen ? size.rows : Math.min(size.rows, 18);
  const width = size.columns;
  const noChoices = controller.modelChoices().length === 0;
  const index = Math.min(picker.index, Math.max(0, items.length - 1));
  const listRows = Math.max(2, rows - 4 - (noChoices ? 1 : 0));
  const visibleCount = Math.max(1, Math.floor(listRows / 2));
  const start = clamp(
    index - Math.floor(visibleCount / 2),
    0,
    Math.max(0, items.length - visibleCount),
  );
  const visible = items.slice(start, start + visibleCount);
  const usingCatalogDefault = !state.modelSelection?.model_id;

  return (
    <Box flexDirection="column" height={fullscreen ? rows : undefined}>
      <Text bold color={state.theme.tokens.claude}>
        Select model
      </Text>
      <Text color={state.theme.tokens.inactive}>
        {truncateToWidth(`⌕ ${query}▌`, width)}
      </Text>
      {noChoices ? (
        <Text color={state.theme.tokens.warning}>
          no enabled models in the catalog
        </Text>
      ) : null}
      {visible.map((item, offset) => {
        const itemIndex = start + offset;
        const selected = itemIndex === index;
        if (item.kind === "default") {
          return (
            <Box key="catalog-default" flexDirection="column">
              <Text
                color={selected ? state.theme.tokens.claude : undefined}
              >
                {truncateToWidth(
                  `${selected ? "❯ " : "  "}Use catalog default`,
                  width,
                )}
              </Text>
              <Text color={state.theme.tokens.inactive}>
                {truncateToWidth(
                  `  workspace default_selection${
                    usingCatalogDefault ? " · current" : ""
                  }`,
                  width,
                )}
              </Text>
            </Box>
          );
        }
        const choice = item.choice;
        const current =
          state.modelSelection?.model_id === choice.modelId &&
          state.modelSelection?.provider_id === choice.providerId;
        const meta = [
          choice.providerName,
          choice.modelId,
          ...(current ? ["current"] : []),
          ...(choice.hasKey ? [] : ["no key"]),
        ].join(" · ");
        return (
          <Box
            key={`${choice.providerId}/${choice.modelId}`}
            flexDirection="column"
          >
            <Text color={selected ? state.theme.tokens.claude : undefined}>
              {truncateToWidth(
                `${selected ? "❯ " : "  "}${choice.label}`,
                width,
              )}
            </Text>
            <Text color={state.theme.tokens.inactive}>
              {truncateToWidth(`  ${meta}`, width)}
            </Text>
          </Box>
        );
      })}
      <Text color={state.theme.tokens.inactive}>
        {truncateToWidth(
          "Type to search · ↑/↓ · Enter apply · Esc cancel",
          width,
        )}
      </Text>
    </Box>
  );
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum);
}
