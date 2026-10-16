import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, dirname, join } from "node:path";

import { DaemonClient } from "../src/api/client";
import {
  ensureDaemon,
  findCellwikiCli,
  readControlToken,
  workspaceStateDir,
} from "../src/daemon/discovery";

const cli = process.env.CELLWIKI_CLI ?? findCellwikiCli();
if (!cli) {
  console.error(
    "smoke: set CELLWIKI_CLI or install the Python cellwiki CLI on PATH",
  );
  process.exit(1);
}

process.env.PATH = `${dirname(cli)}${delimiter}${process.env.PATH ?? ""}`;
const workspace = mkdtempSync(join(tmpdir(), "cellwiki-tui-smoke-"));
writeFileSync(
  join(workspace, ".env"),
  [
    "OPENAI_API_KEY=test",
    "OPENAI_BASE_URL=http://127.0.0.1:9/v1",
    "OPENAI_MODEL=gpt-4o-mini",
    "OPENAI_API_PROTOCOL=chat_completions",
    "",
  ].join("\n"),
);
console.log(`smoke: workspace ${workspace}`);

try {
  const coordinates = await ensureDaemon(workspace);
  const token = readControlToken(workspaceStateDir(coordinates.workspace));
  if (!token) {
    throw new Error("control token missing");
  }
  const client = new DaemonClient(
    `http://127.0.0.1:${coordinates.port}`,
    token,
  );
  const threads = await client.listThreads();
  const catalog = await client.listModelProviders();
  console.log(
    `smoke: connected port=${coordinates.port} threads=${threads.length} ` +
      `model=${catalog.default_selection?.model_id ?? "legacy"}`,
  );
  const threadId = await client.createThread();
  const run = await client.startRun(
    threadId,
    "hello",
    `smoke_${Date.now().toString(16)}`,
  );
  let events = 0;
  for await (const _event of client.streamEvents(run.run_id, 0)) {
    events += 1;
  }
  const finalRun = await client.getRun(run.run_id);
  console.log(`smoke: run ${finalRun.status} events=${events}`);
  if (finalRun.status !== "failed") {
    throw new Error(`smoke: expected a failed run, got ${finalRun.status}`);
  }
} finally {
  await new Promise<void>((resolve) => {
    const child = spawn(cli, ["daemon", "stop", "--workspace", workspace], {
      stdio: "ignore",
      windowsHide: true,
      shell: process.platform === "win32" && /\.(cmd|bat)$/i.test(cli),
    });
    child.on("close", () => resolve());
    child.on("error", () => resolve());
  });
}
