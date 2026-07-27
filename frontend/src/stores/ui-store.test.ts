import { beforeEach, describe, expect, it } from "vitest";
import { useUiStore } from "./ui-store";

describe("UI state boundaries", () => {
  beforeEach(() => {
    localStorage.clear();
    useUiStore.setState({
      activeView: "wiki",
      commandPaletteOpen: false,
      selectedText: "",
      leftWidth: 252,
      rightWidth: 390,
      threadByContext: {},
      zoomLevel: 1,
      themeOverride: null,
    });
  });

  it("isolates durable Agent threads by active context", () => {
    const state = useUiStore.getState();
    state.setContextThread("page:T_cell", "thread-page");
    state.setContextThread("source:paper-1", "thread-source");

    expect(useUiStore.getState().threadByContext).toEqual({
      "page:T_cell": "thread-page",
      "source:paper-1": "thread-source",
    });
  });

  it("keeps selected scientific text out of persisted state", () => {
    useUiStore.getState().setSelectedText("sensitive selected passage");

    const persisted = localStorage.getItem("cellwiki.ui.v2") ?? "";
    expect(persisted).not.toContain("sensitive selected passage");
  });

  it("removes every local context mapping for a deleted thread", () => {
    const state = useUiStore.getState();
    state.setContextThread("page:T_cell", "thread-delete");
    state.setContextThread("source:paper-1", "thread-keep");

    state.clearThread("thread-delete");

    expect(useUiStore.getState().threadByContext).toEqual({
      "source:paper-1": "thread-keep",
    });
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
});
