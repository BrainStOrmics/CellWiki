import { useEffect, useState, type RefObject } from "react";
import { useI18n } from "../../i18n";
import type { ChatMessage } from "../../types";

const QUESTION_CHARS = 42;
const ANSWER_CHARS = 64;
/** 视口顶部往下留一点余量：贴顶那一轮才算"正在看"。 */
const CURRENT_OFFSET_PX = 24;
/**
 * 刻度长度只由"离当前轮多远"决定：当前那枚最长、紧邻两枚次之，其余等长——
 * 像一排均匀短横上顶着一枚更长的表位（对齐参考稿的比例）。
 */
const DASH_BASE_PX = 16;
const DASH_NEAR_PX = 22;
const DASH_CURRENT_PX = 30;

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

/** 一枚刻度的长度：distance = 离当前轮隔了几轮（null = 没有当前轮）。 */
export function dashWidth(distance: number | null): number {
  if (distance === null) return DASH_BASE_PX;
  if (distance === 0) return DASH_CURRENT_PX;
  if (distance === 1) return DASH_NEAR_PX;
  if (distance === 2) return 19;
  return DASH_BASE_PX;
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
  const [activePosition, setActivePosition] = useState<number | null>(null);

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
      const current = currentTurnIndex(anchors);
      setActiveIndex(current);
      setActivePosition(current === null ? null : turns.findIndex((item) => item.index === current));
    };
    update();
    scroller.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      scroller.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, [scrollRef, messages, turns]);

  if (turns.length === 0) return null;

  return (
    <nav className="chat-timeline" aria-label={t("chat.timeline")}>
      {turns.map((turn, position) => {
        const distance = activePosition === null ? null : Math.abs(position - activePosition);
        const isCurrent = turn.index === activeIndex;
        return (
        <button
          key={turn.index}
          type="button"
          className={isCurrent ? "chat-timeline-tick is-current" : "chat-timeline-tick"}
          aria-label={`${t("chat.timelineJump")}: ${snippet(turn.question, QUESTION_CHARS)}`}
          aria-current={isCurrent ? "true" : undefined}
          onClick={() => onJump(turn.index)}
        >
          <span className="chat-timeline-dash" aria-hidden style={{ width: dashWidth(distance) }} />
          <span className="chat-timeline-preview" aria-hidden>
            <b>{snippet(turn.question, QUESTION_CHARS)}</b>
            {turn.answer && <small>{snippet(turn.answer, ANSWER_CHARS)}</small>}
          </span>
        </button>
        );
      })}
    </nav>
  );
}
