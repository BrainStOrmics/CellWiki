import { beforeEach, describe, expect, it } from "vitest";
import { normalizePersistedView, useUiStore } from "./ui-store";

describe("UI state boundaries", () => {
  beforeEach(() => {
    localStorage.clear();
    useUiStore.setState({
      activeView: "wiki",
      activeThreadId: null,
      composerPageRef: null,
      activeAttachmentIds: [],
      commandPaletteOpen: false,
      selectedText: "",
      leftWidth: 252,
      rightWidth: 390,
      zoomLevel: 1,
      themeOverride: null,
    });
  });

  it("keeps the active Agent thread independent from the composer page reference", () => {
    const state = useUiStore.getState();
    state.setActiveThreadId("thread-global");
    state.setComposerPageRef({ page_id: "T_cell", title: "T cell", path: "wiki/cell_types/T_cell.md" });
    state.setComposerPageRef({ page_id: "B_cell", title: "B cell", path: "wiki/cell_types/B_cell.md" });

    expect(useUiStore.getState().activeThreadId).toBe("thread-global");
    expect(useUiStore.getState().composerPageRef?.page_id).toBe("B_cell");
  });

  it("keeps selected scientific text out of persisted state", () => {
    useUiStore.getState().setSelectedText("sensitive selected passage");

    const persisted = localStorage.getItem("cellwiki.ui.v2") ?? "";
    expect(persisted).not.toContain("sensitive selected passage");
  });

  it("removes composer references from the end so Backspace can delete chips", () => {
    const state = useUiStore.getState();
    state.setComposerPageRef({ page_id: "T_cell", title: "T cell" });
    state.setActiveAttachmentIds(["att_1", "att_2"]);

    state.removeLastComposerReference();
    expect(useUiStore.getState().activeAttachmentIds).toEqual(["att_1"]);
    expect(useUiStore.getState().composerPageRef?.page_id).toBe("T_cell");

    state.removeLastComposerReference();
    state.removeLastComposerReference();
    expect(useUiStore.getState().activeAttachmentIds).toEqual([]);
    expect(useUiStore.getState().composerPageRef).toBeNull();
  });

  it("clamps and persists the global zoom level", () => {
    const state = useUiStore.getState();
    state.setZoomLevel(1.25);
    expect(useUiStore.getState().zoomLevel).toBe(1.25);
    expect(JSON.parse(localStorage.getItem("cellwiki.ui.v2") ?? "{}").state.zoomLevel).toBe(1.25);

    state.setZoomLevel(2);
    expect(useUiStore.getState().zoomLevel).toBe(1.4);
    state.setZoomLevel(0.2);
    expect(useUiStore.getState().zoomLevel).toBe(0.8);
  });

  it("keeps a temporary theme override out of persisted UI state", () => {
    useUiStore.getState().setThemeOverride("dark");

    expect(useUiStore.getState().themeOverride).toBe("dark");
    expect(localStorage.getItem("cellwiki.ui.v2") ?? "").not.toContain("themeOverride");
  });

  it("does not restore retired feature views as first-level navigation", () => {
    expect(normalizePersistedView("reviews")).toBe("wiki");
    expect(normalizePersistedView("lint")).toBe("wiki");
    expect(normalizePersistedView("research")).toBe("wiki");
    expect(normalizePersistedView("graph")).toBe("wiki");
    expect(normalizePersistedView("search")).toBe("search");
  });
});
