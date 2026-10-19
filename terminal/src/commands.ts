export const COMMANDS = [
  "/help",
  "/new",
  "/resume",
  "/theme",
  "/clear",
  "/status",
  "/continue",
  "/retry",
  "/cancel",
  "/diff",
  "/model",
  "/context",
  "/quit",
] as const;

export type CommandName = (typeof COMMANDS)[number];

export interface ParsedCommand {
  name: string;
  argument: string;
}

export function parseCommand(input: string): ParsedCommand | null {
  const trimmed = input.trim();
  if (!trimmed.startsWith("/")) {
    return null;
  }
  const spaceIndex = trimmed.indexOf(" ");
  if (spaceIndex < 0) {
    return { name: trimmed, argument: "" };
  }
  return {
    name: trimmed.slice(0, spaceIndex),
    argument: trimmed.slice(spaceIndex + 1).trim(),
  };
}

export function filterCommands(prefix: string): CommandName[] {
  const normalized = prefix.startsWith("/") ? prefix : `/${prefix}`;
  return COMMANDS.filter((command) => command.startsWith(normalized));
}

export function isKnownCommand(name: string): name is CommandName {
  return (COMMANDS as readonly string[]).includes(name);
}
