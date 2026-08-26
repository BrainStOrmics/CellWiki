import { useEffect, useState } from "react";
import { getJson, postJson } from "../../lib/product-api";

export interface PendingQuestion {
  question_id: string;
  run_id: string;
  thread_id: string;
  tool_call_id: string | null;
  question: string;
  options: string[];
  required: boolean;
  status: string;
  answers: string[] | null;
  created_at: string;
  answered_at: string | null;
}

function statusOf(error: unknown): number {
  if (error && typeof error === "object" && "status" in error) {
    return Number((error as { status: unknown }).status);
  }
  return 0;
}

export function QuestionCard({
  runId,
  onAnswered,
}: {
  runId: string;
  onAnswered?: (runId: string) => void;
}) {
  const [question, setQuestion] = useState<PendingQuestion | null>(null);
  const [freeText, setFreeText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    async function poll() {
      try {
        const q = await getJson<PendingQuestion>(`/api/agent/runs/${runId}/question`);
        if (!cancelled) {
          setQuestion(q);
          setError(null);
        }
      } catch (err) {
        // 404/409/422 表示没有挂起问题，停止轮询避免后台请求风暴
        const status = statusOf(err);
        if (status === 404 || status === 409 || status === 422) {
          if (!cancelled) setQuestion(null);
          return;
        }
        void err; // 网络抖动时继续轮询
      }
      if (!cancelled) timer = window.setTimeout(poll, 1500);
    }
    void poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [runId]);

  if (!question) return null;

  async function submit(answer: string | string[] | null, timedOut = false) {
    setSubmitting(true);
    setError(null);
    try {
      await postJson(`/api/agent/runs/${runId}/question`,
        timedOut ? { timed_out: true } : { answers: answer });
      setQuestion(null);
      setFreeText("");
      onAnswered?.(runId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  function submitFreeText() {
    const text = freeText.trim();
    if (text) void submit(text);
  }

  return (
    <div className="question-card" role="region" data-testid="question-card">
      <div className="question-card-title">需要你确认</div>
      <div className="question-card-text">{question.question}</div>
      {question.options.length > 0 && (
        <div className="question-card-options">
          {question.options.map((option) => (
            <button
              key={option}
              type="button"
              className="question-card-option"
              disabled={submitting}
              onClick={() => void submit(option)}
            >
              {option}
            </button>
          ))}
        </div>
      )}
      <div className="question-card-free">
        <input
          data-testid="question-free-text"
          type="text"
          value={freeText}
          disabled={submitting}
          placeholder="输入自定义回答（可留空）"
          onChange={(event) => setFreeText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") submitFreeText();
          }}
        />
        <button
          type="button"
          className="question-card-submit"
          disabled={submitting || freeText.trim().length === 0}
          onClick={submitFreeText}
        >
          提交
        </button>
        <button
          type="button"
          className="question-card-timeout"
          disabled={submitting}
          onClick={() => void submit(null, true)}
        >
          超时跳过
        </button>
      </div>
      {error && <div className="question-card-error">{error}</div>}
    </div>
  );
}
