import { useEffect, useState } from "react";
import {
  Activity,
  ArrowLeft,
  Bot,
  BrainCircuit,
  CheckCircle2,
  FolderOpen,
  FlaskConical,
  Languages,
  LoaderCircle,
  RotateCcw,
  Save,
  Server,
  XCircle,
} from "lucide-react";
import { useI18n } from "../i18n";
import { isDesktopRuntime, openLogsDirectory, productFetch, restartBackend, runtimeConfig } from "../runtime";
import { ProviderManager } from "./ProviderManager";
import type { AppSettings } from "../types";

type SettingsSection = "model" | "interface" | "runtime" | "workspace";

type SettingsDraft = {
  openai_base_url: string;
  openai_model: string;
  openai_api_protocol: AppSettings["openai_api_protocol"];
  openai_api_key: string;
  clear_openai_api_key: boolean;
  log_level: AppSettings["log_level"];
  app_language: AppSettings["app_language"];
  enable_agent_memory: boolean;
  enable_external_research: boolean;
  memory_recall_token_budget: number;
  agent_context_max_tokens: number;
};

const emptyDraft: SettingsDraft = {
  openai_base_url: "",
  openai_model: "qwen3.6-plus",
  openai_api_protocol: "chat_completions",
  openai_api_key: "",
  clear_openai_api_key: false,
  log_level: "INFO",
  app_language: "zh-CN",
  enable_agent_memory: false,
  enable_external_research: false,
  memory_recall_token_budget: 800,
  agent_context_max_tokens: 512000,
};

function formatContextWindow(value: number): string {
  return value >= 1_000_000
    ? `${value / 1_000_000}M`
    : `${Math.round(value / 1_000)}K`;
}

