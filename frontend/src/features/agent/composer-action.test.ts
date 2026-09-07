import { describe, expect, it } from "vitest";
import { composerActionFor, type ComposerState } from "./composer-action";

function state(overrides: Partial<ComposerState> = {}): ComposerState {
  return {
    agentBusy: false,
    waitingOnQuestion: false,
    resumableRunId: null,
    hasDraft: false,
    ...overrides,
  };
}

describe("composerActionFor", () => {
  it("空闲时是发送键，没有草稿就禁用", () => {
    expect(composerActionFor(state())).toEqual({ kind: "send", disabled: true });
    expect(composerActionFor(state({ hasDraft: true }))).toEqual({
      kind: "send",
      disabled: false,
    });
  });

  it("有请求在飞时是停止键，无论输入框里有没有字", () => {
    expect(composerActionFor(state({ agentBusy: true }))).toEqual({ kind: "stop" });
    expect(composerActionFor(state({ agentBusy: true, hasDraft: true }))).toEqual({
      kind: "stop",
    });
  });

  it("提问态是停止键：那时取消是唯一合法出口，composer 已让位给问题卡", () => {
    expect(composerActionFor(state({ waitingOnQuestion: true }))).toEqual({ kind: "stop" });
    expect(
      composerActionFor(state({ waitingOnQuestion: true, hasDraft: true })),
    ).toEqual({ kind: "stop" });
  });

  it("中断且输入框空着时是继续键", () => {
    expect(composerActionFor(state({ resumableRunId: "run_paused" }))).toEqual({
      kind: "resume",
    });
  });

  it("中断但用户打了字时让位给发送键", () => {
    // 这一条是顺序的核心：用户打了字，他要的是发这条新消息而不是续跑旧的。
    // 串行门禁仍被那个中断 run 占着，所以 sendMessage 必须先放弃它再发。
    expect(
      composerActionFor(state({ resumableRunId: "run_paused", hasDraft: true })),
    ).toEqual({ kind: "send", disabled: false });
  });

  it("续跑请求在飞的瞬间是停止键，不是继续键", () => {
    expect(
      composerActionFor(state({ resumableRunId: "run_paused", agentBusy: true })),
    ).toEqual({ kind: "stop" });
  });

  it("提问态压过中断态：两者同时为真时仍是停止键", () => {
    expect(
      composerActionFor(
        state({ resumableRunId: "run_paused", waitingOnQuestion: true }),
      ),
    ).toEqual({ kind: "stop" });
  });
});
