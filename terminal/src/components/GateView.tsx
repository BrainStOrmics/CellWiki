import { Box, Text, useInput } from "ink";
import { useState } from "react";

import type { Gate } from "../controller";
import { redactSecrets } from "../redact";
import { truncateToWidth } from "../render/text";

export interface GateViewProps {
  gate: Gate;
  width?: number;
  previewLines?: number;
  maxOptions?: number;
  marginTop?: number;
  allowSelect?: boolean;
  onSelect?: (index: number) => void;
}

export function GateView({
  gate,
  width = 80,
  previewLines = 24,
  maxOptions = Number.MAX_SAFE_INTEGER,
  marginTop = 1,
  allowSelect = true,
  onSelect,
}: GateViewProps) {
  const options = gate.kind === "question" ? gate.question.options ?? [] : [];
  const [cursor, setCursor] = useState(0);
  const activeCursor =
    options.length > 0 ? Math.min(cursor, options.length - 1) : 0;

  useInput(
    (_input, key) => {
      if (options.length === 0) {
        return;
      }
      if (key.upArrow) {
        setCursor((value) => (value - 1 + options.length) % options.length);
      } else if (key.downArrow) {
        setCursor((value) => (value + 1) % options.length);
      } else if (key.return && allowSelect) {
        onSelect?.(activeCursor);
      }
    },
    { isActive: gate.kind === "question" && options.length > 0 },
  );

  if (gate.kind === "question") {
    const shown = options.slice(0, Math.max(0, maxOptions));
    const hidden = options.length - shown.length;
    return (
      <Box flexDirection="column" marginTop={marginTop}>
        <Text bold color="cyan">
          CellWiki needs your decision
        </Text>
        <Text>{truncateToWidth(gate.question.question ?? "", width)}</Text>
        {shown.map((option, index) => (
          <Text
            key={`${index}-${option.label ?? "option"}`}
            color={
              index === activeCursor || option.recommended ? "cyan" : undefined
            }
          >
            {truncateToWidth(
              `${index === activeCursor ? "❯" : " "} ${index + 1}. ${
                option.label ?? ""
              }${
                option.description ? ` — ${option.description}` : ""
              }`,
              width,
            )}
          </Text>
        ))}
        {hidden > 0 ? (
          <Text dimColor>{`… ${hidden} more options`}</Text>
        ) : null}
        <Text dimColor>↑/↓ choose · Enter select · or type an answer · Esc skips</Text>
      </Box>
    );
  }

  const safePatch = redactSecrets(gate.patch);
  const lines = safePatch.split("\n");
  const preview = lines.slice(0, Math.max(0, previewLines));
  const files = diffFiles(safePatch);
  const [added, removed] = diffCounts(safePatch);
  return (
    <Box flexDirection="column" marginTop={marginTop}>
      <Text bold>Pending diff {gate.diffId}</Text>
      {files.length > 0 ? (
        <Text dimColor>
          {truncateToWidth(
            `files: ${files.slice(0, 6).join(", ")}${
              files.length > 6 ? ` … (+${files.length - 6})` : ""
            }`,
            width,
          )}
        </Text>
      ) : null}
      <Text dimColor>
        changes: +{added} -{removed}
      </Text>
      {preview.map((line, index) => (
        <Text
          key={`${index}-${line}`}
          color={diffColor(line)}
          dimColor={diffMeta(line)}
        >
          {truncateToWidth(line, width)}
        </Text>
      ))}
      {lines.length > preview.length ? (
        <Text dimColor>
          … {lines.length - preview.length} more lines — press 3 to view full diff
        </Text>
      ) : null}
      <Text bold>1 accept · 2 reject · 3 view full diff · Esc later</Text>
    </Box>
  );
}

function diffFiles(patch: string): string[] {
  const files: string[] = [];
  for (const line of patch.split("\n")) {
    if (line.startsWith("diff --git ")) {
      const parts = line.split(" ");
      const path = parts[3];
      if (path) {
        files.push(path.startsWith("b/") ? path.slice(2) : path);
      }
    }
  }
  return files;
}

function diffCounts(patch: string): [number, number] {
  let added = 0;
  let removed = 0;
  for (const line of patch.split("\n")) {
    if (line.startsWith("+") && !line.startsWith("+++")) {
      added += 1;
    } else if (line.startsWith("-") && !line.startsWith("---")) {
      removed += 1;
    }
  }
  return [added, removed];
}

function diffColor(line: string): string | undefined {
  if (line.startsWith("+") && !line.startsWith("+++")) {
    return "green";
  }
  if (line.startsWith("-") && !line.startsWith("---")) {
    return "red";
  }
  return undefined;
}

function diffMeta(line: string): boolean {
  return (
    line.startsWith("@@") ||
    line.startsWith("diff --git") ||
    line.startsWith("index ") ||
    line.startsWith("---") ||
    line.startsWith("+++")
  );
}
