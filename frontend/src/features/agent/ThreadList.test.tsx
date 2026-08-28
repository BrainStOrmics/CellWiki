import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThreadList, type ThreadSelection } from "./ThreadList";
import { getJson } from "../../lib/product-api";
import type { AgentThreadEntry } from "../../types";
import { LanguageProvider } from "../../i18n";

vi.mock("../../lib/product-api", () => ({
  getJson: vi.fn(),
}));

vi.mock("../../runtime", () => ({
  productFetch: vi.fn().mockResolvedValue({ ok: false }),
}));

function thread(overrides: Partial<AgentThreadEntry> = {}): AgentThreadEntry {
  return {
    thread_id: "thread_0000000001",
    title: null,
    created_at: "2026-08-28T07:00:00+00:00",
    updated_at: "2026-08-28T07:00:00+00:00",
    run_count: 1,
    latest_run_id: "run_1",
    latest_status: "succeeded",
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderThreadList(onSelect: (thread: ThreadSelection) => void = () => undefined) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <LanguageProvider>
        <ThreadList
          currentThreadId={null}
          onSelect={onSelect}
          onDelete={async () => undefined}
        />
      </LanguageProvider>
    </QueryClientProvider>,
  );
}

describe("ThreadList", () => {
  it("reads the conversation registry and refetches it when the dropdown expands", async () => {
    const getJsonMock = vi.mocked(getJson);
    getJsonMock.mockResolvedValue([]);
    renderThreadList();
    await waitFor(() => expect(getJsonMock).toHaveBeenCalledTimes(1));
    expect(getJsonMock).toHaveBeenCalledWith("/api/agent/threads?limit=200");

    fireEvent.click(screen.getByRole("button", { name: /对话/ }));
    await waitFor(() => expect(getJsonMock).toHaveBeenCalledTimes(2));
  });

  it("shows a session that has no run yet as a selectable placeholder", async () => {
    const selected: ThreadSelection[] = [];
    const getJsonMock = vi.mocked(getJson);
    getJsonMock.mockResolvedValue([thread({ run_count: 0, latest_run_id: null, latest_status: null })]);
    renderThreadList((entry) => selected.push(entry));

    fireEvent.click(screen.getByRole("button", { name: /对话/ }));
    expect(await screen.findByText("新会话")).toBeInTheDocument();
    expect(screen.getByText("未开始")).toBeInTheDocument();

    fireEvent.click(screen.getByText("新会话"));
    expect(selected).toEqual([{ threadId: "thread_0000000001", latestRunId: null }]);
  });

  it("shows the session id once the first run exists and prefers a title when present", async () => {
    const getJsonMock = vi.mocked(getJson);
    getJsonMock.mockResolvedValue([
      thread({ thread_id: "thread_finished_1", latest_status: "failed" }),
      thread({ thread_id: "thread_named_1", title: "胰岛细胞综述" }),
    ]);
    renderThreadList();

    fireEvent.click(screen.getByRole("button", { name: /对话/ }));
    expect(await screen.findByText("finished_1")).toBeInTheDocument();
    expect(screen.getByText(/failed · 1 次运行/)).toBeInTheDocument();
    expect(screen.getByText("胰岛细胞综述")).toBeInTheDocument();
    expect(screen.queryByText("named_1")).not.toBeInTheDocument();
  });
});
