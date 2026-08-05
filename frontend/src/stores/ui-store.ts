import { create } from "zustand";
import { persist } from "zustand/middleware";

export type WorkspaceView =
  | "wiki"
  | "sources"
  | "reviews"
  | "lint"
  | "search"
  | "graph"
  | "memory"
  | "research"
  | "settings";

const primaryWorkspaceViews = new Set<WorkspaceView>([
  "wiki",
  "sources",
  "search",
  "settings",
]);

/** Keep page-local and legacy feature views out of persisted first-level navigation. */
export function normalizePersistedView(view: unknown): WorkspaceView {
  return typeof view === "string" && primaryWorkspaceViews.has(view as WorkspaceView)
    ? view as WorkspaceView
    : "wiki";
}

export type ThemeOverride = "light" | "dark" | null;

export type PageRef = {
  page_id: string;
  title: string;
  path?: string;
};

export const DEFAULT_ZOOM_LEVEL = 1;
export const MIN_ZOOM_LEVEL = 0.8;
export const MAX_ZOOM_LEVEL = 1.4;
export const ZOOM_STEP = 0.1;

export function clampZoomLevel(level: number): number {
  const clamped = Math.min(MAX_ZOOM_LEVEL, Math.max(MIN_ZOOM_LEVEL, level));
  return Math.round(clamped * 100) / 100;
}

type UiState = {
  activeView: WorkspaceView;
  commandPaletteOpen: boolean;
  selectedText: string;
  leftWidth: number;
  rightWidth: number;
  activeThreadId: string | null;
  composerPageRef: PageRef | null;
  activeAttachmentIds: string[];
  zoomLevel: number;
  themeOverride: ThemeOverride;
  setActiveView: (view: WorkspaceView) => void;
  setCommandPaletteOpen: (open: boolean) => void;
  setSelectedText: (text: string) => void;
  setPanelWidth: (side: "left" | "right", width: number) => void;
  setActiveThreadId: (threadId: string | null) => void;
  setComposerPageRef: (pageRef: PageRef | null) => void;
  setActiveAttachmentIds: (ids: string[]) => void;
  addActiveAttachmentIds: (ids: string[]) => void;
  removeActiveAttachmentId: (id: string) => void;
  clearActiveAttachments: () => void;
  removeLastComposerReference: () => void;
  setZoomLevel: (level: number) => void;
  resetZoom: () => void;
  setThemeOverride: (theme: Exclude<ThemeOverride, null>) => void;
  clearThemeOverride: () => void;
};

type PersistedUiState = Pick<
  UiState,
  | "activeView"
  | "leftWidth"
  | "rightWidth"
  | "activeThreadId"
  | "composerPageRef"
  | "activeAttachmentIds"
  | "zoomLevel"
>;

export const useUiStore = create<UiState>()(persist(
  (set) => ({
    activeView: "wiki",
    commandPaletteOpen: false,
    selectedText: "",
    leftWidth: 252,
    rightWidth: 390,
    activeThreadId: null,
    composerPageRef: null,
    activeAttachmentIds: [],
    zoomLevel: DEFAULT_ZOOM_LEVEL,
    themeOverride: null,
    setActiveView: (activeView) => set({ activeView }),
    setCommandPaletteOpen: (commandPaletteOpen) => set({ commandPaletteOpen }),
    setSelectedText: (selectedText) => set({ selectedText }),
    setPanelWidth: (side, width) => set(side === "left" ? { leftWidth: width } : { rightWidth: width }),
    setActiveThreadId: (activeThreadId) => set({ activeThreadId }),
    setComposerPageRef: (composerPageRef) => set({ composerPageRef }),
    setActiveAttachmentIds: (activeAttachmentIds) => set({ activeAttachmentIds }),
    addActiveAttachmentIds: (ids) => set((state) => ({
      activeAttachmentIds: [...new Set([...state.activeAttachmentIds, ...ids])],
    })),
    removeActiveAttachmentId: (id) => set((state) => ({
      activeAttachmentIds: state.activeAttachmentIds.filter((attachmentId) => attachmentId !== id),
    })),
    clearActiveAttachments: () => set({ activeAttachmentIds: [] }),
    removeLastComposerReference: () => set((state) => {
      if (state.activeAttachmentIds.length > 0) {
        return { activeAttachmentIds: state.activeAttachmentIds.slice(0, -1) };
      }
      if (state.composerPageRef) {
        return { composerPageRef: null };
      }
      return {};
    }),
    setZoomLevel: (level) => set({ zoomLevel: clampZoomLevel(level) }),
    resetZoom: () => set({ zoomLevel: DEFAULT_ZOOM_LEVEL }),
    setThemeOverride: (themeOverride) => set({ themeOverride }),
    clearThemeOverride: () => set({ themeOverride: null }),
  }),
  {
    name: "cellwiki.ui.v2",
    version: 3,
    migrate: (persistedState) => {
      const state = persistedState as Partial<PersistedUiState>;
      return {
        activeView: normalizePersistedView(state.activeView),
        leftWidth: state.leftWidth ?? 252,
        rightWidth: state.rightWidth ?? 390,
        activeThreadId: state.activeThreadId ?? null,
        composerPageRef: state.composerPageRef ?? null,
        activeAttachmentIds: state.activeAttachmentIds ?? [],
        zoomLevel: state.zoomLevel ?? DEFAULT_ZOOM_LEVEL,
      };
    },
    // Selected scientific text is transient and must not leak into durable UI state.
    partialize: (state) => ({
      activeView: normalizePersistedView(state.activeView),
      leftWidth: state.leftWidth,
      rightWidth: state.rightWidth,
      activeThreadId: state.activeThreadId,
      composerPageRef: state.composerPageRef,
      activeAttachmentIds: state.activeAttachmentIds,
      zoomLevel: state.zoomLevel,
    }),
  },
));
