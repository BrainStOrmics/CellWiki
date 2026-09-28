v1

## User Profile

在这个知识库工作区里，用户按证据与逐行审批推进：改动必须可回溯到 `raw/<paper_id>/` 或页面，未证实的结论要显式标为推断。用户要求先给结论再给依据，不接受"看起来对"的解释；验证失败时要如实说哪一步没通过，而不是复述意图。环境是 Windows 桌面端，命令与路径按 PowerShell 习惯给出，不假设 Unix 工具可用。

## User Preferences

- 评审时逐行判定 diff，不要整段接受或整段拒绝。
- 生成页面时保留 Evidence 与 Source 列，不要在页面里写工具指令注释。
- 报告结果时区分"本地提交"与"已推送"，未推送要明确说明。
- 遇到门禁失败先读门禁明细再改，不要先重跑。
- 用户明确说"记住/更正"时按原话记录，不改写措辞。

## General Tips

- `schema.md` 是页面提取契约的唯一来源；模板里的指令注释必须在发布前删除。
- lint 门禁只检查本次 run 改动过的页面，旧页面在被修改前不参与模板检查。
- 工具输出超过阈值会被预览化并落 `data/runtime/tool-results/`，需要原文时读侧车文件。
- 上下文压缩由图内中间件在模型调用前判断，压缩后只保留尾部窗口。
- 跨 run 缓存命中低时先看诊断里的共同前缀长度，再怀疑 provider 侧保留策略。

## What's in Memory

### wiki 内容维护

#### 2026-09-28

- Evidence Tier 与模板门禁: schema.md, cellwiki-template, Evidence Tier, source_field, L0 门禁
  - desc: 页面提取与 lint 的契约细节；需要改模板或排查门禁失败时先搜这里。
  - learnings: Tier 1–4 必须有 `raw/<paper_id>/` 绑定；Tier 5 必须以 inference 或 hypothesis 开头。

### raw 与来源

#### 2026-09-28

- 附件提升与来源登记: promote_attachment, raw/<source_id>, meta.json, needs_extraction
  - desc: 附件如何经用户确认提升为正式源；涉及 source_id 命名与提取文本时先搜这里。
  - learnings: promote 前必须经 ask_user_question 确认；无提取文本的 PDF 标为 needs_extraction。

### prompt 与上下文

#### 2026-09-28

- 稳定前缀与 Turn Context: cache_prefix_hash, Turn Context, run_context, prompt_cache_breakpoint
  - desc: prompt 分层的注入位置与缓存边界；改动工具面或注入内容时先搜这里。
  - learnings: 工具面变化会改稳定前缀指纹；动态内容只能进 Turn Context。

### run 与审批

#### 2026-09-28

- 审批单元与串行门禁: pending diff, diff_<run_id>_<n>, snapshot_commit, 代判
  - desc: 一次 run 如何产出多个审批单元、拒绝如何 revert；涉及审批语义时先搜这里。
  - learnings: 审批单元边界是"判定"而非"发布"；未判定单元会阻塞新 run。

### 评估与测试

#### 2026-09-28

- 记忆配对与安全测试: evals/agent_v2, --memory off/on, 隔离, 注入抵抗
  - desc: 记忆功能的有/无对照运行方式与必须通过的安全项。
  - learnings: 配对运行除 `--memory` 与 `--memory-seed` 外的参数必须完全相同。

### 工作区与环境

#### 2026-09-28

- 工作区初始化与运行时边界: .gitignore, data/runtime, checkpoints.sqlite, PROJECT_ROOT
  - desc: 工作区目录结构与运行时产物的版本控制边界。
  - learnings: `data/runtime/` 不进 git、不参与待确认 diff，随工作区删除一起清除。

### Older Memory Topics

#### 工作区与环境

- 桌面运行拓扑: Product API, Tauri sidecar, 随机端口, bearer token
  - desc: 开发态与发布态的进程编排；排查 sidecar 启动或鉴权问题时使用。