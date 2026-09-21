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
    options: [
      { label: "写入", description: "走审批单元写入", recommended: true },
      { label: "仅回答" },
      { label: "放弃" },
    ],
    required: true,
    status: "pending",
    answers: null,
    created_at: "2026-08-23T00:00:00Z",
    answered_at: null,
    ...overrides,
  };
}

async function renderCard(overrides: Partial<PendingQuestion> = {}) {
  mockedGet.mockResolvedValue(question(overrides));
  render(<QuestionCard runId="run_1" />);
  return screen.findByRole("region");
}

describe("QuestionCard", () => {
  it("renders the pending question as numbered options with free text (+1)", async () => {
    await renderCard();

    expect(screen.getByText("确认任务")).toBeInTheDocument();
    expect(screen.getByText("是否将结果写入 wiki？")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /写入/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /仅回答/ })).toBeInTheDocument();
    expect(screen.getByText("走审批单元写入")).toBeInTheDocument();
    expect(screen.getByText("推荐")).toBeInTheDocument();
    expect(screen.getByTestId("question-free-text")).toBeInTheDocument();
    expect(mockedGet).toHaveBeenCalledWith("/api/agent/runs/run_1/question");
  });

  it("keeps 提交 disabled until an option is picked or text is typed", async () => {
    await renderCard();

    const submit = screen.getByRole("button", { name: "提交" });
    expect(submit).toBeDisabled();

    fireEvent.click(screen.getByRole("radio", { name: /仅回答/ }));
    expect(submit).toBeEnabled();
  });

  it("submits the picked option's label and hides the card on success", async () => {
    mockedPost.mockResolvedValue({});
    await renderCard();

    fireEvent.click(screen.getByRole("radio", { name: /仅回答/ }));
    fireEvent.click(screen.getByRole("button", { name: "提交" }));

    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/agent/runs/run_1/question", {
        answers: "仅回答",
      }),
    );
    await waitFor(() =>
      expect(screen.queryAllByTestId("question-card")).toHaveLength(0),
    );
  });

  it("lets free text replace the picked option and answer with it", async () => {
    mockedPost.mockResolvedValue({});
    await renderCard();

    fireEvent.click(screen.getByRole("radio", { name: /写入/ }));
    fireEvent.change(screen.getByTestId("question-free-text"), {
      target: { value: "写入，但只改标题" },
    });
    // 两者回答同一件事：输入自由文本即取消选中。
    expect(screen.getByRole("radio", { name: /写入/ })).toHaveAttribute(
      "aria-checked",
      "false",
    );

    fireEvent.click(screen.getByRole("button", { name: "提交" }));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/agent/runs/run_1/question", {
        answers: "写入，但只改标题",
      }),
    );
  });

  it("answers with free text on Enter", async () => {
    mockedPost.mockResolvedValue({});
    await renderCard();

    const input = screen.getByTestId("question-free-text");
    fireEvent.change(input, { target: { value: "自定义答案" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/agent/runs/run_1/question", {
        answers: "自定义答案",
      }),
    );
  });

  it("answers a free-text-only question (no fixed options)", async () => {
    mockedPost.mockResolvedValue({});
    await renderCard({ options: [] });

    expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
    const submit = screen.getByRole("button", { name: "提交" });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByTestId("question-free-text"), {
      target: { value: "先看 X 再看 Y" },
    });
    fireEvent.click(submit);
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/agent/runs/run_1/question", {
        answers: "先看 X 再看 Y",
      }),
    );
  });

  it("skips the question with the footer key or the header close", async () => {
    mockedPost.mockResolvedValue({});
    await renderCard();

    fireEvent.click(screen.getByRole("button", { name: "跳过本题" }));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/agent/runs/run_1/question", {
        timed_out: true,
      }),
    );

    mockedPost.mockClear();
    await renderCard();
    fireEvent.click(screen.getByRole("button", { name: "跳过本题（不回答）" }));
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/api/agent/runs/run_1/question", {
        timed_out: true,
      }),
    );
  });

  it("collapses and expands the card body", async () => {
    await renderCard();

    fireEvent.click(screen.getByRole("button", { name: "收起" }));
    expect(screen.queryByText("是否将结果写入 wiki？")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "提交" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "展开" }));
    expect(screen.getByText("是否将结果写入 wiki？")).toBeInTheDocument();
  });

  it("notifies the caller after an answer is submitted", async () => {
    mockedPost.mockResolvedValue({});
    const onAnswered = vi.fn();
    mockedGet.mockResolvedValue(question());
    render(<QuestionCard runId="run_1" onAnswered={onAnswered} />);
    await screen.findByRole("region");

    fireEvent.click(screen.getByRole("radio", { name: /仅回答/ }));
    fireEvent.click(screen.getByRole("button", { name: "提交" }));
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
      expect(screen.getByRole("radio", { name: /写入/ })).toBeInTheDocument();
      expect(mockedGet.mock.calls.length).toBeGreaterThanOrEqual(2);
    } finally {
      vi.useRealTimers();
    }
  });
});