export function SettingsView({ onClose }: { onClose: () => void }) {
  const { setLanguage, t } = useI18n();
  const [section, setSection] = useState<SettingsSection>("model");
  const [stored, setStored] = useState<AppSettings>();
  const [draft, setDraft] = useState<SettingsDraft>(emptyDraft);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "error" | "restart"; text: string }>();
  const [runtime, setRuntime] = useState(() => runtimeConfig());
  const [workspacePath, setWorkspacePath] = useState("");
  const [workspaceSaving, setWorkspaceSaving] = useState(false);
  const contextPresets = stored?.agent_context_max_token_presets?.length
    ? stored.agent_context_max_token_presets
    : [200000, 400000, 512000, 1000000];
  const contextIndex = Math.max(
    0,
    contextPresets.indexOf(draft.agent_context_max_tokens),
  );

  async function loadSettings() {
    setLoading(true);
    try {
      const response = await productFetch("/api/settings");
      if (!response.ok) throw new Error(t("settings.apiUnavailable"));
      const settings = await response.json() as AppSettings;
      setStored(settings);
      setDraft({
        openai_base_url: settings.openai_base_url,
        openai_model: settings.openai_model,
        openai_api_protocol: settings.openai_api_protocol,
        openai_api_key: "",
        clear_openai_api_key: false,
        log_level: settings.log_level,
        app_language: settings.app_language,
        enable_agent_memory: settings.enable_agent_memory,
        enable_external_research: settings.enable_external_research,
        memory_recall_token_budget: settings.memory_recall_token_budget,
        agent_context_max_tokens: settings.agent_context_max_tokens,
      });
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : t("settings.loadError") });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadSettings();
    void loadWorkspace();
    // Product API owns the durable Agent runtime.
    void productFetch("/health")
      .then((response) => setRuntime({ ...runtimeConfig(), ready: response.ok }))
      .catch(() => setRuntime({ ...runtimeConfig(), ready: false }));
  }, []);

  function updateDraft(patch: Partial<SettingsDraft>) {
    setDraft((current) => ({ ...current, ...patch }));
    setNotice(undefined);
  }

  async function saveSettings() {
    setSaving(true);
    setNotice(undefined);
    try {
      const response = await productFetch("/api/settings", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(draft),
      });
      const payload = await response.json().catch(() => null) as (AppSettings & { detail?: string }) | null;
      if (!response.ok || !payload) throw new Error(payload?.detail ?? t("settings.saveError"));
      setStored(payload);
      setLanguage(payload.app_language);
      setDraft((current) => ({ ...current, openai_api_key: "", clear_openai_api_key: false }));
      setNotice({
        kind: payload.restart_required ? "restart" : "ok",
        text: payload.restart_required ? t("settings.savedRestart") : t("settings.saved"),
      });
      if (payload.restart_required && isDesktopRuntime) {
        try {
          const newRuntime = await restartBackend();
          setRuntime(newRuntime);
          setNotice({ kind: "ok", text: t("settings.saved") + " " + t("settings.backendRestarted") });
        } catch (restartError) {
          setNotice({ kind: "error", text: t("settings.restartFailed") + " " + (restartError instanceof Error ? restartError.message : String(restartError)) });
        }
      }
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : t("settings.saveError") });
    } finally {
      setSaving(false);
    }
  }

  async function loadWorkspace() {
    try {
      const response = await productFetch("/api/workspace");
      if (!response.ok) throw new Error(t("settings.workspaceLoadError"));
      const payload = await response.json() as { path?: string };
      setWorkspacePath(payload.path ?? "");
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : t("settings.workspaceLoadError") });
    }
  }

  async function pickWorkspaceDirectory() {
    try {
      const { open } = await import("@tauri-apps/plugin-dialog");
      const selected = await open({ directory: true, multiple: false });
      if (typeof selected === "string" && selected) setWorkspacePath(selected);
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : t("settings.workspaceError") });
    }
  }

  async function selectWorkspace() {
    setWorkspaceSaving(true);
    setNotice(undefined);
    try {
      const response = await productFetch("/api/workspace/select", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ path: workspacePath.trim() }),
      });
      const payload = await response.json().catch(() => null) as { path?: string; status?: string; requires_restart?: boolean; detail?: string } | null;
      if (!response.ok || !payload) throw new Error(payload?.detail ?? t("settings.workspaceError"));
      if (payload.path) setWorkspacePath(payload.path);
      setNotice({
        kind: payload.requires_restart ? "restart" : "ok",
        text: payload.requires_restart ? t("settings.workspaceSavedRestart") : t("settings.saved"),
      });
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : t("settings.workspaceError") });
    } finally {
      setWorkspaceSaving(false);
    }
  }

  const page = section === "model"
    ? { eyebrow: t("settings.providersEyebrow"), title: t("settings.modelTitle") }
    : section === "interface"
      ? { eyebrow: t("settings.interfaceEyebrow"), title: t("settings.interfaceTitle") }
      : section === "workspace"
        ? { eyebrow: t("settings.workspace"), title: t("settings.workspaceTitle") }
        : { eyebrow: t("settings.localServices"), title: t("settings.runtimeTitle") };

  return (
    <section className="settings-workspace">
      <aside className="settings-nav">
        <div className="settings-nav-heading">
          <span>{t("settings.eyebrow")}</span>
          <h1>{t("settings.title")}</h1>
        </div>
        <nav>
          <button className={section === "model" ? "active" : ""} onClick={() => setSection("model")}>
            <Bot size={15} /><span><b>{t("settings.model")}</b></span>
          </button>
          <button className={section === "interface" ? "active" : ""} onClick={() => setSection("interface")}>
            <Languages size={15} /><span><b>{t("settings.interface")}</b></span>
          </button>
          <button className={section === "runtime" ? "active" : ""} onClick={() => setSection("runtime")}>
            <Activity size={15} /><span><b>{t("settings.runtime")}</b></span>
          </button>
          <button data-testid="settings-workspace-nav" className={section === "workspace" ? "active" : ""} onClick={() => setSection("workspace")}>
            <FolderOpen size={15} /><span><b>{t("settings.workspace")}</b></span>
          </button>
        </nav>
        <button className="settings-back" onClick={onClose}><ArrowLeft size={14} />{t("settings.back")}</button>
      </aside>

      <div className="settings-scroll">
        <header className="settings-page-header">
          <div><span>{page.eyebrow}</span><h2>{page.title}</h2></div>
          <button className="settings-save" onClick={() => void saveSettings()} disabled={saving || loading}>
            {saving ? <LoaderCircle className="spin" size={14} /> : <Save size={14} />}{t("settings.save")}
          </button>
        </header>

        {notice && <div className={`settings-notice ${notice.kind}`}>{notice.kind === "error" ? <XCircle size={15} /> : notice.kind === "restart" ? <RotateCcw size={15} /> : <CheckCircle2 size={15} />}<span>{notice.text}</span></div>}

        {loading ? (
          <div className="settings-loading"><LoaderCircle className="spin" size={18} />{t("settings.loading")}</div>
        ) : section === "workspace" ? (
          <div className="settings-content">
            <section className="settings-card workspace-card">
              <div className="settings-card-title"><Server size={16} /><div><h3>{t("settings.workspaceTitle")}</h3></div></div>
              <label className="settings-field"><span>{t("settings.workspacePath")}</span><input data-testid="workspace-path" value={workspacePath} onChange={(event) => setWorkspacePath(event.target.value)} placeholder="D:\KB\my-kb" /></label>
              <div className="workspace-actions">{isDesktopRuntime && <button className="workspace-browse" type="button" onClick={() => void pickWorkspaceDirectory()}>{t("settings.workspaceBrowse")}</button>}<button className="workspace-select" type="button" onClick={() => void selectWorkspace()} disabled={workspaceSaving || !workspacePath.trim()}>{workspaceSaving ? <LoaderCircle className="spin" size={14} /> : <Save size={14} />}{t("settings.workspaceSelect")}</button></div>
            </section>
          </div>
        ) : section === "model" ? (
          <div className="settings-content">
            <section className="settings-card provider-catalog-card">
              <div className="settings-card-title">
                <Server size={16} />
                <div><h3>{t("settings.modelTitle")}</h3></div>
                <span className="provider-restart-badge">{t("settings.providerRestartNotRequired")}</span>
              </div>
              <ProviderManager onNotice={setNotice} />
            </section>
          </div>
        ) : section === "interface" ? (
          <div className="settings-content">
            <section className="settings-card language-card">
              <div className="settings-card-title"><Languages size={16} /><div><h3>{t("settings.languageTitle")}</h3></div></div>
              <div className="language-options">
                <button className={draft.app_language === "zh-CN" ? "active" : ""} onClick={() => updateDraft({ app_language: "zh-CN" })}><span className="language-monogram">中</span><span><b>{t("settings.chinese")}</b></span><i /></button>
                <button className={draft.app_language === "en" ? "active" : ""} onClick={() => updateDraft({ app_language: "en" })}><span className="language-monogram">EN</span><span><b>{t("settings.english")}</b></span><i /></button>
              </div>
            </section>
            <section className="settings-card experimental-card">
              <div className="settings-card-title"><BrainCircuit size={16} /><div><h3>{t("settings.experimentalTitle")}</h3></div><span>{t("settings.defaultOff")}</span></div>
              <label className="clear-secret"><input type="checkbox" checked={draft.enable_agent_memory} onChange={(event) => updateDraft({ enable_agent_memory: event.target.checked })} /><span><BrainCircuit size={13} />{t("settings.agentMemory")}</span></label>
              <label className="clear-secret"><input type="checkbox" checked={draft.enable_external_research} onChange={(event) => updateDraft({ enable_external_research: event.target.checked })} /><span><FlaskConical size={13} />{t("settings.externalResearch")}</span></label>
              <label className="settings-field"><span>{t("settings.memoryBudget")}</span><input type="number" min={128} max={4000} value={draft.memory_recall_token_budget} onChange={(event) => updateDraft({ memory_recall_token_budget: Number(event.target.value) })} /></label>
            </section>
          </div>
        ) : (
          <div className="settings-content">
            <section className="settings-card runtime-grid">
              <RuntimeStatus label="Product API + Agent Runtime" endpoint={runtime.productApiOrigin || "127.0.0.1"} online={runtime.ready} />
              <RuntimeStatus label="Runtime mode" endpoint={runtime.mode} online={runtime.ready} />
            </section>
            <section className="settings-card context-window-card">
              <div className="settings-card-title">
                <Activity size={16} />
                <div><h3>{t("settings.contextWindowTitle")}</h3></div>
                <span className="provider-restart-badge">{t("settings.contextWindowRestartBadge")}</span>
              </div>
              <div className="context-window-control">
                <input
                  data-testid="context-window-slider"
                  className="context-window-slider"
                  type="range"
                  min={0}
                  max={contextPresets.length - 1}
                  step={1}
                  value={contextIndex}
                  aria-label={t("settings.contextWindowTitle")}
                  onChange={(event) => {
                    const preset = contextPresets[Number(event.target.value)];
                    if (preset !== undefined) {
                      updateDraft({ agent_context_max_tokens: preset });
                    }
                  }}
                />
                <div className="context-window-ticks" aria-hidden="true">
                  {contextPresets.map((preset) => (
                    <span
                      key={preset}
                      className={preset === draft.agent_context_max_tokens ? "active" : ""}
                    >
                      {formatContextWindow(preset)}
                    </span>
                  ))}
                </div>
              </div>
              <div className="context-window-summary">
                <span>{t("settings.contextWindowCurrent")}</span>
                <strong>{formatContextWindow(draft.agent_context_max_tokens)}</strong>
              </div>
              <p className="context-window-hint">{t("settings.contextWindowHint")}</p>
            </section>
            <section className="settings-card">
              <div className="settings-card-title"><Activity size={16} /><div><h3>{t("settings.logging")}</h3></div></div>
              <label className="settings-field"><span>{t("settings.logLevel")}</span><select value={draft.log_level} onChange={(event) => updateDraft({ log_level: event.target.value as AppSettings["log_level"] })}>{["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"].map((level) => <option key={level}>{level}</option>)}</select></label>
            </section>
            <section className="settings-card runtime-actions">
              <button onClick={() => void restartBackend().then(setRuntime).catch((error) => setNotice({ kind: "error", text: String(error) }))}><RotateCcw size={14} />{t("settings.restartBackend")}</button>
              <button onClick={() => void openLogsDirectory().catch((error) => setNotice({ kind: "error", text: String(error) }))}><FolderOpen size={14} />{t("settings.openLogs")}</button>
              <small>{runtime.logsDir}</small>
            </section>
          </div>
        )}
      </div>
    </section>
  );
}

function RuntimeStatus({ label, endpoint, online }: { label: string; endpoint: string; online: boolean }) {
  const { t } = useI18n();
  return <div className="runtime-status"><span className={online ? "online" : "offline"}><i />{online ? t("runtime.online") : t("runtime.offline")}</span><h3>{label}</h3><p>{endpoint}</p></div>;
}
