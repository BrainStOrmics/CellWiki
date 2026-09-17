import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Box,
  CheckCircle2,
  ChevronRight,
  Eye,
  EyeOff,
  KeyRound,
  LoaderCircle,
  Plus,
  Save,
  Search,
  Star,
  TestTube2,
  Trash2,
  XCircle,
} from "lucide-react";
import { useI18n, type MessageKey } from "../i18n";
import { deleteJson, getJson, postJson, putJson } from "../lib/product-api";
import type {
  ModelProviderCatalog,
  ModelProviderInfo,
  ProviderTestResult,
  WireProtocol,
} from "../types";

// ---------------------------------------------------------------------------
// 供应商目录管理（设置 → 模型服务）。与全局保存按钮无关：每个供应商的
// 保存/测试/拉取/删除都是独立即时操作，保存后免重启对下一条 run 生效。
// key 只写不读：表单留空 = 保留已存密钥。
// ---------------------------------------------------------------------------

type ProviderDraft = {
  name: string;
  base_url: string;
  protocol: WireProtocol;
  enabled: boolean;
  models: {
    id: string;
    display_name?: string | null;
    enabled: boolean;
    max_input_tokens?: number | null;
  }[];
  api_key: string;
  clear_api_key: boolean;
  overrides_text: string;
};

type TemplateKey = "bailian" | "openrouter" | "deepseek" | "siliconflow" | "ollama" | "anthropic";

const TEMPLATES: {
  key: TemplateKey;
  nameKey: MessageKey;
  // 该供应商在各协议下的官方端点；未列出的协议不切换（避免猜错）。
  baseUrls: Partial<Record<WireProtocol, string>>;
  // 仅原生协议模板带 protocol：OpenAI 兼容模板沿用当前下拉值（既有行为）。
  protocol?: WireProtocol;
}[] = [
  { key: "bailian", nameKey: "settings.templateBailian", baseUrls: { chat_completions: "https://dashscope.aliyuncs.com/compatible-mode/v1" } },
  { key: "openrouter", nameKey: "settings.templateOpenRouter", baseUrls: { chat_completions: "https://openrouter.ai/api/v1" } },
  { key: "deepseek", nameKey: "settings.templateDeepSeek", baseUrls: { chat_completions: "https://api.deepseek.com/v1", anthropic: "https://api.deepseek.com/anthropic" } },
  { key: "siliconflow", nameKey: "settings.templateSiliconFlow", baseUrls: { chat_completions: "https://api.siliconflow.cn/v1" } },
  { key: "ollama", nameKey: "settings.templateOllama", baseUrls: { chat_completions: "http://127.0.0.1:11434/v1" } },
  { key: "anthropic", nameKey: "settings.templateAnthropic", baseUrls: { anthropic: "https://api.anthropic.com" }, protocol: "anthropic" },
];

function draftFromProvider(provider: ModelProviderInfo): ProviderDraft {
  return {
    name: provider.name,
    base_url: provider.base_url,
    protocol: provider.protocol,
    enabled: provider.enabled,
    models: provider.models.map((model) => ({ ...model })),
    api_key: "",
    clear_api_key: false,
    overrides_text: Object.keys(provider.request_overrides ?? {}).length
      ? JSON.stringify(provider.request_overrides, null, 2)
      : "",
  };
}

function emptyDraft(baseUrl = ""): ProviderDraft {
  return {
    name: "",
    base_url: baseUrl,
    protocol: "chat_completions",
    enabled: true,
    models: [],
    api_key: "",
    clear_api_key: false,
    overrides_text: "",
  };
}

