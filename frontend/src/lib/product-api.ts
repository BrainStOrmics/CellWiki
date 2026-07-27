import { apiUrl, productFetch } from "../runtime";

export class ProductApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message);
  }
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const detail = await response.json().catch(() => null) as { detail?: string } | null;
    throw new ProductApiError(
      detail?.detail ?? `${response.status} ${response.statusText}`,
      response.status,
      detail,
    );
  }
  return response.json() as Promise<T>;
}

export async function getJson<T>(path: string): Promise<T> {
  return parseResponse<T>(await productFetch(path));
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  return parseResponse<T>(await productFetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  }));
}

export async function deleteJson<T>(path: string): Promise<T> {
  return parseResponse<T>(await productFetch(path, { method: "DELETE" }));
}

export async function uploadFile<T>(path: string, file: File): Promise<T> {
  const body = new FormData();
  body.append("file", file);
  return parseResponse<T>(await productFetch(path, { method: "POST", body }));
}

export function streamUrl(path: string): string {
  // Agent event streams are read-only; packaged auth protects all mutations while
  // allowing native EventSource reconnect semantics without token query parameters.
  return apiUrl(path);
}

