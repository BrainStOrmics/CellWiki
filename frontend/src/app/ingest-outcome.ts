export type IngestOutcome = "committed" | "awaiting_review" | "failed" | "cancelled";

export function resolveIngestOutcome(status: string): IngestOutcome {
  if (status === "succeeded") return "committed";
  if (status === "waiting_approval") return "awaiting_review";
  if (status === "cancelled") return "cancelled";
  return "failed";
}
