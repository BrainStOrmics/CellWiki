import { useStdout } from "ink";
import { useEffect, useState } from "react";

export interface TerminalSize {
  rows: number;
  columns: number;
}

export function useTerminalSize(override?: TerminalSize): TerminalSize {
  const { stdout } = useStdout();
  const source = stdout as unknown as SizeSource;
  const [size, setSize] = useState<TerminalSize>(() => readSize(source));

  useEffect(() => {
    if (override) {
      return;
    }
    const update = (): void => setSize(readSize(source));
    update();
    source.on("resize", update);
    return () => {
      source.off("resize", update);
    };
  }, [source, override]);

  return override ?? size;
}

interface SizeSource {
  rows?: number;
  columns?: number;
  on(event: "resize", listener: () => void): unknown;
  off(event: "resize", listener: () => void): unknown;
}

function readSize(source: SizeSource): TerminalSize {
  const rows = source.rows;
  const columns = source.columns;
  return {
    rows: typeof rows === "number" && rows > 0 ? rows : 24,
    columns: typeof columns === "number" && columns > 0 ? columns : 80,
  };
}
