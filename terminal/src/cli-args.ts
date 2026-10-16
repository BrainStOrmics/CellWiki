export const VERSION = "0.1.0";

export const HELP = `cellwiki-tui - CellWiki terminal client (Ink + React)

Usage:
  cellwiki-tui [--workspace PATH] [--classic]

Options:
  -w, --workspace PATH  Knowledge-base workspace (default: current directory)
      --classic         Use the classic scrollback renderer (no alternate screen)
  -h, --help            Show this help
  -v, --version         Show the version

The default renderer runs fullscreen on the terminal's alternate screen, like
Claude Code fullscreen mode; set CELLWIKI_TUI_CLASSIC=1 for the same effect as
--classic.
`;

export function parseWorkspaceArg(args: string[]): string | null {
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === "--workspace" || arg === "-w") {
      return args[index + 1] ?? null;
    }
    if (arg?.startsWith("--workspace=")) {
      return arg.slice("--workspace=".length);
    }
  }
  return null;
}

export function hasHelpFlag(args: string[]): boolean {
  return args.includes("--help") || args.includes("-h");
}

export function hasVersionFlag(args: string[]): boolean {
  return args.includes("--version") || args.includes("-v");
}

export function hasClassicFlag(args: string[]): boolean {
  return args.includes("--classic");
}

export function classicFromEnv(env: NodeJS.ProcessEnv = process.env): boolean {
  const value = (env.CELLWIKI_TUI_CLASSIC ?? "").trim().toLowerCase();
  return value === "1" || value === "true" || value === "yes";
}
