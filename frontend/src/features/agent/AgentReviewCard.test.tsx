import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LanguageProvider } from "../../i18n";
import { AgentReviewCard } from "./AgentReviewCard";

describe("AgentReviewCard", () => {
  it("shows the ingest summary and submits reviewer feedback", () => {
    const approve = vi.fn();
    const reject = vi.fn();
    const requestRevision = vi.fn();

    render(
      <LanguageProvider>
        <AgentReviewCard
          changeSetId="cs-ingest"
          summary={{
            reason: "Extract paper claims",
            risk: "medium",
            operationCount: 2,
            evidenceCount: 6,
          }}
          onApprove={approve}
          onReject={reject}
          onRequestRevision={requestRevision}
        />
      </LanguageProvider>,
    );

    expect(screen.getByText("cs-ingest")).toBeInTheDocument();
    expect(screen.getByText("Extract paper claims")).toBeInTheDocument();
    expect(screen.getByText(/2.*操作/)).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("assistant-review-comment"), {
      target: { value: "补充缺失的证据定位。" },
    });
    fireEvent.click(screen.getByTestId("assistant-request-revision"));

    expect(requestRevision).toHaveBeenCalledWith("补充缺失的证据定位。");
    fireEvent.click(screen.getByRole("button", { name: "审核通过" }));
    fireEvent.click(screen.getByRole("button", { name: "拒绝" }));
    expect(approve).toHaveBeenCalledOnce();
    expect(reject).toHaveBeenCalledOnce();
  });
});
