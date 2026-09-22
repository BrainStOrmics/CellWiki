import { useEffect, useState, type RefObject } from "react";
import { useI18n } from "../../i18n";
import type { ChatMessage } from "../../types";

const QUESTION_CHARS = 42;
const ANSWER_CHARS = 64;
/** 视口顶部往下留一点余量：贴顶那一轮才算"正在看"。 */
const CURRENT_OFFSET_PX = 24;
/** 刻度长度跟着该轮的问答字数走：短到 12px、长到 28px，400 字以上封顶。 */
const DASH_MIN_PX = 12;
const DASH_MAX_PX = 28;
const DASH_FULL_CHARS = 400;

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

/** 一枚刻度的长度：按该轮"问答字数"线性映射，够长的那轮一眼看得出来。 */
export function dashWidth(turn: ChatTurn): number {
  const chars = turn.question.length + turn.answer.length;
  const ratio = Math.min(1, chars / DASH_FULL_CHARS);
  return Math.round(DASH_MIN_PX + ratio * (DASH_MAX_PX - DASH_MIN_PX));
}

/**
 * "正在看的那一轮" = 视口顶部之前最近的一条锚点。纯函数，方便单测：
 * 入参是各轮锚点相对视口顶部的位置（负数 = 已经滚过去了）。
 */
export function currentTurnIndex(
  anchors: Array<{ index: number; top: number }>,
  offset = CURRENT_OFFSET_PX,
): number | null {
  let current: number | null = null;
  for (const anchor of anchors) {
    if (anchor.top <= offset) current = anchor.index;
  }
  return current;
}

/**
 * 转录左侧的时间线：一轮一枚等宽短横，**正在看的那一轮加长变深**（随滚动移动）；
 * 悬停或键盘聚焦显示预览（用户消息前几十字 + 该轮回答开头），点击跳回那一轮。
 * 刻度只按顺序均匀铺开、不按滚动比例，所以不需要量任何布局。
 */
export function ChatTimeline({
  messages,
  onJump,
  scrollRef,
}: {
  messages: ChatMessage[];
  onJump: (index: number) => void;
  /** 转录滚动容器：用它算"正在看的那一轮"（滚动时只重渲染这条轨）。 */
  scrollRef?: RefObject<HTMLDivElement | null>;
}) {
  const { t } = useI18n();
  const turns = chatTurns(messages);
  const [activeIndex, setActiveIndex] = useState<number | null>(null);

  useEffect(() => {
    const scroller = scrollRef?.current;
    if (!scroller) return;
    const update = () => {
      const origin = scroller.getBoundingClientRect().top;
      const anchors = [...scroller.querySelectorAll<HTMLElement>("[data-chat-index]")].flatMap(
        (node) => {
          const index = Number(node.dataset.chatIndex);
          return Number.isFinite(index)
            ? [{ index, top: node.getBoundingClientRect().top - origin }]
            : [];
        },
      );
      setActiveIndex(currentTurnIndex(anchors));
    };
    update();
    scroller.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      scroller.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, [scrollRef, messages]);

  if (turns.length === 0) return null;

  return (
    <nav className="chat-timeline" aria-label={t("chat.timeline")}>
      {turns.map((turn) => (
        <button
          key={turn.index}
          type="button"
          className={
            turn.index === activeIndex ? "chat-timeline-tick is-current" : "chat-timeline-tick"
          }
          aria-label={`${t("chat.timelineJump")}: ${snippet(turn.question, QUESTION_CHARS)}`}
          aria-current={turn.index === activeIndex ? "true" : undefined}
          onClick={() => onJump(turn.index)}
        >
          <span className="chat-timeline-dash" aria-hidden style={{ width: dashWidth(turn) }} />
          <span className="chat-timeline-preview" aria-hidden>
            <b>{snippet(turn.question, QUESTION_CHARS)}</b>
            {turn.answer && <small>{snippet(turn.answer, ANSWER_CHARS)}</small>}
          </span>
        </button>
      ))}
    </nav>
  );
}
