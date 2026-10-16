export const VERSION = "0.1.0";

export const HELP = `cellwiki-tui - CellWiki terminal client (Ink + React)

Usage:
  cellwiki-tui [--workspace PATH]

Options:
  -w, --workspace PATH  Knowledge-base workspace (default: current directory)
  -h, --help            Show this help
  -v, --version         Show the version
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
