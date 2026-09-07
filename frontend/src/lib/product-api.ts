import { apiUrl, productFetch } from "../runtime";

export class ProductApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
    readonly code?: string,
  ) {
    super(message);
  }
}

/** FastAPI 的 `detail` 既可能是裸字符串，也可能是 `{code, message}`。后者用于需要
 *  前端按类别分流、而不是按文案分流的错误——例如续跑被永久拒绝时要把「继续」换成
 *  「重试」。码是契约，文案不是，所以文案日后本地化不会打断分流。 */
function readDetail(
  body: { detail?: unknown } | null,
): { message: string | null; code: string | null } {
  const detail = body?.detail;
  if (typeof detail === "string") return { message: detail, code: null };
  if (detail && typeof detail === "object") {
    const record = detail as { message?: unknown; code?: unknown };
    return {
      message: typeof record.message === "string" ? record.message : null,
      code: typeof record.code === "string" ? record.code : null,
    };
  }
  return { message: null, code: null };
}

function toApiError(body: { detail?: unknown } | null, response: Response): ProductApiError {
  const { message, code } = readDetail(body);
  return new ProductApiError(
    message ?? `${response.status} ${response.statusText}`,
    response.status,
    body,
    code ?? undefined,
  );
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: unknown } | null;
    throw toApiError(body, response);
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
    throw toApiError(body, response);
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

