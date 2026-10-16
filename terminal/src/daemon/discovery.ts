import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import {
  accessSync,
  constants,
  existsSync,
  mkdirSync,
  readFileSync,
  realpathSync,
} from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";

export const DAEMON_SCHEMA_VERSION = 1;
export const DAEMON_API_VERSION = "cellwiki-daemon-v1";
export const DISCOVERY_FILE_NAME = "daemon.json";
export const CONTROL_TOKEN_FILE_NAME = "control.token";
export const LAUNCH_LOG_FILE_NAME = "launch.log";

export interface DaemonCoordinates {
  schema_version: number;
  pid: number;
  port: number;
  workspace: string;
  package_version: string;
  api_version: string;
  started_at: string;
  log_path: string;
}

export class DaemonError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DaemonError";
  }
}

export class DaemonStartError extends DaemonError {
  constructor(message: string) {
    super(message);
    this.name = "DaemonStartError";
  }
}

export class DaemonVersionMismatch extends DaemonError {
  constructor(readonly coordinates: DaemonCoordinates) {
    super(
      "the running CellWiki daemon was started by an incompatible version " +
        `(package ${coordinates.package_version || "unknown"}, ` +
        `API ${coordinates.api_version || "unknown"}); ` +
        "restart the daemon with `cellwiki daemon restart`",
    );
    this.name = "DaemonVersionMismatch";
  }
}

export interface EnsureDaemonOptions {
  env?: NodeJS.ProcessEnv;
  timeoutMs?: number;
  pollMs?: number;
  spawnCli?: (cli: string, args: string[]) => Promise<void>;
  healthCheck?: (coordinates: DaemonCoordinates) => Promise<boolean>;
  sleep?: (ms: number) => Promise<void>;
}

export function expandHome(value: string): string {
  if (value === "~") {
    return homedir();
  }
  if (value.startsWith("~/") || value.startsWith("~\\")) {
    return join(homedir(), value.slice(2));
  }
  return value;
}

export function resolveWorkspace(workspace: string): string {
  const absolute = resolve(expandHome(workspace));
  try {
    return realpathSync.native(absolute);
  } catch {
    return absolute;
  }
}

export function workspaceHash(workspace: string): string {
  return createHash("sha256")
    .update(resolveWorkspace(workspace), "utf8")
    .digest("hex")
    .slice(0, 16);
}

export function workspaceStateDir(
  workspace: string,
  env: NodeJS.ProcessEnv = process.env,
): string {
  const digest = workspaceHash(workspace);
  const override = env.CELLWIKI_DAEMON_DIR;
  if (override) {
    return join(expandHome(override), digest);
  }
  if (env.XDG_RUNTIME_DIR) {
    return join(env.XDG_RUNTIME_DIR, "cellwiki", "daemon", digest);
  }
  return join(homedir(), ".cellwiki", "daemon", digest);
}

export function readCoordinates(stateDir: string): DaemonCoordinates | null {
  try {
    const payload = JSON.parse(
      readFileSync(join(stateDir, DISCOVERY_FILE_NAME), "utf8"),
    ) as Partial<DaemonCoordinates>;
    if (
      typeof payload.pid !== "number" ||
      typeof payload.port !== "number" ||
      typeof payload.workspace !== "string"
    ) {
      return null;
    }
    return {
      schema_version: Number(payload.schema_version ?? 0),
      pid: payload.pid,
      port: payload.port,
      workspace: payload.workspace,
      package_version: String(payload.package_version ?? ""),
      api_version: String(payload.api_version ?? ""),
      started_at: String(payload.started_at ?? ""),
      log_path: String(payload.log_path ?? ""),
    };
  } catch {
    return null;
  }
}

export function readControlToken(stateDir: string): string | null {
  try {
    const token = readFileSync(
      join(stateDir, CONTROL_TOKEN_FILE_NAME),
      "utf8",
    ).trim();
    return token || null;
  } catch {
    return null;
  }
}

export function pidAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === "EPERM";
  }
}

export async function checkHealth(
  coordinates: DaemonCoordinates,
  timeoutMs = 500,
): Promise<boolean> {
  try {
    const response = await fetch(
      `http://127.0.0.1:${coordinates.port}/health`,
      { signal: AbortSignal.timeout(timeoutMs) },
    );
    return response.ok;
  } catch {
    return false;
  }
}

export function findCellwikiCli(env: NodeJS.ProcessEnv = process.env): string | null {
  const pathValue = env.PATH ?? env.Path ?? "";
  const separator = process.platform === "win32" ? ";" : ":";
  const extensions =
    process.platform === "win32"
      ? (env.PATHEXT ?? ".COM;.EXE;.BAT;.CMD").split(";")
      : [""];
  for (const directory of pathValue.split(separator)) {
    if (!directory) {
      continue;
    }
    for (const extension of extensions) {
      const candidates =
        process.platform === "win32"
          ? [`cellwiki${extension}`, `cellwiki${extension.toLowerCase()}`]
          : ["cellwiki"];
      for (const candidate of candidates) {
        const fullPath = join(directory, candidate);
        if (!existsSync(fullPath)) {
          continue;
        }
        if (process.platform === "win32") {
          return fullPath;
        }
        try {
          accessSync(fullPath, constants.X_OK);
          return fullPath;
        } catch {
          continue;
        }
      }
    }
  }
  return null;
}

