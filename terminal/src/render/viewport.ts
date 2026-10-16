import type { Gate, Tone } from "../controller";
import {
  renderMarkdownLines,
  type StyledSegment,
} from "./markdown";
import { displayWidth, wrapToWidth } from "./text";

export interface VisualLine {
  text: string;
  tone?: Tone;
  segments?: StyledSegment[];
}

export interface LiveInput {
  reasoning: string;
  streaming: string;
  tools: Array<{ id: string; summary: string }>;
  runId: string | null;
  verbose: boolean;
}

export function transcriptPrefix(tone: Tone | undefined): string {
  if (tone === "user") {
    return "❯ ";
  }
  if (tone === "assistant") {
    return "● ";
  }
  return "";
}

export function segmentText(segments: StyledSegment[]): string {
  return segments.map((segment) => segment.text).join("");
}

export function toVisualLines(
  lines: Array<{ text: string; tone?: Tone }>,
  width: number,
): VisualLine[] {
  const visual: VisualLine[] = [];
  for (const line of lines) {
    const prefix = transcriptPrefix(line.tone);
    const bodyWidth = Math.max(1, width - displayWidth(prefix));
    const source =
      line.tone === "assistant"
        ? renderMarkdownLines(line.text, bodyWidth)
        : wrapToWidth(line.text, bodyWidth).map((text) => [{ text }]);
    source.forEach((segments, index) => {
      const lead = index === 0 ? prefix : prefix ? "  " : "";
      const withLead = lead ? [{ text: lead }, ...segments] : segments;
      visual.push({
        text: segmentText(withLead),
        tone: line.tone,
        segments: withLead,
      });
    });
  }
  return visual;
}

export function buildLiveLines(
  state: LiveInput,
  spinner: string,
  width: number,
): VisualLine[] {
  const lines: VisualLine[] = [];
  if (state.reasoning) {
    const tail = state.reasoning
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .at(-1) ?? "";
    const text = state.verbose
      ? `✻ ${state.reasoning.split("\n").slice(-12).join("\n")}`
      : `✻ Thinking… ${tail.slice(-120)}`;
    for (const wrapped of wrapToWidth(text, width)) {
      lines.push({ text: wrapped, tone: "dim" });
    }
  }
  if (state.streaming) {
    for (const segments of renderMarkdownLines(state.streaming, width)) {
      lines.push({ text: segmentText(segments), segments });
    }
  }
  for (const tool of state.tools) {
    lines.push({ text: `${spinner} ${tool.summary}`, tone: "warning" });
  }
  const busy = state.runId !== null || state.tools.length > 0;
  if (busy && !state.streaming && !state.reasoning && state.tools.length === 0) {
    lines.push({ text: `${spinner} working… (Esc to interrupt)`, tone: "dim" });
  }
  return lines;
}

export interface ViewportWindow {
  lines: VisualLine[];
  hiddenAbove: number;
  hiddenBelow: number;
}

export function windowLines(
  lines: VisualLine[],
  height: number,
  offsetFromBottom: number,
): ViewportWindow {
  const rows = Math.max(1, Math.floor(height));
  const maxOffset = Math.max(0, lines.length - rows);
  const offset = Math.min(Math.max(0, Math.floor(offsetFromBottom)), maxOffset);
  const end = lines.length - offset;
  const start = Math.max(0, end - rows);
  return {
    lines: lines.slice(start, end),
    hiddenAbove: start,
    hiddenBelow: offset,
  };
}

export interface GateLayout {
  rows: number;
  previewLines: number;
  maxOptions: number;
}

export function gateLayout(gate: Gate, terminalRows: number): GateLayout {
  const budget = Math.max(5, terminalRows - 6);
  if (gate.kind === "question") {
    const optionCount = gate.question.options?.length ?? 0;
    const maxOptions = Math.max(0, Math.min(optionCount, budget - 4));
    const overflow = optionCount > maxOptions ? 1 : 0;
    return {
      rows: Math.min(budget, 3 + maxOptions + overflow),
      previewLines: 0,
      maxOptions,
    };
  }
  const previewLines = Math.max(2, Math.min(24, budget - 6));
  const patchLines = gate.patch.split("\n").length;
  const overflow = patchLines > previewLines ? 1 : 0;
  return {
    rows: Math.min(budget, 4 + previewLines + overflow),
    previewLines,
    maxOptions: 0,
  };
}
