import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import i18nSource from "../i18n.tsx?raw";
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
  it("shows ingest progress details without a duplicate task control", () => {
    render(
      <LanguageProvider>
        <SourceReview
          source={source}
          workflow={{ phase: "preparing", message: "Preparing" }}
          taskEvents={[taskEvent]}
          onApprove={vi.fn()}
          onReject={vi.fn()}
          onRollback={vi.fn()}
        />
      </LanguageProvider>,
    );

    expect(screen.getByText("分块 2 / 8")).toBeInTheDocument();
    expect(screen.getByText("尝试 2 / 3")).toBeInTheDocument();
    expect(screen.getByText("已用时 2分03秒")).toBeInTheDocument();
    expect(screen.getByText("预计剩余 5分00秒")).toBeInTheDocument();

    expect(screen.queryByText("取消摄取")).not.toBeInTheDocument();
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
          onApprove={vi.fn()}
          onReject={vi.fn()}
          onRollback={vi.fn()}
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

  it("keeps long source names inspectable when the header is visually clamped", () => {
    const longName = "ENCSR659HPI.research.with.a.very.long.registered-source-name.json";

    render(
      <LanguageProvider>
        <SourceReview
          source={{ ...source, original_name: longName }}
          workflow={{ phase: "awaiting_review", message: "Review" }}
          taskEvents={[]}
          onApprove={vi.fn()}
          onReject={vi.fn()}
          onRollback={vi.fn()}
        />
      </LanguageProvider>,
    );

    const title = screen.getByRole("heading", { name: longName });
    expect(title).toHaveClass("source-review-title");
    expect(title).toHaveAttribute("title", longName);
  });

  it("presents sources as review records, not Agent question targets", () => {
    render(
      <LanguageProvider>
        <SourceReview
          source={source}
          workflow={{ phase: "idle", message: "Ready" }}
          taskEvents={[]}
          onApprove={vi.fn()}
          onReject={vi.fn()}
          onRollback={vi.fn()}
        />
      </LanguageProvider>,
    );

    expect(i18nSource).not.toContain('"chat.sourcePlaceholder": "Ask about this source or its ChangeSet..."');
    expect(i18nSource).toContain('"chat.sourcePlaceholder": "Review this source status and any ChangeSet."');
  });
});
