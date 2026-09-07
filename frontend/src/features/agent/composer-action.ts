/** composer 那一颗按钮当前该做什么。发送、停止、继续共用同一个槽位。 */
export type ComposerAction =
  | { kind: "send"; disabled: boolean }
  | { kind: "stop" }
  | { kind: "resume" };

export interface ComposerState {
  /** 有一次请求在飞——发送、续跑、重试的 POST 期间同样算。 */
  agentBusy: boolean;
  /** run 停在提问态，composer 已经把位置让给问题卡。 */
  waitingOnQuestion: boolean;
  /** 可续跑的中断 run；空表示没有。 */
  resumableRunId: string | null;
  /** 输入框里有非空白内容。 */
  hasDraft: boolean;
}

/**
 * 判定顺序即优先级，不可换。
 *
 * 提问态排最前：那时取消是唯一合法出口（`cancel()` 接受 WAITING_CONFIRMATION），
 * 而 composer 已经让位给问题卡，既不该发送也不该继续。
 *
 * 「继续」只在输入框空着时占位。一旦用户打了字，他要的是发这条新消息而不是续跑旧的
 * ——但串行门禁仍被那个中断 run 占着，所以 `sendMessage` 必须先放弃它再发。
 *
 * 「继续」排在 `agentBusy` 之后：续跑请求在飞的瞬间按钮该是停止，不是继续。
 */
export function composerActionFor(state: ComposerState): ComposerAction {
  if (state.waitingOnQuestion) return { kind: "stop" };
  if (state.agentBusy) return { kind: "stop" };
  if (state.resumableRunId && !state.hasDraft) return { kind: "resume" };
  return { kind: "send", disabled: !state.hasDraft };
}
