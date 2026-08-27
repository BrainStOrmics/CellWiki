import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThreadList } from "./ThreadList";
import { getJson } from "../../lib/product-api";
import { LanguageProvider } from "../../i18n";

vi.mock("../../lib/product-api", () => ({
  getJson: vi.fn(),
}));

vi.mock("../../runtime", () => ({
  productFetch: vi.fn().mockResolvedValue({ ok: false }),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderThreadList() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <LanguageProvider>
        <ThreadList
          currentThreadId={null}
          onSelect={() => undefined}
          onDelete={async () => undefined}
        />
      </LanguageProvider>
    </QueryClientProvider>,
  );
}

describe("ThreadList", () => {
  it("refetches thread history immediately when the dropdown expands", async () => {
    const getJsonMock = vi.mocked(getJson);
    getJsonMock.mockResolvedValue([]);
    renderThreadList();
    await waitFor(() => expect(getJsonMock).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: /对话/ }));
    await waitFor(() => expect(getJsonMock).toHaveBeenCalledTimes(2));
  });

  it("shows a newly created session as soon as fresh data lands", async () => {
    const getJsonMock = vi.mocked(getJson);
    getJsonMock.mockResolvedValue([]);
    renderThreadList();
    await waitFor(() => expect(getJsonMock).toHaveBeenCalledTimes(1));

    getJsonMock.mockResolvedValue([
      {
        run_id: "run_1",
        thread_id: "abc_000001",
        project_id: "cellwiki",
        status: "succeeded",
        finished_at: "2026-08-26T00:00:00Z",
        retry_count: 0,
        retryable: false,
        cancellable: false,
        resumable: false,
        usage: {
          model_calls: 1,
          input_tokens: 0,
          output_tokens: 0,
          estimated_cost_usd: 0,
          tool_calls: 0,
          elapsed_seconds: 0,
        },
      },
    ]);
    fireEvent.click(screen.getByRole("button", { name: /对话/ }));
    await waitFor(() => expect(getJsonMock).toHaveBeenCalledTimes(2));
    expect(await screen.findByText(/abc_000001/)).toBeInTheDocument();
  });
});
