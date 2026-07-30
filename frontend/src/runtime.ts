import { invoke } from "@tauri-apps/api/core";

// Browser-based smoke tests use an isolated API port; normal development keeps
// the desktop runtime's documented 8000 default.
const DEVELOPMENT_PRODUCT_API_ORIGIN =
  import.meta.env.VITE_PRODUCT_API_ORIGIN || "http://127.0.0.1:8000";
const RUNTIME_CONFIG_RETRY_DELAY_MS = 250;
const RUNTIME_CONFIG_MAX_ATTEMPTS = 500;

export type DesktopRuntimeConfig = {
  productApiOrigin: string;
  bearerToken: string;
  mode: "development" | "packaged" | "unknown";
  logsDir: string;
  ready: boolean;
  error?: string | null;
};

type TauriWindow = Window & {
  __TAURI_INTERNALS__?: unknown;
};

export const isDesktopRuntime = (() => {
  if (typeof window === "undefined") return false;
  return Boolean((window as TauriWindow).__TAURI_INTERNALS__);
})();

let runtime: DesktopRuntimeConfig = {
  productApiOrigin: DEVELOPMENT_PRODUCT_API_ORIGIN,
  bearerToken: "",
  mode: "development",
  logsDir: "logs",
  ready: true,
  error: null,
};

export async function initializeRuntime(): Promise<DesktopRuntimeConfig> {
  if (!isDesktopRuntime) return runtime;
  let lastError: unknown;
  for (let attempt = 0; attempt < RUNTIME_CONFIG_MAX_ATTEMPTS; attempt += 1) {
    try {
      runtime = await invoke<DesktopRuntimeConfig>("runtime_config");
      return runtime;
    } catch (error) {
      // Tauri can expose the WebView before its blocking setup hook finishes
      // starting the Python sidecar and registering managed runtime state.
      lastError = error;
      if (attempt + 1 < RUNTIME_CONFIG_MAX_ATTEMPTS) {
        await new Promise((resolve) => window.setTimeout(resolve, RUNTIME_CONFIG_RETRY_DELAY_MS));
      }
    }
  }
  runtime = {
    ...runtime,
    mode: "unknown",
    ready: false,
    error: lastError instanceof Error ? lastError.message : String(lastError),
  };
  return runtime;
}

export function runtimeConfig(): DesktopRuntimeConfig {
  return runtime;
}

function normalizePath(path: string): string {
  return path.startsWith("/") ? path : `/${path}`;
}

export function apiUrl(path: string): string {
  return `${runtime.productApiOrigin || DEVELOPMENT_PRODUCT_API_ORIGIN}${normalizePath(path)}`;
}

export function productFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (runtime.bearerToken) headers.set("Authorization", `Bearer ${runtime.bearerToken}`);
  return fetch(apiUrl(path), { ...init, headers });
}

export async function restartBackend(): Promise<DesktopRuntimeConfig> {
  if (!isDesktopRuntime) throw new Error("Backend restart is available in the desktop application only.");
  runtime = await invoke<DesktopRuntimeConfig>("restart_backend");
  return runtime;
}

export async function openLogsDirectory(): Promise<void> {
  if (!isDesktopRuntime) throw new Error("Log directory is available in the desktop application only.");
  await invoke("open_logs");
}
