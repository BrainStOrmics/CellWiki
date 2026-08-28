import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QuestionCard } from "./QuestionCard";
import type { PendingQuestion } from "./QuestionCard";

vi.mock("../../lib/product-api", () => ({
  getJson: vi.fn(),
  postJson: vi.fn(),
}));

import { getJson, postJson } from "../../lib/product-api";

const mockedGet = vi.mocked(getJson);
const mockedPost = vi.mocked(postJson);

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function question(overrides: Partial<PendingQuestion> = {}): PendingQuestion {
  return {
    question_id: "q_1",
    run_id: "run_1",
    thread_id: "thread_1",
    tool_call_id: "call_1",
    question: "是否将结果写入 wiki？",
    options: ["写入", "仅回答", "放弃"],
    required: true,
    status: "pending",
    answers: null,
    created_at: "2026-08-23T00:00:00Z",
    answered_at: null,
    ...overrides,
  };
}

describe("QuestionCard", () => {
  it("renders the pending question with options and free text (+1)", async () => {
    mockedGet.mockResolvedValue(question());
    render(<QuestionCard runId="run_1" />);
    expect(await screen.findByText("是否将结果写入 wiki？")).toBeInTheDocument();
    expect(screen.getByText("写入")).toBeInTheDocument();
    expect(screen.getByText("仅回答")).toBeInTheDocument();
    expect(screen.getByTestId("question-free-text")).toBeInTheDocument();
    expect(mockedGet).toHaveBeenCalledWith("/api/agent/runs/run_1/question");
  });

  it("submits a fixed option and hides the card on success", async () => {
    mockedGet.mockResolvedValue(question());
    mockedPost.mockResolvedValue({});
    render(<QuestionCard runId="run_1" />);
    const optionButton = await screen.findByText("仅回答");
    fireEvent.click(optionButton);
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/agent/runs/run_1/question", {
        answers: "仅回答",
      }),
    );
    await waitFor(() =>
      expect(screen.queryAllByTestId("question-card")).toHaveLength(0),
    );
  });

  it("notifies the caller after an answer is submitted", async () => {
    mockedGet.mockResolvedValue(question());
    mockedPost.mockResolvedValue({});
    const onAnswered = vi.fn();
    render(<QuestionCard runId="run_1" onAnswered={onAnswered} />);
    const optionButton = await screen.findByText("仅回答");
    fireEvent.click(optionButton);
    await waitFor(() => expect(onAnswered).toHaveBeenCalledWith("run_1"));
  });

  it("keeps polling and reveals a question that arrives after an empty first poll", async () => {
    // 运行中挂起询问时，卡片会先于问题持久化挂载：第一次 404 之后必须继续轮询。
    vi.useFakeTimers();
    try {
      mockedGet
        .mockRejectedValueOnce(Object.assign(new Error("no open question"), { status: 404 }))
        .mockResolvedValue(question());
      render(<QuestionCard runId="run_1" />);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1_600);
      });
      expect(screen.getByText("是否将结果写入 wiki？")).toBeInTheDocument();
      expect(screen.getByText("写入")).toBeInTheDocument();
      expect(mockedGet.mock.calls.length).toBeGreaterThanOrEqual(2);
    } finally {
      vi.useRealTimers();
    }
  });
});
