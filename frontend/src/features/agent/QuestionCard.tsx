import { useEffect, useState } from "react";
import { ChevronDown, Pencil, X } from "lucide-react";
import { getJson, postJson } from "../../lib/product-api";

export interface QuestionOption {
  label: string;
  description?: string;
  recommended?: boolean;
}

export interface PendingQuestion {
  question_id: string;
  run_id: string;
  thread_id: string;
  tool_call_id: string | null;
  question: string;
  options: QuestionOption[];
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

/**
 * 挂起问题的回答卡片（5+1：最多 5 个固定选项 + 自由文本）。选项先选中、再按
 * 提交；回车与提交同义。跳过（标题栏 X 或底部键）走 timed_out，把 run 停在
 * 可继续的中断态——不是"不回答也继续"。
 */
export function QuestionCard({
  runId,
  onAnswered,
}: {
  runId: string;
  onAnswered?: (runId: string) => void;
}) {
  const [question, setQuestion] = useState<PendingQuestion | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [freeText, setFreeText] = useState("");
  const [collapsed, setCollapsed] = useState(false);
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
        // 404/409/422 = 该 run 当前没有待答问题（还没问到，或已经答完）。
        // 这里必须继续轮询：卡片会在 ask_user_question 持久化问题之前就先挂载一次。
        const status = statusOf(err);
        if (status === 404 || status === 409 || status === 422) {
          if (!cancelled) setQuestion(null);
        }
        void err; // 其它错误（网络抖动）同样继续轮询
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
      setSelected(null);
      setFreeText("");
      onAnswered?.(runId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  function submitSelection() {
    if (selected !== null) {
      const option = question?.options[selected];
      if (option) void submit(option.label);
      return;
    }
    const text = freeText.trim();
    if (text) void submit(text);
  }

  const answerable = selected !== null || freeText.trim().length > 0;

  return (
    <div className="question-card" role="region" data-testid="question-card">
      <div className="question-card-head">
        <span className="question-card-title">确认任务</span>
        <span className="question-card-head-actions">
          <button
            type="button"
            className="question-card-icon"
            aria-expanded={!collapsed}
            aria-label={collapsed ? "展开" : "收起"}
            onClick={() => setCollapsed((value) => !value)}
          >
            <ChevronDown size={16} />
          </button>
          <button
            type="button"
            className="question-card-icon"
            aria-label="跳过本题（不回答）"
            title="跳过本题：不回答，把 run 停在可继续的中断态"
            disabled={submitting}
            onClick={() => void submit(null, true)}
          >
            <X size={16} />
          </button>
        </span>
      </div>
      {!collapsed && (
        <>
          <div className="question-card-text">{question.question}</div>
          {question.options.length > 0 && (
            <div className="question-card-options" role="radiogroup" aria-label="固定选项">
              {question.options.map((option, index) => (
                <button
                  key={option.label}
                  type="button"
                  role="radio"
                  aria-checked={selected === index}
                  className={`question-card-option${selected === index ? " is-selected" : ""}`}
                  disabled={submitting}
                  onClick={() => {
                    setSelected(index);
                    setFreeText("");
                  }}
                >
                  <span className="question-card-option-index">{index + 1}</span>
                  <span className="question-card-option-body">
                    <span className="question-card-option-label">{option.label}</span>
                    {option.recommended && (
                      <span className="question-card-option-tag">推荐</span>
                    )}
                    {option.description && (
                      <span className="question-card-option-desc">{option.description}</span>
                    )}
                  </span>
                </button>
              ))}
            </div>
          )}
          <label className="question-card-free">
            <Pencil size={14} aria-hidden />
            <input
              data-testid="question-free-text"
              type="text"
              value={freeText}
              disabled={submitting}
              placeholder="输入你的答案"
              onChange={(event) => {
                setFreeText(event.target.value);
                setSelected(null);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") submitSelection();
              }}
            />
          </label>
          <div className="question-card-foot">
            <button
              type="button"
              className="question-card-skip"
              disabled={submitting}
              onClick={() => void submit(null, true)}
            >
              跳过本题
            </button>
            <button
              type="button"
              className="question-card-submit"
              disabled={submitting || !answerable}
              onClick={submitSelection}
            >
              提交
            </button>
          </div>
          {error && <div className="question-card-error">{error}</div>}
        </>
      )}
    </div>
  );
}
