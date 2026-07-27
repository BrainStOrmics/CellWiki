import { useEffect } from "react";
import { useUiStore } from "../stores/ui-store";

function applyZoom(level: number) {
  document.documentElement.style.setProperty("--ui-zoom", String(level));
}

function isEditableTarget(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && (
    target.isContentEditable
    || target.tagName === "INPUT"
    || target.tagName === "TEXTAREA"
    || target.tagName === "SELECT"
  );
}

/** Own global keyboard zoom without interfering with normal text editing. */
export function ZoomController({
  zoomInLabel,
  zoomOutLabel,
  resetLabel,
}: {
  zoomInLabel: string;
  zoomOutLabel: string;
  resetLabel: string;
}) {
  const zoomLevel = useUiStore((state) => state.zoomLevel);
  const setZoomLevel = useUiStore((state) => state.setZoomLevel);
  const resetZoom = useUiStore((state) => state.resetZoom);

  useEffect(() => {
    applyZoom(zoomLevel);
  }, [zoomLevel]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey)) return;
      if (isEditableTarget(event.target) && event.key !== "0") return;
      if (event.key === "=" || event.key === "+") {
        event.preventDefault();
        setZoomLevel(zoomLevel + 0.1);
      } else if (event.key === "-") {
        event.preventDefault();
        setZoomLevel(zoomLevel - 0.1);
      } else if (event.key === "0") {
        event.preventDefault();
        resetZoom();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [resetZoom, setZoomLevel, zoomLevel]);

  return (
    <div className="zoom-controller" aria-live="polite">
      <span className="sr-only">{`${zoomInLabel} / ${zoomOutLabel} / ${resetLabel}`}</span>
    </div>
  );
}
