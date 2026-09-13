import { useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  Eye,
  EyeOff,
  KeyRound,
  LoaderCircle,
  Plus,
  Save,
  Server,
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
} from "../types";

// ---------------------------------------------------------------------------
// 供应商目录管理（设置 → 模型服务）。与全局保存按钮无关：每个供应商的
// 保存/测试/拉取/删除都是独立即时操作，保存后免重启对下一条 run 生效。
// key 只写不读：表单留空 = 保留已存密钥。
// ---------------------------------------------------------------------------

type ProviderDraft = {
  name: string;
  base_url: string;
  protocol: "chat_completions" | "responses";
  enabled: boolean;
  models: { id: string; display_name?: string | null; enabled: boolean }[];
  api_key: string;
  clear_api_key: boolean;
  overrides_text: string;
};

type TemplateKey = "bailian" | "openrouter" | "deepseek" | "siliconflow" | "ollama";

const TEMPLATES: { key: TemplateKey; nameKey: MessageKey; baseUrl: string }[] = [
  { key: "bailian", nameKey: "settings.templateBailian", baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1" },
  { key: "openrouter", nameKey: "settings.templateOpenRouter", baseUrl: "https://openrouter.ai/api/v1" },
  { key: "deepseek", nameKey: "settings.templateDeepSeek", baseUrl: "https://api.deepseek.com/v1" },
  { key: "siliconflow", nameKey: "settings.templateSiliconFlow", baseUrl: "https://api.siliconflow.cn/v1" },
  { key: "ollama", nameKey: "settings.templateOllama", baseUrl: "http://127.0.0.1:11434/v1" },
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
  const [showKey, setShowKey] = useState(false);
  const [modelInput, setModelInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [testResult, setTestResult] = useState<ProviderTestResult>();
  const [loading, setLoading] = useState(true);

  const selected = useMemo(
    () => catalog?.providers.find((provider) => provider.id === selectedId),
    [catalog, selectedId],
  );
  const editorVisible = creating || selected !== undefined;

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
    onNotice(undefined);
    const provider = asNew ? undefined : catalog?.providers.find((item) => item.id === id);
    setDraft(provider ? draftFromProvider(provider) : emptyDraft());
  }

  function addModel() {
    const id = modelInput.trim();
    if (!id || draft.models.some((model) => model.id === id)) {
      setModelInput("");
      return;
    }
    updateDraft({ models: [...draft.models, { id, enabled: true }] });
    setModelInput("");
  }

  function removeModel(id: string) {
    updateDraft({ models: draft.models.filter((model) => model.id !== id) });
  }

  function applyTemplate(template: (typeof TEMPLATES)[number]) {
    if (!creating) return; // 快速填充只用于新建
    updateDraft({ name: t(template.nameKey), base_url: template.baseUrl });
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
    if (!draft.name.trim() || draft.models.length === 0) return;
    setSaving(true);
    onNotice(undefined);
    try {
      const shared = {
        name: draft.name.trim(),
        base_url: draft.base_url.trim(),
        protocol: draft.protocol,
        enabled: draft.enabled,
        models: draft.models,
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
      setDraft(nextProvider ? draftFromProvider(nextProvider) : emptyDraft());
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

  async function fetchModels() {
    if (!selectedId) return;
    setFetching(true);
    onNotice(undefined);
    try {
      const payload = await postJson<{ models: string[] }>(
        `/api/model-providers/${encodeURIComponent(selectedId)}/fetch-models`,
        {},
      );
      const existing = new Set(draft.models.map((model) => model.id));
      const merged = [
        ...draft.models,
        ...payload.models
          .filter((id) => !existing.has(id))
          .map((id) => ({ id, enabled: true })),
      ];
      updateDraft({ models: merged });
      onNotice({ kind: "ok", text: t("settings.providerFetchOk").replace("{count}", String(payload.models.length)) });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : t("settings.providerFetchError") });
    } finally {
      setFetching(false);
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

  return (
    <div className="provider-manager">
      <div className="provider-list" role="list">
        {catalog?.providers.map((provider) => (
          <button
            key={provider.id}
            type="button"
            role="listitem"
            className={!creating && provider.id === selectedId ? "provider-item active" : "provider-item"}
            onClick={() => selectProvider(provider.id)}
          >
            <span className="provider-item-name">{provider.name}</span>
            <small>{provider.base_url || "OpenAI"}</small>
            <span className="provider-item-badges">
              {defaultSelection?.provider_id === provider.id && <i className="provider-badge default">{t("settings.providerDefaultBadge")}</i>}
              {!provider.enabled && <i className="provider-badge">{t("settings.providerDisabledBadge")}</i>}
              {!provider.api_key_configured && <i className="provider-badge warn">{t("settings.providerNoKeyBadge")}</i>}
            </span>
          </button>
        ))}
        <button
          type="button"
          className={creating ? "provider-item add active" : "provider-item add"}
          onClick={() => selectProvider(null, true)}
        >
          <Plus size={14} />
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
              <small>{t("settings.providerNameHint")}</small>
            </label>
            <label className="settings-field"><span>{t("settings.baseUrl")}</span>
              <input value={draft.base_url} onChange={(event) => updateDraft({ base_url: event.target.value })} placeholder="https://api.openai.com/v1" />
              <small>{t("settings.baseUrlHint")}</small>
            </label>
            <label className="settings-field"><span>{t("settings.protocol")}</span>
              <select value={draft.protocol} onChange={(event) => updateDraft({ protocol: event.target.value as ProviderDraft["protocol"] })}>
                <option value="chat_completions">{t("settings.protocolChatCompletions")}</option>
                <option value="responses">{t("settings.protocolResponses")}</option>
              </select>
              <small>{t("settings.protocolHint")}</small>
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
              <small>{t("settings.apiKeyHint")}</small>
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
              <span>{t("settings.providerModels")}</span>
              <div className="provider-model-list">
                {draft.models.map((model) => {
                  const isDefault = !creating
                    && defaultSelection?.provider_id === selectedId
                    && defaultSelection.model_id === model.id;
                  return (
                    <span key={model.id} className="provider-model-row">
                      <button
                        type="button"
                        className={isDefault ? "provider-model-default active" : "provider-model-default"}
                        title={t("settings.providerSetDefault")}
                        aria-label={`${t("settings.providerSetDefault")}: ${model.id}`}
                        disabled={creating}
                        onClick={() => selectedId && void setDefault(selectedId, model.id)}
                      >
                        <Star size={12} />
                      </button>
                      <code>{model.id}</code>
                      <button type="button" className="provider-model-remove" onClick={() => removeModel(model.id)} aria-label={`${t("settings.providerDelete")}: ${model.id}`}>
                        <XCircle size={12} />
                      </button>
                    </span>
                  );
                })}
              </div>
              <div className="provider-model-add">
                <input
                  value={modelInput}
                  onChange={(event) => setModelInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      addModel();
                    }
                  }}
                  placeholder={t("settings.providerModelPlaceholder")}
                />
                <button
                  type="button"
                  onClick={() => void fetchModels()}
                  disabled={creating || fetching}
                  title={t("settings.providerFetchModels")}
                >
                  {fetching ? <LoaderCircle className="spin" size={13} /> : <Server size={13} />}
                  {fetching ? t("settings.providerFetching") : t("settings.providerFetchModels")}
                </button>
              </div>
              <small>{t("settings.providerModelsHint")}</small>
            </div>

            <label className="settings-field"><span>{t("settings.providerRequestOverrides")}</span>
              <textarea
                rows={2}
                value={draft.overrides_text}
                onChange={(event) => updateDraft({ overrides_text: event.target.value })}
                placeholder='{"thinking_budget": 1000}'
              />
              <small>{t("settings.providerRequestOverridesHint")}</small>
            </label>

            <div className="provider-actions">
              <button className="provider-save" type="button" onClick={() => void saveProvider()} disabled={saving || !draft.name.trim() || draft.models.length === 0}>
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
