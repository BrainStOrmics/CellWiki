import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LanguageProvider } from "../i18n";
import type { ChangeSetReview, Source, TaskEvent } from "../types";
import { SourceReview } from "./SourceReview";

const source: Source = {
  source_id: "source-paper",
  source_type: "pdf",
  original_name: "paper.pdf",
  status: "ready",
  content_hash: "0123456789abcdef0123456789abcdef",
};

const taskEvent: TaskEvent = {
  event_id: "event-1",
  run_id: "ingest-test",
  source_id: source.source_id,
  stage: "entity_extraction",
  status: "running",
  message: "Extracting chunk 2 of 8.",
  progress: 40,
  detail: {
    chunk_index: 2,
    chunk_count: 8,
    attempt: 2,
    max_attempts: 3,
    elapsed_seconds: 123,
    estimated_remaining_seconds: 300,
  },
  created_at: "2026-07-18T10:00:00Z",
};

const review: ChangeSetReview = {
  change_set: {
    change_set_id: "cs-review",
    run_id: "run-review",
    project_id: "cellwiki",
    operations: [],
    evidence: [],
    review_items: [],
    risk: "medium",
    reason: "Review fixture",
    created_at: "2026-07-18T10:00:00Z",
  },
  status: "awaiting_review",
  preview: {
    operations: [],
    summary: { added: 0, removed: 0, changed: 0 },
  },
};

describe("SourceReview", () => {
  it("shows ingest progress details and lets the user cancel the active run", () => {
    const cancel = vi.fn();
    render(
      <LanguageProvider>
        <SourceReview
          source={source}
          workflow={{ phase: "preparing", message: "Preparing" }}
          taskEvents={[taskEvent]}
          onPrepare={vi.fn()}
          onCancel={cancel}
          onApprove={vi.fn()}
          onReject={vi.fn()}
          onRollback={vi.fn()}
          onProposeFix={vi.fn()}
        />
      </LanguageProvider>,
    );

    expect(screen.getByText("分块 2 / 8")).toBeInTheDocument();
    expect(screen.getByText("尝试 2 / 3")).toBeInTheDocument();
    expect(screen.getByText("已用时 2分03秒")).toBeInTheDocument();
    expect(screen.getByText("预计剩余 5分00秒")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "取消摄取" }));
    expect(cancel).toHaveBeenCalledOnce();
  });

  it("submits reviewer comments for a same-source re-ingest", () => {
    const requestRevision = vi.fn();
    render(
      <LanguageProvider>
        <SourceReview
          source={source}
          review={review}
          workflow={{ phase: "awaiting_review", message: "Review" }}
          taskEvents={[]}
          onPrepare={vi.fn()}
          onCancel={vi.fn()}
          onApprove={vi.fn()}
          onReject={vi.fn()}
          onRollback={vi.fn()}
          onProposeFix={vi.fn()}
          onRequestRevision={requestRevision}
        />
      </LanguageProvider>,
    );

    fireEvent.change(screen.getByTestId("revision-comment"), {
      target: { value: "Add the missing evidence section." },
    });
    fireEvent.click(screen.getByTestId("request-revision"));

    expect(requestRevision).toHaveBeenCalledWith("Add the missing evidence section.");
  });
});
