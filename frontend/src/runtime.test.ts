import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { invoke } = vi.hoisted(() => ({
  invoke: vi.fn(),
}));

vi.mock("@tauri-apps/api/core", () => ({ invoke }));

describe("desktop runtime initialization", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.resetModules();
    invoke.mockReset();
    Object.defineProperty(window, "__TAURI_INTERNALS__", {
      configurable: true,
      value: {},
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    Reflect.deleteProperty(window, "__TAURI_INTERNALS__");
  });

  it("retries the coordinate lookup while the Tauri sidecar is starting", async () => {
    const readyRuntime = {
      productApiOrigin: "http://127.0.0.1:50750",
      bearerToken: "launch-token",
      mode: "development",
      logsDir: "logs",
      ready: true,
      error: null,
    };
    invoke
      .mockRejectedValueOnce(new Error("desktop runtime state is not managed yet"))
      .mockResolvedValueOnce(readyRuntime);
    const runtimeModule = await import("./runtime");

    const initialization = runtimeModule.initializeRuntime();
    await vi.runAllTimersAsync();

    await expect(initialization).resolves.toEqual(readyRuntime);
    expect(invoke).toHaveBeenCalledTimes(2);
    expect(runtimeModule.apiUrl("/health")).toBe("http://127.0.0.1:50750/health");
  });
});
