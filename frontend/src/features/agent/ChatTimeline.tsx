import { useI18n } from "../../i18n";
import type { ChatMessage } from "../../types";

const QUESTION_CHARS = 42;
const ANSWER_CHARS = 64;

export type ChatTurn = {
  /** 该轮用户消息在消息数组里的下标——跳转锚点就是它。 */
  index: number;
  question: string;
  answer: string;
};

/** 一行、截断：预览里不放换行，读起来才是"标题 + 摘要"。 */
function snippet(text: string, limit: number): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > limit ? `${flat.slice(0, limit)}…` : flat;
}

/** 一轮 = 一条用户消息 + 它之后的第一条 Agent 回答。 */
export function chatTurns(messages: ChatMessage[]): ChatTurn[] {
  const turns: ChatTurn[] = [];
  messages.forEach((message, index) => {
    if (message.role !== "user") return;
    const answer = messages.slice(index + 1).find((next) => next.role === "agent");
    turns.push({ index, question: message.text, answer: answer?.text ?? "" });
  });
  return turns;
}

/**
 * 转录左侧的时间线：一轮一枚刻度，悬停（或键盘聚焦）预览"用户消息前几十字 +
 * 该轮回答开头"，点击跳回那一轮。刻度只按顺序均匀铺开、不按滚动比例，所以不需要
 * 量任何布局；跳转靠消息上的 data-chat-index 锚点。
 */
export function ChatTimeline({
  messages,
  onJump,
}: {
  messages: ChatMessage[];
  onJump: (index: number) => void;
}) {
  const { t } = useI18n();
  const turns = chatTurns(messages);
  if (turns.length === 0) return null;

  return (
    <nav className="chat-timeline" aria-label={t("chat.timeline")}>
      {turns.map((turn) => (
        <button
          key={turn.index}
          type="button"
          className="chat-timeline-tick"
          aria-label={`${t("chat.timelineJump")}: ${snippet(turn.question, QUESTION_CHARS)}`}
          onClick={() => onJump(turn.index)}
        >
          <span className="chat-timeline-dash" aria-hidden />
          <span className="chat-timeline-preview" aria-hidden>
            <b>{snippet(turn.question, QUESTION_CHARS)}</b>
            {turn.answer && <small>{snippet(turn.answer, ANSWER_CHARS)}</small>}
          </span>
        </button>
      ))}
    </nav>
  );
}
