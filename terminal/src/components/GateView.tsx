import { Box, Text } from "ink";

import type { Gate } from "../controller";
import { redactSecrets } from "../redact";

export function GateView({ gate }: { gate: Gate }) {
  if (gate.kind === "question") {
    const options = gate.question.options ?? [];
    return (
      <Box flexDirection="column" marginTop={1}>
        <Text bold color="cyan">
          CellWiki needs your decision
        </Text>
        <Text>{gate.question.question}</Text>
        {options.map((option, index) => (
          <Text
            key={`${index}-${option.label ?? "option"}`}
            color={option.recommended ? "cyan" : undefined}
          >
            {"  "}
            {index + 1}. {option.label}
            {option.description ? ` — ${option.description}` : ""}
          </Text>
        ))}
        <Text dimColor>
          Answer with an option number or free text; Esc skips.
        </Text>
      </Box>
    );
  }

  const safePatch = redactSecrets(gate.patch);
  const lines = safePatch.split("\n");
  const preview = lines.slice(0, 24);
  const files = diffFiles(safePatch);
  const [added, removed] = diffCounts(safePatch);
  return (
    <Box flexDirection="column" marginTop={1}>
      <Text bold>Pending diff {gate.diffId}</Text>
      {files.length > 0 ? (
        <Text dimColor>
          files: {files.slice(0, 6).join(", ")}
          {files.length > 6 ? ` … (+${files.length - 6})` : ""}
        </Text>
      ) : null}
      <Text dimColor>
        changes: +{added} -{removed}
      </Text>
      {preview.map((line, index) => (
        <Text key={`${index}-${line}`} color={diffColor(line)} dimColor={diffMeta(line)}>
          {line}
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
