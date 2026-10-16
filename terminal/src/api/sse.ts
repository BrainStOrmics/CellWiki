export class SseParser {
  private buffer = "";
  private dataLines: string[] = [];

  push(chunk: string): unknown[] {
    const events: unknown[] = [];
    this.buffer += chunk;
    let newlineIndex = this.buffer.indexOf("\n");
    while (newlineIndex >= 0) {
      let line = this.buffer.slice(0, newlineIndex);
      this.buffer = this.buffer.slice(newlineIndex + 1);
      if (line.endsWith("\r")) {
        line = line.slice(0, -1);
      }
      this.consumeLine(line, events);
      newlineIndex = this.buffer.indexOf("\n");
    }
    return events;
  }

  finish(): unknown[] {
    const events: unknown[] = [];
    if (this.buffer) {
      this.consumeLine(this.buffer, events);
      this.buffer = "";
    }
    this.flush(events);
    return events;
  }

  private consumeLine(line: string, events: unknown[]): void {
    if (line === "") {
      this.flush(events);
      return;
    }
    if (line.startsWith(":")) {
      return;
    }
    const colon = line.indexOf(":");
    const field = colon >= 0 ? line.slice(0, colon) : line;
    const value = colon >= 0 ? line.slice(colon + 1).replace(/^ /, "") : "";
    if (field === "data") {
      this.dataLines.push(value);
    }
  }

  private flush(events: unknown[]): void {
    if (this.dataLines.length === 0) {
      return;
    }
    const payload = this.dataLines.join("\n");
    this.dataLines = [];
    try {
      events.push(JSON.parse(payload));
    } catch {
      throw new Error("daemon returned invalid SSE JSON");
    }
  }
}
