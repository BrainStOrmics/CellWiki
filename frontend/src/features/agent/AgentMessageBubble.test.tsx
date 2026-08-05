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
});
