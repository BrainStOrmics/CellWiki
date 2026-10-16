import { render } from "ink";

import { App } from "./components/App";
import { TuiController } from "./controller";
import {
  HELP,
  VERSION,
  hasHelpFlag,
  hasVersionFlag,
  parseWorkspaceArg,
} from "./cli-args";

export async function main(
  argv: string[] = process.argv.slice(2),
): Promise<number> {
  if (hasHelpFlag(argv)) {
    process.stdout.write(HELP);
    return 0;
  }
  if (hasVersionFlag(argv)) {
    process.stdout.write(`${VERSION}\n`);
    return 0;
  }
  const workspace = parseWorkspaceArg(argv) ?? process.cwd();
  const controller = new TuiController(workspace);
  const app = render(<App controller={controller} />);
  await app.waitUntilExit();
  return 0;
}

void main()
  .then((code) => {
    process.exitCode = code;
  })
  .catch((error: unknown) => {
    process.stderr.write(
      `cellwiki-tui: ${error instanceof Error ? error.message : String(error)}\n`,
    );
    process.exitCode = 1;
  });
