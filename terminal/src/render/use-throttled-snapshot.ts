import { useEffect, useRef, useState } from "react";

/**
 * Coalesce high-frequency controller snapshots into a bounded render rate.
 * `intervalMs <= 0` flushes every change immediately (gates, pickers, exit).
 */
export function useThrottledSnapshot<T>(value: T, intervalMs: number): T {
  const [snapshot, setSnapshot] = useState(value);
  const latestRef = useRef(value);
  const lastFlushRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  latestRef.current = value;

  useEffect(() => {
    if (intervalMs <= 0) {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      lastFlushRef.current = Date.now();
      setSnapshot(value);
      return;
    }
    const now = Date.now();
    const elapsed = now - lastFlushRef.current;
    if (elapsed >= intervalMs) {
      lastFlushRef.current = now;
      setSnapshot(value);
      return;
    }
    if (timerRef.current) {
      return;
    }
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      lastFlushRef.current = Date.now();
      setSnapshot(latestRef.current);
    }, intervalMs - elapsed);
  }, [value, intervalMs]);

  useEffect(
    () => () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    },
    [],
  );

  return intervalMs <= 0 ? value : snapshot;
}
