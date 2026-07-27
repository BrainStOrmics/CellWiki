import { describe, expect, it } from "vitest";
import { resolveIngestOutcome } from "./ingest-outcome";

describe("resolveIngestOutcome", () => {
  it("treats a successful auto-approved run as committed", () => {
    expect(resolveIngestOutcome("succeeded")).toBe("committed");
  });

  it("keeps a manual approval interrupt waiting for the review card", () => {
    expect(resolveIngestOutcome("waiting_approval")).toBe("awaiting_review");
  });

  it("does not present failed or cancelled runs as pending review", () => {
    expect(resolveIngestOutcome("failed")).toBe("failed");
    expect(resolveIngestOutcome("cancelled")).toBe("cancelled");
  });
});
