const WIDE_RANGES: ReadonlyArray<readonly [number, number]> = [
  [0x1100, 0x115f],
  [0x2e80, 0xa4cf],
  [0xac00, 0xd7a3],
  [0xf900, 0xfaff],
  [0xfe30, 0xfe6f],
  [0xff00, 0xff60],
  [0xffe0, 0xffe6],
];

export function isWideCharacter(character: string): boolean {
  const code = character.codePointAt(0) ?? 0;
  return WIDE_RANGES.some(([start, end]) => code >= start && code <= end);
}

export function characterWidth(character: string): number {
  return isWideCharacter(character) ? 2 : 1;
}

export function displayWidth(text: string): number {
  let width = 0;
  for (const character of text) {
    width += characterWidth(character);
  }
  return width;
}

export function truncateToWidth(text: string, limit: number): string {
  const width = Math.max(1, Math.floor(limit));
  if (displayWidth(text) <= width) {
    return text;
  }
  let used = 0;
  let result = "";
  for (const character of text) {
    const size = characterWidth(character);
    if (used + size > width - 1) {
      break;
    }
    used += size;
    result += character;
  }
  return `${result}…`;
}

export function padToWidth(text: string, limit: number): string {
  const width = Math.max(0, Math.floor(limit) - displayWidth(text));
  return `${text}${" ".repeat(width)}`;
}

export function wrapToWidth(text: string, limit: number): string[] {
  const width = Math.max(1, Math.floor(limit));
  const lines: string[] = [];
  for (const logicalLine of text.split("\n")) {
    if (logicalLine === "") {
      lines.push("");
      continue;
    }
    let current = "";
    let currentWidth = 0;
    for (const character of logicalLine) {
      const size = characterWidth(character);
      if (currentWidth + size > width) {
        lines.push(current);
        current = "";
        currentWidth = 0;
      }
      current += character;
      currentWidth += size;
    }
    lines.push(current);
  }
  return lines;
}
