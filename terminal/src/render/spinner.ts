import { useEffect, useState } from "react";

export const SPINNER_FRAMES = [
  "⠋",
  "⠙",
  "⠹",
  "⠸",
  "⠼",
  "⠴",
  "⠦",
  "⠧",
  "⠇",
  "⠏",
] as const;

export function useSpinnerFrame(busy: boolean, intervalMs = 200): string {
  const [frame, setFrame] = useState(0);
  useEffect(() => {
    if (!busy) {
      return;
    }
    const timer = setInterval(() => {
      setFrame((value) => value + 1);
    }, Math.max(50, intervalMs));
    return () => clearInterval(timer);
  }, [busy, intervalMs]);
  return SPINNER_FRAMES[frame % SPINNER_FRAMES.length] ?? SPINNER_FRAMES[0];
}
