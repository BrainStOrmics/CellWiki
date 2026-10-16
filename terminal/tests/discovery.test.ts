import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import {
  DAEMON_API_VERSION,
  ensureDaemon,
  readControlToken,
  readCoordinates,
  resolveCellwikiInvocation,
  workspaceHash,
  workspaceStateDir,
} from "../src/daemon/discovery";

function makeStateDir(workspace: string): string {
  const override = mkdtempSync(join(tmpdir(), "cellwiki-daemon-"));
  const stateDir = workspaceStateDir(workspace, {
    ...process.env,
    CELLWIKI_DAEMON_DIR: override,
  });
  mkdirSync(stateDir, { recursive: true });
  return stateDir;
}

function writeCoordinates(
  stateDir: string,
  workspace: string,
  apiVersion = DAEMON_API_VERSION,
): void {
  writeFileSync(
    join(stateDir, "daemon.json"),
    JSON.stringify({
      schema_version: 1,
      pid: process.pid,
      port: 1234,
      workspace,
      package_version: "2.0.0",
      api_version: apiVersion,
      started_at: "2026-10-16T00:00:00+00:00",
      log_path: "daemon.log",
    }),
  );
  writeFileSync(join(stateDir, "control.token"), "test-token");
}

describe("daemon discovery", () => {
  it("matches the Python workspace hash when Python is available", () => {
    const workspace = mkdtempSync(join(tmpdir(), "cellwiki-hash-"));
    const script =
      "import hashlib; from pathlib import Path; " +
      `p=Path(${JSON.stringify(workspace)}).resolve(); ` +
      'print(hashlib.sha256(str(p).encode("utf-8")).hexdigest()[:16])';
    let expected: string | null = null;
    for (const python of ["python", "python3"]) {
      try {
        expected = execFileSync(python, ["-c", script], {
          encoding: "utf8",
        }).trim();
        break;
      } catch {
        expected = null;
      }
    }
    if (!expected) {
      return;
    }
    expect(workspaceHash(workspace)).toBe(expected);
  });

  it("honors CELLWIKI_DAEMON_DIR and reads private state files", async () => {
    const workspace = mkdtempSync(join(tmpdir(), "cellwiki-ws-"));
    const stateDir = makeStateDir(workspace);
    writeCoordinates(stateDir, workspace);
    const coordinates = await ensureDaemon(workspace, {
      env: { ...process.env, CELLWIKI_DAEMON_DIR: join(stateDir, "..") },
      healthCheck: async () => true,
      spawnCli: async () => {
        throw new Error("should not spawn a daemon");
      },
    });
    expect(coordinates.port).toBe(1234);
    expect(readCoordinates(stateDir)?.workspace).toBe(workspace);
    expect(readControlToken(stateDir)).toBe("test-token");
  });

  it("rejects an incompatible daemon API version", async () => {
    const workspace = mkdtempSync(join(tmpdir(), "cellwiki-ws-"));
    const stateDir = makeStateDir(workspace);
    writeCoordinates(stateDir, workspace, "old-api");
    await expect(
      ensureDaemon(workspace, {
        env: { ...process.env, CELLWIKI_DAEMON_DIR: join(stateDir, "..") },
        healthCheck: async () => true,
        spawnCli: async () => undefined,
      }),
    ).rejects.toThrow(/incompatible/);
  });

  it("prefers the handoff interpreter when cellwiki is not on PATH", async () => {
    const invocation = resolveCellwikiInvocation({
      PATH: "",
      CELLWIKI_PYTHON: "C:\\venv\\python.exe",
    } as NodeJS.ProcessEnv);
    expect(invocation).toEqual({
      command: "C:\\venv\\python.exe",
      args: ["-m", "cellwiki.product_cli"],
    });
    const workspace = mkdtempSync(join(tmpdir(), "cellwiki-ws-"));
    const override = mkdtempSync(join(tmpdir(), "cellwiki-daemon-"));
    const spawned: string[] = [];
    const coordinates = await ensureDaemon(workspace, {
      env: {
        PATH: "",
        CELLWIKI_PYTHON: "C:\\venv\\python.exe",
        CELLWIKI_DAEMON_DIR: override,
      } as NodeJS.ProcessEnv,
      spawnCli: async (command, args) => {
        spawned.push(command, ...args);
      },
      healthCheck: async () => false,
      timeoutMs: 1,
      sleep: async () => undefined,
    }).catch(() => null);
    expect(coordinates).toBeNull();
    expect(spawned[0]).toBe("C:\\venv\\python.exe");
    expect(spawned.slice(1, 4)).toEqual([
      "-m",
      "cellwiki.product_cli",
      "serve",
    ]);
  });
});
