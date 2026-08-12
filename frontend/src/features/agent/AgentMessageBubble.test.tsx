import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AgentMessageBubble } from "./AgentMessageBubble";
import type { ChatMessage } from "../../types";

const labels = {
  agentLabel: "CewiPilot",
  userLabel: "You",
  missingEvidenceLabel: "Missing evidence",
  processTitle: "Process",
  processLiveLabel: "Running",
  processCompletedLabel: "Completed",
  processFailedLabel: "Failed",
  processCancelledLabel: "Cancelled",
  processEmptyLabel: "No steps",
  diagnosticsLabel: "Run details",
};

describe("AgentMessageBubble", () => {
  it("renders attachment citations without opening an undefined Wiki page", () => {
    const openCitation = vi.fn();
    const message: ChatMessage = {
      role: "agent",
      text: "The attachment mentions FOXP3.",
      citations: [
        {
          type: "thread_attachment",
          attachment_id: "att_abc123",
          section_locator: "Page 1 · Markers",
          locator: "Page 1 · Markers",
        },
      ],
    };

    render(<AgentMessageBubble {...labels} message={message} onCitationOpen={openCitation} />);

    expect(screen.queryByRole("button", { name: /undefined/i })).not.toBeInTheDocument();
    expect(screen.getByText("att_abc123")).toBeInTheDocument();
    expect(screen.getByText("Page 1 · Markers")).toBeInTheDocument();
  });
  it("renders sent user attachments above the user message", () => {
    render(
      <AgentMessageBubble
        {...labels}
        message={{
          role: "user",
          text: "Summarize the attachment.",
          attachments: [{
            attachment_id: "att_" + "a".repeat(32),
            original_name: "paper.pdf",
            media_type: "application/pdf",
          }],
        }}
        onCitationOpen={vi.fn()}
      />,
    );

    expect(screen.getByText("paper.pdf")).toBeInTheDocument();
    expect(screen.getByText("Summarize the attachment.")).toBeInTheDocument();
  });
});
