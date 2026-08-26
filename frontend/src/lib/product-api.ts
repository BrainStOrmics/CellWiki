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
    const body = await response.json().catch(() => null) as { detail?: unknown } | null;
    const message = body && typeof body.detail === "string"
      ? body.detail
      : `${response.status} ${response.statusText}`;
    throw new ProductApiError(message, response.status, body);
  }
  return response.json() as Promise<T>;
}

export async function getJson<T>(path: string): Promise<T> {
  return parseResponse<T>(await productFetch(path));
}

export async function getText(path: string): Promise<string> {
  const response = await productFetch(path);
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: unknown } | null;
    throw new ProductApiError(
      body && typeof body.detail === "string" ? body.detail : `${response.status} ${response.statusText}`,
      response.status,
      body,
    );
  }
  return response.text();
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  return parseResponse<T>(await productFetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  }));
}

export async function deleteJson<T>(path: string): Promise<T> {
  const response = await productFetch(path, { method: "DELETE" });
  // DELETE 端点使用 204 No Content；空响应体不能走 parseResponse 的 json() 解析
  if (response.status === 204) return undefined as T;
  return parseResponse<T>(response);
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

