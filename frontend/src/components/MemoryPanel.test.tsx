import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LanguageProvider } from "../i18n";
import { MemoryPanel } from "./MemoryPanel";

const { getJson, putJson, postJson, deleteJson } = vi.hoisted(() => ({
  getJson: vi.fn(),
  putJson: vi.fn(),
  postJson: vi.fn(),
  deleteJson: vi.fn(),
}));

vi.mock("../lib/product-api", () => ({
  getJson,
  putJson,
  postJson,
  deleteJson,
}));

const ENTRY = {
  memory_id: "mem_1",
  kind: "preference",
  topic_family: "run 与审批",
  title: "逐行审批",
  file_name: "run-approval.md",
  user_edited: false,
  auto_update: true,
  origin_thread_id: "thread_api",
  origin_run_id: "run_api",
  source_refs: ["thread:thread_api", "run:run_api"],
  updated_at: "2026-09-28T00:00:00+00:00",
};

const VIEWS = [
  {
    file_name: "memory_summary.md",
    read_only: true,
    exists: true,
    updated_at: "2026-09-29T00:00:00+00:00",
  },
  {
    file_name: "MEMORY.md",
    read_only: true,
    exists: false,
    updated_at: null,
  },
];

const STATUS = {
  enabled: true,
  auto_extract: true,
  min_idle_hours: 4,
  debounce_minutes: 1,
  daily_extractions: 24,
  pending_candidates: 2,
  jobs_pending: 2,
  jobs_leased: 1,
  jobs_failed: 0,
  next_job_at: "2026-09-29T16:00:00+00:00",
  last_job_status: "succeeded_no_output",
  last_job_error: "",
  last_job_updated_at: "2026-09-29T12:00:00+00:00",
  last_consolidated_at: null,
};

function payload(overrides: Record<string, unknown> = {}) {
  return {
    entries: [ENTRY],
    count: 1,
    views: VIEWS,
    status: STATUS,
    ...overrides,
  };
}

