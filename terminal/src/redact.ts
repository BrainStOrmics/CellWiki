const SECRET_ASSIGNMENT =
  /^(.*?(?:api[_-]?key|secret|token|password)\s*[:=]\s*)(\S+)(.*)$/i;

export function redactSecrets(text: string): string {
  return text
    .split("\n")
    .map((line) => {
      const match = SECRET_ASSIGNMENT.exec(line);
      if (!match) {
        return line;
      }
      return `${match[1]}<redacted>${match[3] ?? ""}`;
    })
    .join("\n");
}