export interface CellwikiInvocation {
  command: string;
  args: string[];
}

export function resolveCellwikiInvocation(
  env: NodeJS.ProcessEnv = process.env,
): CellwikiInvocation | null {
  if (env.CELLWIKI_CLI) {
    return { command: env.CELLWIKI_CLI, args: [] };
  }
  if (env.CELLWIKI_PYTHON) {
    return {
      command: env.CELLWIKI_PYTHON,
      args: ["-m", "cellwiki.product_cli"],
    };
  }
  const cli = findCellwikiCli(env);
  return cli ? { command: cli, args: [] } : null;
}

export async function ensureDaemon(
  workspace: string,
  options: EnsureDaemonOptions = {},
): Promise<DaemonCoordinates> {
  const env = options.env ?? process.env;
  const resolved = resolveWorkspace(workspace);
  const stateDir = workspaceStateDir(resolved, env);
  mkdirSync(stateDir, { recursive: true });
  const healthCheck = options.healthCheck ?? checkHealth;
  const existing = readCoordinates(stateDir);
  if (existing && pidAlive(existing.pid) && (await healthCheck(existing))) {
    assertCompatible(existing);
    return existing;
  }
  const invocation = resolveCellwikiInvocation(env);
  if (!invocation) {
    throw new DaemonError(
      "the Python CellWiki CLI was not found on PATH; " +
        "install it first (for example `uv tool install CellWiki`)",
    );
  }
  const spawnCli = options.spawnCli ?? runCellwikiCli;
  await spawnCli(invocation.command, [
    ...invocation.args,
    "serve",
    "--detach",
    "--workspace",
    resolved,
  ]);
  const timeoutMs = options.timeoutMs ?? 90_000;
  const pollMs = options.pollMs ?? 100;
  const sleep = options.sleep ?? ((ms) => new Promise((r) => setTimeout(r, ms)));
  const deadline = Date.now() + timeoutMs;
  const launchLog = join(stateDir, LAUNCH_LOG_FILE_NAME);
  while (Date.now() < deadline) {
    const coordinates = readCoordinates(stateDir);
    if (coordinates && (await healthCheck(coordinates))) {
      assertCompatible(coordinates);
      return coordinates;
    }
    await sleep(pollMs);
  }
  throw new DaemonStartError(
    `the CellWiki daemon did not become healthy; inspect ${launchLog}`,
  );
}

export async function restartDaemon(
  workspace: string,
  options: EnsureDaemonOptions = {},
): Promise<DaemonCoordinates> {
  const env = options.env ?? process.env;
  const invocation = resolveCellwikiInvocation(env);
  if (!invocation) {
    throw new DaemonError("the Python CellWiki CLI was not found on PATH");
  }
  const spawnCli = options.spawnCli ?? runCellwikiCli;
  await spawnCli(invocation.command, [
    ...invocation.args,
    "daemon",
    "restart",
    "--workspace",
    resolveWorkspace(workspace),
  ]);
  return ensureDaemon(workspace, options);
}

export function assertCompatible(coordinates: DaemonCoordinates): void {
  if (
    coordinates.schema_version !== DAEMON_SCHEMA_VERSION ||
    coordinates.api_version !== DAEMON_API_VERSION
  ) {
    throw new DaemonVersionMismatch(coordinates);
  }
}

export async function runCellwikiCli(
  cli: string,
  args: string[],
): Promise<void> {
  const invocation = commandFor(cli, args);
  await new Promise<void>((resolvePromise, rejectPromise) => {
    const child = spawn(invocation.command, invocation.args, {
      stdio: ["ignore", "ignore", "pipe"],
      windowsHide: true,
      windowsVerbatimArguments: invocation.windowsVerbatimArguments,
    });
    let stderr = "";
    child.stderr?.on("data", (chunk: Buffer) => {
      stderr += chunk.toString("utf8");
    });
    child.on("error", (error) => rejectPromise(error));
    child.on("close", (code) => {
      if (code === 0) {
        resolvePromise();
        return;
      }
      rejectPromise(
        new DaemonError(
          `cellwiki ${args.join(" ")} exited with code ${code ?? "unknown"}` +
            (stderr.trim() ? `: ${stderr.trim()}` : ""),
        ),
      );
    });
  });
}

interface CliInvocation {
  command: string;
  args: string[];
  windowsVerbatimArguments?: boolean;
}

function commandFor(cli: string, args: string[]): CliInvocation {
  if (process.platform === "win32" && /\.(cmd|bat)$/i.test(cli)) {
    const comspec = process.env.ComSpec ?? "cmd.exe";
    const line = [cli, ...args].map(quoteWindowsArgument).join(" ");
    return {
      command: comspec,
      args: ["/d", "/s", "/c", line],
      windowsVerbatimArguments: true,
    };
  }
  return { command: cli, args };
}

function quoteWindowsArgument(value: string): string {
  return `"${value.replace(/"/g, '""')}"`;
}
