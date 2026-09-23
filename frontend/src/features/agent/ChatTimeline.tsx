import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent, type RefObject } from "react";
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
 * 视口顶部落在某条消息上时它属于哪一轮：起点不晚于它的最后一个刻度。
 *
 * ``currentTurnIndex`` 给的是**任意**消息的下标——视口顶部通常正落在某条回答中间，
 * 直接拿它去刻度里找会找不到（返回 -1），镜头就从第 0 枚的左边开始衰减，表现为
 * "第一条特别长"（实测 2026-09-23：切到长会话时 20 枚刻度宽度是 22/19/16…、
 * 且没有任何一枚是 current）。
 */
export function activeTurnPosition(turns: ChatTurn[], activeIndex: number | null): number | null {
  if (activeIndex === null) return null;
  for (let position = turns.length - 1; position >= 0; position -= 1) {
    if (turns[position].index <= activeIndex) return position;
  }
  return null;
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
  const [hoveredPosition, setHoveredPosition] = useState<number | null>(null);
  const navRef = useRef<HTMLElement | null>(null);

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
      setActivePosition(activeTurnPosition(turns, current));
    };
    update();
    scroller.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      scroller.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, [scrollRef, messages, turns]);

  // 悬停 = 预演"正在看的那一轮"：镜头跟着指针最近的那枚刻度走，刻度长度随它变，
  // 宽度过渡由 CSS 补间，滑过整条轨时就是连续的变长/回落。
  function handlePointerMove(event: ReactMouseEvent<HTMLElement>) {
    const nav = navRef.current;
    if (!nav) return;
    let nearest: number | null = null;
    let nearestDistance = Number.POSITIVE_INFINITY;
    [...nav.querySelectorAll<HTMLElement>(".chat-timeline-tick")].forEach((tick, position) => {
      const rect = tick.getBoundingClientRect();
      const distance = Math.abs(rect.top + rect.height / 2 - event.clientY);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearest = position;
      }
    });
    setHoveredPosition(nearest);
  }

  if (turns.length === 0) return null;
  const focusPosition = hoveredPosition ?? activePosition;
  const focusing = hoveredPosition !== null;

  return (
    <nav
      className="chat-timeline"
      aria-label={t("chat.timeline")}
      ref={navRef}
      onMouseMove={handlePointerMove}
      onMouseLeave={() => setHoveredPosition(null)}
    >
      {turns.map((turn, position) => {
        const distance = focusPosition === null ? null : Math.abs(position - focusPosition);
        const isCurrent = activePosition !== null && position === activePosition;
        const isHovered = focusing && position === hoveredPosition;
        return (
        <button
          key={turn.index}
          type="button"
          className={[
            "chat-timeline-tick",
            isCurrent ? "is-current" : "",
            isHovered ? "is-hovered" : "",
          ].filter(Boolean).join(" ")}
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
