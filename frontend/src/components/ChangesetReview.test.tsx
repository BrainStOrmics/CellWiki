import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(cleanup);
import i18nSource from "../i18n.tsx?raw";
import { LanguageProvider } from "../i18n";
import type { ChangeSetReview, TaskEvent } from "../types";
import { ChangesetReview } from "./ChangesetReview";

const taskEvent: TaskEvent = {
  event_id: "event-1",
  run_id: "ingest-test",
  source_id: "source-paper",
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

function renderReview(overrides: Partial<Parameters<typeof ChangesetReview>[0]> = {}) {
  return render(
    <LanguageProvider>
      <ChangesetReview
        review={review}
        workflow={{ phase: "awaiting_review", message: "Review" }}
        taskEvents={[]}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        onRollback={vi.fn()}
        onDelete={vi.fn()}
        {...overrides}
      />
    </LanguageProvider>,
  );
}

describe("ChangesetReview", () => {
  it("shows ingest progress details without a duplicate task control", () => {
    renderReview({ workflow: { phase: "preparing", message: "Preparing" }, taskEvents: [taskEvent] });

    expect(screen.getByText("分块 2 / 8")).toBeInTheDocument();
    expect(screen.getByText("尝试 2 / 3")).toBeInTheDocument();
    expect(screen.getByText("已用时 2分03秒")).toBeInTheDocument();
    expect(screen.getByText("预计剩余 5分00秒")).toBeInTheDocument();

    expect(screen.queryByText("取消摄取")).not.toBeInTheDocument();
  });

  it("submits reviewer comments for a same-source re-ingest", () => {
    const requestRevision = vi.fn();
    renderReview({ onRequestRevision: requestRevision });

    fireEvent.change(screen.getByTestId("revision-comment"), {
      target: { value: "Add the missing evidence section." },
    });
    fireEvent.click(screen.getByTestId("request-revision"));

    expect(requestRevision).toHaveBeenCalledWith("Add the missing evidence section.");
  });

  it("offers deletion only for decided terminal proposals", () => {
    const onDelete = vi.fn();
    const { unmount } = renderReview({ onDelete });

    expect(screen.queryByTestId("delete-changeset")).not.toBeInTheDocument();
    unmount();

    renderReview({ review: { ...review, status: "rejected" }, onDelete });
    fireEvent.click(screen.getByTestId("delete-changeset"));
    expect(onDelete).toHaveBeenCalledTimes(1);
  });

  it("keeps approve and reject enabled while awaiting review and disabled while committing", () => {
    const { unmount } = renderReview();

    expect(screen.getByRole("button", { name: /批准并发布/ })).toBeEnabled();
    unmount();

    renderReview({ workflow: { phase: "committing", message: "Committing" } });
    expect(screen.getByRole("button", { name: /批准并发布/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /拒绝/ })).toBeDisabled();
  });

  it("presents ChangeSets as review records, not Agent question targets", () => {
    expect(i18nSource).not.toContain('"chat.sourcePlaceholder": "Ask about this source or its ChangeSet..."');
    expect(i18nSource).toContain('"chat.sourcePlaceholder": "Review this source status and any ChangeSet."');
  });
});
