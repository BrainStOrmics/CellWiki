import { beforeEach, describe, expect, it, vi } from "vitest";
import { productFetch } from "../runtime";
import { ProductApiError, getJson } from "./product-api";

vi.mock("../runtime", () => ({
  apiUrl: (path: string) => path,
  productFetch: vi.fn(),
}));

const fetchMock = vi.mocked(productFetch);

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 409 ? "Conflict" : "Error",
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

async function captureError(request: Promise<unknown>): Promise<ProductApiError> {
  try {
    await request;
  } catch (error) {
    return error as ProductApiError;
  }
  throw new Error("expected the request to fail");
}

/**
 * FastAPI 的 `detail` 有两种形状：裸字符串（既有端点）与 `{code, message}`
 * （需要前端按类别分流的错误）。后者是续跑死结修复的契约——同一个 409 既可能是
 * "图状态没了，永远续不了"，也可能是"串行门禁冲突，稍后再试"，按文案分流会在
 * 文案本地化时静默失效。
 */
describe("Product API error detail", () => {
  beforeEach(() => fetchMock.mockReset());

  it("保留裸字符串 detail，不附带判别码", async () => {
    fetchMock.mockResolvedValue(jsonResponse(409, { detail: "another run is active" }));

    const error = await captureError(getJson("/api/agent/runs/r1/resume"));

    expect(error).toBeInstanceOf(ProductApiError);
    expect(error.message).toBe("another run is active");
    expect(error.status).toBe(409);
    expect(error.code).toBeUndefined();
  });

  it("从 dict detail 里同时取出消息与稳定判别码", async () => {
    fetchMock.mockResolvedValue(jsonResponse(409, {
      detail: {
        code: "checkpoint_missing",
        message: "run r1 has no usable checkpoint; resend the message to start a new run",
      },
    }));

    const error = await captureError(getJson("/api/agent/runs/r1/resume"));

    expect(error.code).toBe("checkpoint_missing");
    expect(error.message).toBe(
      "run r1 has no usable checkpoint; resend the message to start a new run",
    );
  });

  it("认不出 detail 时退回状态行，不把 undefined 当消息抛出去", async () => {
    fetchMock.mockResolvedValue(jsonResponse(500, {}));

    const error = await captureError(getJson("/api/agent/runs"));

    expect(error.message).toBe("500 Error");
    expect(error.code).toBeUndefined();
  });

  it("响应体不是 JSON 时同样退回状态行", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 502,
      statusText: "Bad Gateway",
      json: () => Promise.reject(new Error("not json")),
    } as unknown as Response);

    const error = await captureError(getJson("/api/agent/runs"));

    expect(error.message).toBe("502 Bad Gateway");
  });
});