function renderPanel() {
  return render(
    <LanguageProvider>
      <MemoryPanel />
    </LanguageProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe("MemoryPanel", () => {
  it("renders scheduler status and unified file rows", async () => {
    getJson.mockResolvedValue(payload());

    renderPanel();

    await waitFor(() => expect(screen.getByTestId("memory-entry")).toBeTruthy());
    expect(getJson).toHaveBeenCalledWith("/api/memory");
    expect(screen.getByTestId("memory-status")).toBeTruthy();
    expect(screen.getByText("已开启")).toBeTruthy();
    expect(screen.getByText("4 小时")).toBeTruthy();
    expect(screen.getByText("2 待处理 · 1 进行中 · 0 失败")).toBeTruthy();
    expect(screen.getByText("run-approval.md")).toBeTruthy();
    expect(screen.getByText("memory_summary.md")).toBeTruthy();
    expect(screen.getByText("MEMORY.md")).toBeTruthy();
    expect(screen.getByText("尚未生成")).toBeTruthy();
  });

  it("shows the empty state when no memories exist", async () => {
    getJson.mockResolvedValue(
      payload({ entries: [], count: 0, status: { ...STATUS, pending_candidates: 0 } }),
    );

    renderPanel();

    await waitFor(() => expect(screen.queryByTestId("memory-entry")).toBeNull());
    expect(screen.getByText(/还没有成型记忆/)).toBeTruthy();
  });

  it("opens a derived view as read-only content", async () => {
    getJson
      .mockResolvedValueOnce(payload())
      .mockResolvedValueOnce({
        ...VIEWS[0],
        content: "v1\n\n## User Preferences\n逐行审批。",
      });

    renderPanel();
    await waitFor(() => expect(screen.getByTestId("memory-entry")).toBeTruthy());

    fireEvent.click(screen.getByTestId("memory-view-memory_summary.md"));

    await waitFor(() =>
      expect(getJson).toHaveBeenCalledWith(
        "/api/memory/views/memory_summary.md",
      ),
    );
    expect(screen.getByTestId("memory-view-content").textContent).toContain(
      "逐行审批",
    );
    expect(screen.queryByText("编辑")).toBeNull();
  });

  it("opens a topic file with edit and delete actions", async () => {
    getJson
      .mockResolvedValueOnce(payload())
      .mockResolvedValueOnce({ ...ENTRY, body: "原始正文" });

    renderPanel();
    await waitFor(() => expect(screen.getByTestId("memory-entry")).toBeTruthy());

    fireEvent.click(screen.getByTestId("memory-entry-open"));

    await waitFor(() =>
      expect(getJson).toHaveBeenCalledWith("/api/memory/mem_1"),
    );
    expect(screen.getByTestId("memory-file-content").textContent).toContain(
      "原始正文",
    );
    expect(screen.getByText("编辑")).toBeTruthy();
    expect(screen.getByText("删除")).toBeTruthy();
  });

  it("deletes a memory through the API and reloads", async () => {
    getJson
      .mockResolvedValueOnce(payload())
      .mockResolvedValueOnce({ ...ENTRY, body: "原始正文" })
      .mockResolvedValueOnce(payload({ entries: [], count: 0 }));
    deleteJson.mockResolvedValue({ deleted: "mem_1" });

    renderPanel();
    await waitFor(() => expect(screen.getByTestId("memory-entry")).toBeTruthy());

    fireEvent.click(screen.getByTestId("memory-entry-open"));
    await waitFor(() => expect(screen.getByText("删除")).toBeTruthy());
    fireEvent.click(screen.getByText("删除"));

    await waitFor(() => expect(deleteJson).toHaveBeenCalledWith("/api/memory/mem_1"));
    expect(getJson).toHaveBeenCalledTimes(3);
  });

  it("edits a memory body through the API", async () => {
    getJson
      .mockResolvedValueOnce(payload())
      .mockResolvedValueOnce({ ...ENTRY, body: "原始正文" })
      .mockResolvedValueOnce(payload());
    putJson.mockResolvedValue({ ...ENTRY, body: "改写后的正文" });

    renderPanel();
    await waitFor(() => expect(screen.getByTestId("memory-entry")).toBeTruthy());

    fireEvent.click(screen.getByTestId("memory-entry-open"));
    await waitFor(() => expect(screen.getByText("编辑")).toBeTruthy());
    fireEvent.click(screen.getByText("编辑"));
    await waitFor(() => expect(screen.getByTestId("memory-editor")).toBeTruthy());
    fireEvent.change(screen.getByTestId("memory-editor").querySelector("textarea")!, {
      target: { value: "改写后的正文" },
    });
    fireEvent.click(screen.getByText("保存"));

    await waitFor(() =>
      expect(putJson).toHaveBeenCalledWith("/api/memory/mem_1", {
        body: "改写后的正文",
        reenable_auto_update: false,
      }),
    );
  });

  it("consolidates pending candidates when some exist", async () => {
    getJson.mockResolvedValue(payload());
    postJson.mockResolvedValue({ consolidated: 0, entries: [] });

    renderPanel();
    await waitFor(() => expect(screen.getByTestId("memory-entry")).toBeTruthy());

    const button = screen.getByTestId("memory-consolidate") as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    fireEvent.click(button);

    await waitFor(() =>
      expect(postJson).toHaveBeenCalledWith("/api/memory/consolidate", {}),
    );
    expect(getJson).toHaveBeenCalledTimes(2);
  });

  it("disables consolidation when no candidates are pending", async () => {
    getJson.mockResolvedValue(
      payload({ status: { ...STATUS, pending_candidates: 0 } }),
    );

    renderPanel();
    await waitFor(() => expect(screen.getByTestId("memory-entry")).toBeTruthy());

    const button = screen.getByTestId("memory-consolidate") as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it("deletes memories by source after confirmation", async () => {
    getJson.mockResolvedValue(payload());
    deleteJson.mockResolvedValue({ deleted_entries: 1, deleted_candidates: 0 });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    renderPanel();
    await waitFor(() => expect(screen.getByTestId("memory-entry")).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText("thread_id 或 run_id"), {
      target: { value: "thread_api" },
    });
    fireEvent.click(screen.getByTestId("memory-clean-source"));

    await waitFor(() =>
      expect(deleteJson).toHaveBeenCalledWith("/api/memory/sources/thread_api"),
    );
    expect(getJson).toHaveBeenCalledTimes(2);
  });

  it("keeps memories when the source cleanup confirmation is cancelled", async () => {
    getJson.mockResolvedValue(payload());
    vi.spyOn(window, "confirm").mockReturnValue(false);

    renderPanel();
    await waitFor(() => expect(screen.getByTestId("memory-entry")).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText("thread_id 或 run_id"), {
      target: { value: "thread_api" },
    });
    fireEvent.click(screen.getByTestId("memory-clean-source"));

    await waitFor(() => expect(window.confirm).toHaveBeenCalled());
    expect(deleteJson).not.toHaveBeenCalled();
  });

  it("keeps maintenance actions behind the maintenance disclosure", async () => {
    getJson.mockResolvedValue(payload());

    renderPanel();
    await waitFor(() => expect(screen.getByTestId("memory-entry")).toBeTruthy());

    const maintenance = screen.getByTestId("memory-maintenance");
    expect(maintenance.querySelector("summary")?.textContent).toContain("维护");
    expect(maintenance.querySelector("button.danger")).toBeTruthy();
  });
});
