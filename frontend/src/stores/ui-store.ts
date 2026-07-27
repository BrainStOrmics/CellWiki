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

export type ThemeOverride = "light" | "dark" | null;

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
  threadByContext: Record<string, string>;
  zoomLevel: number;
  themeOverride: ThemeOverride;
  setActiveView: (view: WorkspaceView) => void;
  setCommandPaletteOpen: (open: boolean) => void;
  setSelectedText: (text: string) => void;
  setPanelWidth: (side: "left" | "right", width: number) => void;
  setContextThread: (contextKey: string, threadId: string) => void;
  clearContextThread: (contextKey: string) => void;
  clearThread: (threadId: string) => void;
  setZoomLevel: (level: number) => void;
  resetZoom: () => void;
  setThemeOverride: (theme: Exclude<ThemeOverride, null>) => void;
  clearThemeOverride: () => void;
};

export const useUiStore = create<UiState>()(persist(
  (set) => ({
    activeView: "wiki",
    commandPaletteOpen: false,
    selectedText: "",
    leftWidth: 252,
    rightWidth: 390,
    threadByContext: {},
    zoomLevel: DEFAULT_ZOOM_LEVEL,
    themeOverride: null,
    setActiveView: (activeView) => set({ activeView }),
    setCommandPaletteOpen: (commandPaletteOpen) => set({ commandPaletteOpen }),
    setSelectedText: (selectedText) => set({ selectedText }),
    setPanelWidth: (side, width) => set(side === "left" ? { leftWidth: width } : { rightWidth: width }),
    setContextThread: (contextKey, threadId) => set((state) => ({
      threadByContext: { ...state.threadByContext, [contextKey]: threadId },
    })),
    clearContextThread: (contextKey) => set((state) => {
      const threadByContext = { ...state.threadByContext };
      delete threadByContext[contextKey];
      return { threadByContext };
    }),
    clearThread: (threadId) => set((state) => ({
      threadByContext: Object.fromEntries(
        Object.entries(state.threadByContext).filter(([, value]) => value !== threadId),
      ),
    })),
    setZoomLevel: (level) => set({ zoomLevel: clampZoomLevel(level) }),
    resetZoom: () => set({ zoomLevel: DEFAULT_ZOOM_LEVEL }),
    setThemeOverride: (themeOverride) => set({ themeOverride }),
    clearThemeOverride: () => set({ themeOverride: null }),
  }),
  {
    name: "cellwiki.ui.v2",
    // Selected scientific text is transient and must not leak into durable UI state.
    partialize: (state) => ({
      activeView: state.activeView,
      leftWidth: state.leftWidth,
      rightWidth: state.rightWidth,
      threadByContext: state.threadByContext,
      zoomLevel: state.zoomLevel,
    }),
  },
));
