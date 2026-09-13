import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronDown, CircleAlert, Search } from "lucide-react";
import { getJson } from "../../lib/product-api";
import { useUiStore } from "../../stores/ui-store";
import type { ModelProviderCatalog, ModelSelection } from "../../types";
import { useI18n } from "../../i18n";

// ---------------------------------------------------------------------------
// Composer 模型切换器：供应商分组的 popover（CommandPalette 交互范式：
// backdrop + 键盘导航 + Esc 关闭）。全局当前模型语义：选择作用于下一次 run。
// 已停用供应商整组隐藏；缺 Key 的供应商仍列出（带警示）但发送时后端会
// 显式拒绝，避免静默回退默认模型。
// ---------------------------------------------------------------------------
export function ModelSwitcher({ disabled }: { disabled?: boolean }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const selectedModel = useUiStore((state) => state.selectedModel);
  const setSelectedModel = useUiStore((state) => state.setSelectedModel);

  const catalog = useQuery({
    queryKey: ["model-providers"],
    queryFn: () => getJson<ModelProviderCatalog>("/api/model-providers"),
    enabled: open,
    placeholderData: (previous) => previous,
  });

  useEffect(() => {
    if (!open) return;
    setActiveIndex(0);
    setQuery("");
    window.requestAnimationFrame(() => inputRef.current?.focus());
  }, [open]);

  const providers = catalog.data?.providers ?? [];
  const defaultSelection = catalog.data?.default_selection ?? null;

  const selectable = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return providers
      .filter((provider) => provider.enabled && provider.models.length > 0)
      .map((provider) => {
        const models = provider.models.filter(
          (model) =>
            model.enabled
            && (!needle
              || model.id.toLowerCase().includes(needle)
              || provider.name.toLowerCase().includes(needle)),
        );
        return { provider, models };
      })
      .filter((entry) => entry.models.length > 0);
  }, [providers, query]);

  const flattened: ModelSelection[] = useMemo(
    () =>
      selectable.flatMap((entry) =>
        entry.models.map((model) => ({
          provider_id: entry.provider.id,
          model_id: model.id,
        })),
      ),
    [selectable],
  );

  const defaultLabel = defaultSelection
    ? `${defaultSelection.model_id}`
    : t("chat.modelDefault");

  function choose(selection: ModelSelection | null) {
    setSelectedModel(selection);
    setOpen(false);
  }

  function currentLabel(): string {
    if (!selectedModel) return defaultLabel;
    return selectedModel.model_id;
  }

  function isDefaultSelection(selection: ModelSelection): boolean {
    return defaultSelection?.provider_id === selection.provider_id
      && defaultSelection?.model_id === selection.model_id;
  }

  const totalOptions = flattened.length + (selectedModel ? 1 : 0);

  return (
    <div className="model-switcher">
      <button
        type="button"
        className="model-switcher-button"
        onClick={() => setOpen((value) => !value)}
        disabled={disabled}
        title={t("chat.modelSwitch")}
        aria-label={t("chat.modelSwitch")}
        aria-expanded={open}
      >
        <span>{currentLabel()}</span>
        <ChevronDown size={12} />
      </button>
      {open && (
        <>
          <div
            className="model-switcher-backdrop"
            role="presentation"
            onMouseDown={() => setOpen(false)}
          />
          <div className="model-switcher-popover" role="dialog" aria-label={t("chat.modelSwitch")}>
            <div className="command-input">
              <Search size={14} />
              <input
                ref={inputRef}
                value={query}
                placeholder={t("chat.modelSearchPlaceholder")}
                onChange={(event) => { setQuery(event.target.value); setActiveIndex(0); }}
                onKeyDown={(event) => {
                  if (event.key === "Escape") setOpen(false);
                  if (event.key === "ArrowDown") {
                    event.preventDefault();
                    setActiveIndex((index) => Math.min(index + 1, Math.max(totalOptions - 1, 0)));
                  }
                  if (event.key === "ArrowUp") {
                    event.preventDefault();
                    setActiveIndex((index) => Math.max(index - 1, 0));
                  }
                  if (event.key === "Enter") {
                    event.preventDefault();
                    if (selectedModel && activeIndex === 0) {
                      choose(null);
                      return;
                    }
                    const index = selectedModel ? activeIndex - 1 : activeIndex;
                    if (flattened[index]) choose(flattened[index]);
                  }
                }}
              />
            </div>
            <div className="model-switcher-options">
              {catalog.isLoading && <div className="command-state">{t("settings.loading")}</div>}
              {catalog.isError && <div className="command-state error">{t("chat.modelLoadError")}</div>}
              {!catalog.isLoading && !catalog.isError && flattened.length === 0 && (
                <div className="command-state">{t("chat.modelEmpty")}</div>
              )}
              {selectedModel && (
                <button
                  type="button"
                  className={activeIndex === 0 ? "model-option active" : "model-option"}
                  onMouseEnter={() => setActiveIndex(0)}
                  onClick={() => choose(null)}
                >
                  <span className="model-option-name">{t("chat.modelFollowDefault")}</span>
                  <em>{defaultLabel}</em>
                  <Check size={13} className="model-option-check" />
                </button>
              )}
              {selectable.map((entry) => (
                <div key={entry.provider.id} className="model-group">
                  <div className="model-group-header">
                    <span>{entry.provider.name}</span>
                    {!entry.provider.api_key_configured && (
                      <span className="model-group-warning" title={t("chat.modelNeedsKey")}>
                        <CircleAlert size={12} />
                        {t("chat.modelNeedsKey")}
                      </span>
                    )}
                  </div>
                  {entry.models.map((model) => {
                    const selection: ModelSelection = {
                      provider_id: entry.provider.id,
                      model_id: model.id,
                    };
                    const index = flattened.findIndex(
                      (item) => item.provider_id === selection.provider_id
                        && item.model_id === selection.model_id,
                    );
                    const optionIndex = selectedModel ? index + 1 : index;
                    const active = selectedModel
                      ? selectedModel.provider_id === selection.provider_id
                        && selectedModel.model_id === selection.model_id
                      : isDefaultSelection(selection);
                    return (
                      <button
                        key={model.id}
                        type="button"
                        className={optionIndex === activeIndex ? "model-option active" : "model-option"}
                        onMouseEnter={() => setActiveIndex(optionIndex)}
                        onClick={() => choose(selection)}
                      >
                        <span className="model-option-name">{model.display_name || model.id}</span>
                        {active && <Check size={13} className="model-option-check" />}
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
            <footer>{t("chat.modelConfigureHint")}</footer>
          </div>
        </>
      )}
    </div>
  );
}
