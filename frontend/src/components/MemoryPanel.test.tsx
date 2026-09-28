import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LanguageProvider } from "../i18n";
import { MemoryPanel } from "./MemoryPanel";

const { getJson, putJson, deleteJson } = vi.hoisted(() => ({
  getJson: vi.fn(),
  putJson: vi.fn(),
  deleteJson: vi.fn(),
}));

vi.mock("../lib/product-api", () => ({
  getJson,
  putJson,
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
  updated_at: "2026-09-28T00:00:00+00:00",
};

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
});

describe("MemoryPanel", () => {
  it("lists memories from the API", async () => {
    getJson.mockResolvedValue({ entries: [ENTRY], count: 1 });

    renderPanel();

    await waitFor(() => expect(screen.getByTestId("memory-entry")).toBeTruthy());
    expect(getJson).toHaveBeenCalledWith("/api/memory");
    expect(screen.getByText("逐行审批")).toBeTruthy();
    expect(screen.getByText("run 与审批")).toBeTruthy();
  });

  it("shows the empty state when no memories exist", async () => {
    getJson.mockResolvedValue({ entries: [], count: 0 });

    renderPanel();

    await waitFor(() => expect(screen.queryByTestId("memory-entry")).toBeNull());
    expect(screen.getByText(/还没有记忆/)).toBeTruthy();
  });

  it("deletes a memory through the API and reloads", async () => {
    getJson.mockResolvedValue({ entries: [ENTRY], count: 1 });
    deleteJson.mockResolvedValue({ deleted: "mem_1" });

    renderPanel();
    await waitFor(() => expect(screen.getByTestId("memory-entry")).toBeTruthy());

    fireEvent.click(screen.getByText("删除"));

    await waitFor(() => expect(deleteJson).toHaveBeenCalledWith("/api/memory/mem_1"));
    expect(getJson).toHaveBeenCalledTimes(2);
  });

  it("edits a memory body through the API", async () => {
    getJson
      .mockResolvedValueOnce({ entries: [ENTRY], count: 1 })
      .mockResolvedValueOnce({ ...ENTRY, body: "原始正文" })
      .mockResolvedValueOnce({ entries: [ENTRY], count: 1 });
    putJson.mockResolvedValue({ ...ENTRY, body: "改写后的正文" });

    renderPanel();
    await waitFor(() => expect(screen.getByTestId("memory-entry")).toBeTruthy());

    fireEvent.click(screen.getByText("编辑"));
    await waitFor(() => expect(screen.getByTestId("memory-editor")).toBeTruthy());
    fireEvent.change(screen.getByRole("textbox"), {
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
});