export function ProviderManager({
  onNotice,
}: {
  onNotice: (notice: { kind: "ok" | "error"; text: string } | undefined) => void;
}) {
  const { t } = useI18n();
  const [catalog, setCatalog] = useState<ModelProviderCatalog>();
  // selectedId 为 null 且 creating=false 表示"未选中"；creating=true 表示新建草稿。
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState<ProviderDraft>(emptyDraft());
  // 快速填充所选模板：改协议时据此跟随切换 base_url（手改过 URL 则不覆盖）。
  const [appliedTemplate, setAppliedTemplate] = useState<TemplateKey | null>(null);
  const [showKey, setShowKey] = useState(false);
  const [openPanelIndex, setOpenPanelIndex] = useState<number | null>(null);
  const [panelQuery, setPanelQuery] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ProviderTestResult>();
  const [loading, setLoading] = useState(true);
  const queryClient = useQueryClient();

  const selected = useMemo(
    () => catalog?.providers.find((provider) => provider.id === selectedId),
    [catalog, selectedId],
  );
  const editorVisible = creating || selected !== undefined;

  // 可用清单只读缓存：顶部按钮或 › 面板触发拉取，拉取结果不自动并入模型目录。
  // 草稿（新建）还没有 provider id，走草稿端点（key 只随该次请求发往草稿
  // 自己的 base_url，不落盘）。
  const available = useQuery({
    queryKey: ["provider-available-models", creating ? "draft" : selectedId],
    queryFn: async () => {
      const payload = creating
        ? await postJson<{ models: string[] }>("/api/model-providers/fetch-models", {
            base_url: draft.base_url.trim(),
            protocol: draft.protocol,
            api_key: draft.api_key.trim() || null,
          })
        : await postJson<{ models: string[] }>(
            `/api/model-providers/${encodeURIComponent(selectedId ?? "")}/fetch-models`,
            {},
          );
      return payload.models;
    },
    enabled: false,
    retry: false,
    staleTime: Infinity,
  });
  const filteredAvailable = useMemo(() => {
    const models = available.data ?? [];
    const needle = panelQuery.trim().toLowerCase();
    return needle ? models.filter((id) => id.toLowerCase().includes(needle)) : models;
  }, [available.data, panelQuery]);

  useEffect(() => {
    if (openPanelIndex === null || available.data !== undefined || available.isFetching) return;
    void available.refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openPanelIndex, available.data, available.isFetching]);

  async function loadCatalog(selectId?: string) {
    setLoading(true);
    try {
      const payload = await getJson<ModelProviderCatalog>("/api/model-providers");
      setCatalog(payload);
      const nextId = selectId
        ?? payload.providers.find((provider) => provider.id === selectedId)?.id
        ?? payload.providers[0]?.id
        ?? null;
      setSelectedId(nextId);
      setCreating(nextId === null);
      const nextProvider = payload.providers.find((provider) => provider.id === nextId);
      setDraft(nextProvider ? draftFromProvider(nextProvider) : emptyDraft());
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : t("settings.loadError") });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadCatalog();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function updateDraft(patch: Partial<ProviderDraft>) {
    setDraft((current) => ({ ...current, ...patch }));
    onNotice(undefined);
    setTestResult(undefined);
  }

  function selectProvider(id: string | null, asNew = false) {
    setSelectedId(asNew ? null : id);
    setCreating(asNew);
    setTestResult(undefined);
    setOpenPanelIndex(null);
    setPanelQuery("");
    onNotice(undefined);
    setAppliedTemplate(null);
    if (asNew) {
      // 新草稿不继承上一个草稿拉取到的候选清单。
      queryClient.removeQueries({ queryKey: ["provider-available-models", "draft"] });
    }
    const provider = asNew ? undefined : catalog?.providers.find((item) => item.id === id);
    setDraft(provider ? draftFromProvider(provider) : emptyDraft());
  }

  function updateModel(index: number, patch: Partial<ProviderDraft["models"][number]>) {
    updateDraft({
      models: draft.models.map((model, itemIndex) => (
        itemIndex === index ? { ...model, ...patch } : model
      )),
    });
  }

  function addModelRow() {
    updateDraft({ models: [...draft.models, { id: "", enabled: true }] });
    setOpenPanelIndex(null);
  }

  function removeModel(index: number) {
    updateDraft({ models: draft.models.filter((_, itemIndex) => itemIndex !== index) });
    setOpenPanelIndex(null);
  }

  function togglePanel(index: number) {
    setOpenPanelIndex((current) => (current === index ? null : index));
    setPanelQuery("");
  }

  function pickAvailableModel(index: number, id: string) {
    updateModel(index, { id });
    setOpenPanelIndex(null);
    setPanelQuery("");
  }

  async function refreshAvailableModels() {
    onNotice(undefined);
    const result = await available.refetch();
    if (result.error) {
      const message = result.error instanceof Error ? result.error.message : t("settings.providerFetchError");
      onNotice({ kind: "error", text: message });
      return;
    }
    onNotice({
      kind: "ok",
      text: t("settings.providerFetchOk").replace("{count}", String(result.data?.length ?? 0)),
    });
  }

  function applyTemplate(template: (typeof TEMPLATES)[number]) {
    if (!creating) return; // 快速填充只用于新建
    // 模板自带协议（Anthropic 官方）时按该协议取端点；否则按当前协议取。
    const protocol = template.protocol ?? draft.protocol;
    updateDraft({
      name: t(template.nameKey),
      base_url: template.baseUrls[protocol] ?? draft.base_url,
      ...(template.protocol ? { protocol: template.protocol } : {}),
    });
    setAppliedTemplate(template.key);
  }

  function changeProtocol(protocol: WireProtocol) {
    // 快速填充的草稿改协议时跟随模板切换端点；URL 已被手改（不在模板端点
    // 集合里）则保持不动，避免覆盖用户输入。
    const template = TEMPLATES.find((item) => item.key === appliedTemplate);
    const nextUrl = template?.baseUrls[protocol];
    const patch: Partial<ProviderDraft> = { protocol };
    if (
      creating
      && nextUrl
      && template
      && Object.values(template.baseUrls).includes(draft.base_url.trim())
    ) {
      patch.base_url = nextUrl;
    }
    updateDraft(patch);
  }

  function parseOverrides(): Record<string, unknown> | null {
    const text = draft.overrides_text.trim();
    if (!text) return {};
    try {
      const parsed = JSON.parse(text) as unknown;
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>;
      }
      return null;
    } catch {
      return null;
    }
  }

  async function saveProvider() {
    if (!creating && !selectedId) return;
    const overrides = parseOverrides();
    if (overrides === null) {
      onNotice({ kind: "error", text: t("settings.providerOverridesInvalid") });
      return;
    }
    if (!draft.name.trim() || draftModels.length === 0) return;
    setSaving(true);
    onNotice(undefined);
    try {
      const shared = {
        name: draft.name.trim(),
        base_url: draft.base_url.trim(),
        protocol: draft.protocol,
        enabled: draft.enabled,
        models: draftModels,
        request_overrides: overrides,
        api_key: draft.api_key || null,
      };
      const payload = creating
        ? await postJson<ModelProviderCatalog & { created_id: string }>(
            "/api/model-providers",
            shared,
          )
        : await putJson<ModelProviderCatalog>(
            `/api/model-providers/${encodeURIComponent(selectedId!)}`,
            { ...shared, clear_api_key: draft.clear_api_key },
          );
      setCatalog(payload);
      const nextId = creating
        ? (payload as ModelProviderCatalog & { created_id: string }).created_id
        : selectedId!;
      const nextProvider = payload.providers.find((provider) => provider.id === nextId);
      setSelectedId(nextId);
      setCreating(false);
      setAppliedTemplate(null);
      setOpenPanelIndex(null);
      setPanelQuery("");
      setDraft(nextProvider ? draftFromProvider(nextProvider) : emptyDraft());
      // key / base_url 可能刚改过，旧可用清单作废
      await queryClient.invalidateQueries({ queryKey: ["provider-available-models", nextId] });
      onNotice({ kind: "ok", text: t("settings.providerSaved") });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : t("settings.saveError") });
    } finally {
      setSaving(false);
    }
  }

  async function deleteProvider(id: string) {
    const provider = catalog?.providers.find((item) => item.id === id);
    const confirmed = window.confirm(
      t("settings.providerDeleteConfirm").replace("{name}", provider?.name ?? id),
    );
    if (!confirmed) return;
    try {
      const payload = await deleteJson<ModelProviderCatalog>(
        `/api/model-providers/${encodeURIComponent(id)}`,
      );
      setCatalog(payload);
      selectProvider(payload.providers[0]?.id ?? null);
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : t("settings.saveError") });
    }
  }

  async function testProvider() {
    if (!selectedId) return;
    setTesting(true);
    setTestResult(undefined);
    try {
      setTestResult(await postJson<ProviderTestResult>(
        `/api/model-providers/${encodeURIComponent(selectedId)}/test`,
        {},
      ));
    } catch (error) {
      setTestResult({ ok: false, message: error instanceof Error ? error.message : t("settings.testError") });
    } finally {
      setTesting(false);
    }
  }

  async function setDefault(providerId: string, modelId: string) {
    onNotice(undefined);
    try {
      const payload = await putJson<ModelProviderCatalog>(
        "/api/model-providers/default-selection",
        { provider_id: providerId, model_id: modelId },
      );
      setCatalog(payload);
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : t("settings.saveError") });
    }
  }

  const defaultSelection = catalog?.default_selection ?? null;
  // 草稿就绪 = key 齐备且（base_url 齐备或 Anthropic 官方端点可留空）。
  const draftFetchReady =
    draft.api_key.trim().length > 0
    && (draft.base_url.trim().length > 0 || draft.protocol === "anthropic");
  // 草稿态的行内下拉在拉取成功（且结果非空）后才可用。
  const availableModelsReady = (available.data?.length ?? 0) > 0;
  // 空行（新建后未填调用名）在保存时丢弃
  const draftModels = draft.models
    .map((model) => ({
      id: model.id.trim(),
      display_name: model.display_name?.trim() || null,
      enabled: model.enabled,
      max_input_tokens: model.max_input_tokens ?? null,
    }))
    .filter((model) => model.id);

  return (
    <div className="provider-manager">
      <div className="provider-list" role="list">
        {catalog?.providers.map((provider) => {
          const health = !provider.enabled ? "off" : provider.api_key_configured ? "ok" : "warn";
          const healthTitle = health === "off"
            ? t("settings.providerDisabledBadge")
            : health === "warn"
              ? t("settings.providerNoKeyBadge")
              : undefined;
          return (
            <button
              key={provider.id}
              type="button"
              role="listitem"
              className={!creating && provider.id === selectedId ? "provider-item active" : "provider-item"}
              onClick={() => selectProvider(provider.id)}
            >
              <Box size={12} className="provider-item-icon" />
              <span className="provider-item-name">{provider.name}</span>
              <span className={`provider-dot ${health}`} title={healthTitle} />
            </button>
          );
        })}
        <button
          type="button"
          className={creating ? "provider-item add active" : "provider-item add"}
          onClick={() => selectProvider(null, true)}
        >
          <Plus size={12} />
          <span>{t("settings.providerAdd")}</span>
        </button>
      </div>
      <div className="provider-editor">
        {loading ? (
          <div className="settings-loading"><LoaderCircle className="spin" size={18} />{t("settings.loading")}</div>
        ) : !editorVisible ? (
          <div className="command-state">
            {(catalog?.providers.length ?? 0) === 0
              ? t("settings.providerEmpty")
              : t("settings.providerSelectHint")}
          </div>
        ) : (
          <>
            {creating && (
              <div className="provider-templates">
                <span>{t("settings.providerTemplates")}:</span>
                {TEMPLATES.map((template) => (
                  <button key={template.key} type="button" onClick={() => applyTemplate(template)}>
                    {t(template.nameKey)}
                  </button>
                ))}
              </div>
            )}
            <label className="settings-field"><span>{t("settings.providerName")}</span>
              <input value={draft.name} onChange={(event) => updateDraft({ name: event.target.value })} placeholder="OpenRouter" />
            </label>
            <label className="settings-field"><span>{t("settings.baseUrl")}</span>
              <input value={draft.base_url} onChange={(event) => updateDraft({ base_url: event.target.value })} placeholder="https://api.openai.com/v1" />
            </label>
            <label className="settings-field"><span>{t("settings.protocol")}</span>
              <select value={draft.protocol} onChange={(event) => changeProtocol(event.target.value as WireProtocol)}>
                <option value="chat_completions">{t("settings.protocolChatCompletions")}</option>
                <option value="responses">{t("settings.protocolResponses")}</option>
                <option value="anthropic">{t("settings.protocolAnthropic")}</option>
              </select>
            </label>
            <label className="settings-field"><span>{t("settings.apiKey")}</span>
              <div className="secret-input">
                <KeyRound size={14} />
                <input
                  type={showKey ? "text" : "password"}
                  value={draft.api_key}
                  onChange={(event) => updateDraft({ api_key: event.target.value, clear_api_key: false })}
                  placeholder={selected?.api_key_configured ? `${selected.api_key_hint ?? "••••"} — ${t("settings.apiKeyKeep")}` : t("settings.apiKeyEnter")}
                />
                <button type="button" onClick={() => setShowKey((current) => !current)} aria-label={showKey ? t("settings.hideKey") : t("settings.showKey")}>
                  {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            </label>
            {selected?.api_key_configured && (
              <label className="clear-secret">
                <input type="checkbox" checked={draft.clear_api_key} onChange={(event) => updateDraft({ clear_api_key: event.target.checked, api_key: "" })} />
                <span>{t("settings.clearKey")}</span>
              </label>
            )}
            <label className="clear-secret">
              <input type="checkbox" checked={draft.enabled} onChange={(event) => updateDraft({ enabled: event.target.checked })} />
              <span>{t("settings.providerEnabled")}</span>
            </label>

            <div className="settings-field provider-models-field">
              <div className="provider-models-header">
                <span>{t("settings.providerModels")}</span>
                <button
                  type="button"
                  className="provider-models-fetch"
                  onClick={() => void refreshAvailableModels()}
                  disabled={available.isFetching || (creating && !draftFetchReady)}
                >
                  {available.isFetching && <LoaderCircle className="spin" size={12} />}
                  {available.isFetching ? t("settings.providerFetching") : t("settings.providerFetchModels")}
                </button>
              </div>
              <div className="provider-models-list">
                {draft.models.map((model, index) => {
                  const isDefault = !creating
                    && defaultSelection?.provider_id === selectedId
                    && defaultSelection.model_id === model.id;
                  const panelOpen = openPanelIndex === index;
                  return (
                    <div key={index} className="provider-model-row">
                      <div className="provider-model-line">
                        <input
                          className="provider-model-id-input"
                          value={model.id}
                          onChange={(event) => updateModel(index, { id: event.target.value })}
                          placeholder={t("settings.providerModelPlaceholder")}
                        />
                        <input
                          className="provider-model-display-input"
                          value={model.display_name ?? ""}
                          onChange={(event) => updateModel(index, { display_name: event.target.value })}
                          placeholder={t("settings.providerModelDisplayName")}
                        />
                        <input
                          className="provider-model-window-input"
                          type="number"
                          min={8000}
                          max={2000000}
                          value={model.max_input_tokens ?? ""}
                          onChange={(event) => {
                            const raw = event.target.value;
                            const parsed = Number(raw);
                            updateModel(index, {
                              max_input_tokens: raw === "" || !Number.isFinite(parsed)
                                ? null
                                : parsed,
                            });
                          }}
                          placeholder={t("settings.providerModelMaxInputTokens")}
                          aria-label={`${t("settings.providerModelMaxInputTokens")}: ${model.id}`}
                        />
                        <button
                          type="button"
                          className={isDefault ? "provider-model-default active" : "provider-model-default"}
                          title={isDefault ? t("chat.modelDefault") : t("settings.providerSetDefault")}
                          aria-label={`${t("settings.providerSetDefault")}: ${model.id}`}
                          disabled={creating || !model.id.trim()}
                          onClick={() => selectedId && void setDefault(selectedId, model.id)}
                        >
                          <Star size={13} fill={isDefault ? "currentColor" : "none"} />
                        </button>
                        <button
                          type="button"
                          className="provider-model-panel-toggle"
                          aria-label={`${t("settings.providerModelOptions")}: ${model.id}`}
                          aria-expanded={panelOpen}
                          disabled={creating && !availableModelsReady}
                          onClick={() => togglePanel(index)}
                        >
                          <ChevronRight size={14} />
                        </button>
                        <button
                          type="button"
                          className="provider-model-remove"
                          onClick={() => removeModel(index)}
                          aria-label={`${t("settings.providerDelete")}: ${model.id}`}
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                      {panelOpen && (
                        <div className="provider-model-panel">
                          <label className="provider-model-search">
                            <Search size={12} />
                            <input
                              value={panelQuery}
                              onChange={(event) => setPanelQuery(event.target.value)}
                              placeholder={t("settings.providerModelSearch")}
                            />
                          </label>
                          {available.isError ? (
                            <div className="command-state error">{(available.error as Error).message}</div>
                          ) : available.data === undefined ? (
                            <div className="command-state">{t("settings.providerFetching")}</div>
                          ) : filteredAvailable.length === 0 ? (
                            <div className="command-state">{t("settings.providerAvailableEmpty")}</div>
                          ) : (
                            <div className="provider-model-available">
                              {filteredAvailable.map((id) => (
                                <button
                                  key={id}
                                  type="button"
                                  className={id === model.id ? "active" : ""}
                                  onClick={() => pickAvailableModel(index, id)}
                                >
                                  {id}
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
              <button type="button" className="provider-model-add-row" onClick={addModelRow}>
                <Plus size={12} />
                <span>{t("settings.providerAddModel")}</span>
              </button>
            </div>

            <label className="settings-field"><span>{t("settings.providerRequestOverrides")}</span>
              <textarea
                rows={2}
                value={draft.overrides_text}
                onChange={(event) => updateDraft({ overrides_text: event.target.value })}
                placeholder='{"thinking_budget": 1000}'
              />
            </label>

            <div className="provider-actions">
              <button className="provider-save" type="button" onClick={() => void saveProvider()} disabled={saving || !draft.name.trim() || draftModels.length === 0}>
                {saving ? <LoaderCircle className="spin" size={14} /> : <Save size={14} />}
                {t("settings.providerSave")}
              </button>
              <button className="provider-test" type="button" onClick={() => void testProvider()} disabled={creating || testing}>
                {testing ? <LoaderCircle className="spin" size={14} /> : <TestTube2 size={14} />}
                {t("settings.providerTest")}
              </button>
              {selectedId && !creating && (
                <button className="provider-delete" type="button" onClick={() => void deleteProvider(selectedId)}>
                  <Trash2 size={14} />
                  {t("settings.providerDelete")}
                </button>
              )}
            </div>
            {testResult && (
              <div className={testResult.ok ? "provider-test-result ok" : "provider-test-result error"}>
                {testResult.ok ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
                <span>
                  <b>{testResult.ok ? t("settings.testSuccess") : testResult.message}</b>
                  {testResult.ok && <small>{testResult.model} · {testResult.protocol} · JSON · {testResult.latency_ms} ms</small>}
                </span>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
