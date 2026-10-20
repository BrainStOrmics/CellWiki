import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getJson } from "../../lib/product-api";
import { useUiStore } from "../../stores/ui-store";
import { useI18n, type MessageKey } from "../../i18n";
import { formatTokens } from "./AgentRunDiagnostics";
import type {
  AgentContextUsage,
  AppSettings,
  ModelProviderCatalog,
  ModelSelection,
} from "../../types";

// ---------------------------------------------------------------------------
// Composer 里的上下文容量键：一枚细环显示"已用/上限"，悬停展开构成明细。
// 位置在模型选择左边——上限取决于**当前选中的模型**（min(设置里的上限, 模型输入窗口)），
// 挨着模型键放，改模型与改上限的影响一眼能对上。
// ---------------------------------------------------------------------------

const RING_RADIUS = 6;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

const SECTION_KEYS = ["messages", "injection", "tools", "system_prompt"] as const;
type SectionKey = (typeof SECTION_KEYS)[number] | "answer" | "other";

const SECTION_LABEL_KEYS: Record<SectionKey, MessageKey> = {
  messages: "context.messages",
  injection: "context.injection",
  tools: "context.tools",
  system_prompt: "context.systemPrompt",
  answer: "context.lastAnswer",
  other: "context.other",
};

/** 占比统一一位小数、整数不留小数点（参考稿的 73% 与 21.8% 就是这种混排）。 */
export function formatShare(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "0%";
  const percent = Math.round(value * 1000) / 10;
  return `${Number.isInteger(percent) ? percent : percent.toFixed(1)}%`;
}

/** 上下限取小：设置里的上限与模型声明的输入窗口，谁小听谁的。 */
export function effectiveContextCap(
  settingsCap: number | undefined,
  modelInputTokens: number | null | undefined,
): number | null {
  const candidates = [settingsCap, modelInputTokens].filter(
    (value): value is number => typeof value === "number" && value > 0,
  );
  return candidates.length > 0 ? Math.min(...candidates) : null;
}

function modelInputTokensFor(
  catalog: ModelProviderCatalog | undefined,
  selection: ModelSelection | null,
): number | null {
  if (!catalog || !selection) return null;
  const provider = catalog.providers.find((item) => item.id === selection.provider_id);
  const model = provider?.models.find((item) => item.id === selection.model_id);
  return model?.max_input_tokens ?? null;
}

export function ContextUsage({ threadId }: { threadId: string | null }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const selectedModel = useUiStore((state) => state.selectedModel);

  const usage = useQuery({
    queryKey: ["agent-context-usage", threadId],
    queryFn: () =>
      getJson<AgentContextUsage>(
        `/api/agent/threads/${encodeURIComponent(String(threadId))}/context-usage`,
      ),
    enabled: Boolean(threadId),
  });
  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: () => getJson<AppSettings>("/api/settings"),
    staleTime: 30_000,
  });
  // 与模型切换器共用同一份目录缓存，不额外发请求。
  const catalog = useQuery({
    queryKey: ["model-providers"],
    queryFn: () => getJson<ModelProviderCatalog>("/api/model-providers"),
    placeholderData: (previous) => previous,
  });

  const data = usage.data;
  const cap =
    data?.effective_context_limit ??
    effectiveContextCap(
      settings.data?.agent_context_max_tokens,
      modelInputTokensFor(
        catalog.data,
        selectedModel ?? catalog.data?.default_selection ?? null,
      ),
    );
  const used = data?.used_tokens ?? 0;
  const answer = data?.last_output_tokens ?? 0;
  const estimated = data?.estimated_tokens ?? 0;
  // 分母取"实测总量"与"估算 prompt + 实测输出"的较大者：有实测时两者相等，没实测时
  // 用估算兜底。分节是 prompt 侧估算，上轮回答与"其他"各自单列，加起来才是占用总量。
  const denominator = Math.max(used, estimated + answer, 1);
  const other = Math.max(0, denominator - estimated - answer);
  const share = cap !== null ? Math.min(1, used / cap) : 0;
  const rows = [
    ...SECTION_KEYS.map((key) => ({ key: key as SectionKey, value: data?.sections[key] ?? 0 })),
    ...(answer > 0 ? [{ key: "answer" as SectionKey, value: answer }] : []),
    ...(other > 0 ? [{ key: "other" as SectionKey, value: other }] : []),
  ];

  return (
    <div
      className="context-usage"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        className="context-usage-button"
        aria-label={t("context.title")}
        title={t("context.buttonHint")}
        aria-expanded={open}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
      >
        <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
          <circle cx="8" cy="8" r={RING_RADIUS} fill="none" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2" />
          <circle
            cx="8"
            cy="8"
            r={RING_RADIUS}
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeDasharray={`${share * RING_CIRCUMFERENCE} ${RING_CIRCUMFERENCE}`}
            transform="rotate(-90 8 8)"
          />
        </svg>
      </button>
      {open && (
        <div className="context-usage-popover" role="tooltip">
          <div className="context-usage-head">
            <span>{t("context.title")}</span>
            <span className="context-usage-total">
              {formatTokens(used)}/{cap === null ? "—" : formatTokens(cap)}（{formatShare(share)}）
            </span>
          </div>
          <div className="context-usage-bar" aria-hidden>
            <i style={{ width: `${share * 100}%` }} />
          </div>
          <ul className="context-usage-rows">
            {rows.map((row) => (
              <li key={row.key}>
                <span className="context-usage-dot" aria-hidden />
                <span className="context-usage-label">{t(SECTION_LABEL_KEYS[row.key])}</span>
                <span className="context-usage-value">{formatShare(row.value / denominator)}</span>
              </li>
            ))}
          </ul>
          <div className="context-usage-foot">
            <span>{t("context.avgCacheHit")}</span>
            <span className="context-usage-value">
              {formatShare(data?.avg_cache_hit_rate ?? 0)}
            </span>
          </div>
          {data?.compaction_threshold ? (
            <div className="context-usage-foot">
              <span>{t("context.compactionThreshold")}</span>
              <span className="context-usage-value">
                {formatTokens(data.compaction_threshold)}
              </span>
            </div>
          ) : null}
          {data?.retained_tokens !== undefined ? (
            <div className="context-usage-foot">
              <span>{t("context.retainedTail")}</span>
              <span className="context-usage-value">
                {formatTokens(data.retained_tokens)}
              </span>
            </div>
          ) : null}
          {data?.input_window_source ? (
            <div className="context-usage-foot">
              <span>{t("context.windowSource")}</span>
              <span className="context-usage-value">{data.input_window_source}</span>
            </div>
          ) : null}
          {data?.input_window_source === "fallback" ? (
            <div className="context-usage-warning" role="status">
              {t("context.windowFallback").replace(
                "{tokens}",
                formatTokens(data.model_input_tokens),
              )}
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
