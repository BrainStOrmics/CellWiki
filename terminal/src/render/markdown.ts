import { characterWidth } from "./text";

export interface StyledSegment {
  text: string;
  bold?: boolean;
  italic?: boolean;
  dim?: boolean;
  underline?: boolean;
  color?: string;
}

export interface MarkdownLine {
  segments: StyledSegment[];
}

const INLINE_PATTERN =
  /(`[^`]+`|\*\*[^*\n]+\*\*|\[[^\]]+\]\([^)]+\)|~~[^~\n]+~~|\*[^*\n]+\*)/;

export function renderInline(text: string): StyledSegment[] {
  const segments: StyledSegment[] = [];
  let rest = text;
  while (rest.length > 0) {
    const match = INLINE_PATTERN.exec(rest);
    if (!match || match.index === undefined) {
      segments.push({ text: rest });
      break;
    }
    if (match.index > 0) {
      segments.push({ text: rest.slice(0, match.index) });
    }
    const token = match[0];
    segments.push(...styleToken(token));
    rest = rest.slice(match.index + token.length);
  }
  return segments.filter((segment) => segment.text.length > 0);
}

function styleToken(token: string): StyledSegment[] {
  if (token.startsWith("**") && token.endsWith("**")) {
    return renderInline(token.slice(2, -2)).map((segment) => ({
      ...segment,
      bold: true,
    }));
  }
  if (token.startsWith("`") && token.endsWith("`")) {
    return [{ text: token.slice(1, -1), dim: true }];
  }
  if (token.startsWith("~~") && token.endsWith("~~")) {
    return [{ text: token.slice(2, -2), dim: true }];
  }
  if (token.startsWith("[")) {
    const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token);
    return [{ text: link?.[1] ?? token, underline: true }];
  }
  if (token.startsWith("*") && token.endsWith("*")) {
    return renderInline(token.slice(1, -1)).map((segment) => ({
      ...segment,
      italic: true,
    }));
  }
  return [{ text: token }];
}

export function renderMarkdown(text: string): MarkdownLine[] {
  const lines: MarkdownLine[] = [];
  let inFence = false;
  for (const raw of text.split("\n")) {
    if (/^\s*(```|~~~)/.test(raw)) {
      inFence = !inFence;
      continue;
    }
    if (inFence) {
      lines.push({ segments: [{ text: raw, dim: true }] });
      continue;
    }
    const heading = /^(#{1,6})\s+(.*)$/.exec(raw);
    if (heading) {
      lines.push({ segments: [{ text: heading[2] ?? "", bold: true }] });
      continue;
    }
    const bullet = /^(\s*)[-*+]\s+(.*)$/.exec(raw);
    if (bullet) {
      lines.push({
        segments: [
          { text: `${bullet[1] ?? ""}• ` },
          ...renderInline(bullet[2] ?? ""),
        ],
      });
      continue;
    }
    const ordered = /^(\s*)(\d+)[.)]\s+(.*)$/.exec(raw);
    if (ordered) {
      lines.push({
        segments: [
          { text: `${ordered[1] ?? ""}${ordered[2] ?? ""}. ` },
          ...renderInline(ordered[3] ?? ""),
        ],
      });
      continue;
    }
    const quote = /^>\s?(.*)$/.exec(raw);
    if (quote) {
      lines.push({
        segments: [
          { text: "│ ", dim: true },
          ...renderInline(quote[1] ?? ""),
        ],
      });
      continue;
    }
    if (/^\s*([-*_])\1{2,}\s*$/.test(raw)) {
      lines.push({ segments: [{ text: "────────", dim: true }] });
      continue;
    }
    lines.push({ segments: renderInline(raw) });
  }
  return lines;
}

export function wrapSegments(
  segments: StyledSegment[],
  width: number,
): StyledSegment[][] {
  const limit = Math.max(1, Math.floor(width));
  const result: StyledSegment[][] = [];
  let current: StyledSegment[] = [];
  let currentWidth = 0;
  for (const segment of segments) {
    let buffer = "";
    for (const character of segment.text) {
      const size = characterWidth(character);
      if (currentWidth + size > limit) {
        if (buffer) {
          current.push({ ...segment, text: buffer });
          buffer = "";
        }
        result.push(current);
        current = [];
        currentWidth = 0;
      }
      buffer += character;
      currentWidth += size;
    }
    if (buffer) {
      current.push({ ...segment, text: buffer });
    }
  }
  if (current.length > 0 || result.length === 0) {
    result.push(current);
  }
  return result;
}

export function renderMarkdownLines(
  text: string,
  width: number,
): StyledSegment[][] {
  return renderMarkdown(text).flatMap((line) =>
    wrapSegments(line.segments, width),
  );
}
