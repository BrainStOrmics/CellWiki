import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronDown } from "lucide-react";
import { getJson } from "../../lib/product-api";
import { useUiStore } from "../../stores/ui-store";
import type { ModelProviderCatalog, ModelSelection } from "../../types";
import { useI18n } from "../../i18n";

// ---------------------------------------------------------------------------
// Composer 模型切换器：供应商分组的纯列表 popover（无搜索框、无底部提示），
// 按钮在输入框右下角、紧邻发送键。全局当前模型语义：选择作用于下一次 run。
// 已停用供应商整组隐藏。键盘（↑↓/Enter/Esc）仍可用但默认不高亮任何行。
// ---------------------------------------------------------------------------
export function ModelSwitcher({ disabled }: { disabled?: boolean }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const popoverRef = useRef<HTMLDivElement>(null);
  const selectedModel = useUiStore((state) => state.selectedModel);
  const setSelectedModel = useUiStore((state) => state.setSelectedModel);

  const catalog = useQuery({
    queryKey: ["model-providers"],
    queryFn: () => getJson<ModelProviderCatalog>("/api/model-providers"),
    placeholderData: (previous) => previous,
  });

  useEffect(() => {
    if (!open) return;
    setActiveIndex(-1);
    window.requestAnimationFrame(() => popoverRef.current?.focus());
  }, [open]);

  const providers = catalog.data?.providers ?? [];
  const defaultSelection = catalog.data?.default_selection ?? null;
  // 当前生效的模型（按钮上显示的那个）：钩只打在这一行上。
  const current = selectedModel ?? defaultSelection;

  const selectable = useMemo(
    () =>
      providers
        .filter((provider) => provider.enabled && provider.models.length > 0)
        .map((provider) => ({
          provider,
          models: provider.models.filter((model) => model.enabled),
        }))
        .filter((entry) => entry.models.length > 0),
    [providers],
  );

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

  function labelFor(selection: ModelSelection | null): string {
    if (!selection) return t("chat.modelDefault");
    const model = providers
      .find((provider) => provider.id === selection.provider_id)
      ?.models.find((item) => item.id === selection.model_id);
    return model?.display_name || selection.model_id;
  }

  function choose(selection: ModelSelection) {
    setSelectedModel(selection);
    setOpen(false);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") setOpen(false);
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((index) => Math.min(index + 1, Math.max(flattened.length - 1, 0)));
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((index) => Math.max(index - 1, 0));
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const target = flattened[activeIndex];
      if (target) choose(target);
    }
  }

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
        <span>{labelFor(selectedModel ?? defaultSelection)}</span>
        <ChevronDown size={12} />
      </button>
      {open && (
        <>
          <div
            className="model-switcher-backdrop"
            role="presentation"
            onMouseDown={() => setOpen(false)}
          />
          <div
            ref={popoverRef}
            className="model-switcher-popover"
            role="dialog"
            aria-label={t("chat.modelSwitch")}
            tabIndex={-1}
            onKeyDown={handleKeyDown}
          >
            <div className="model-switcher-options">
              {catalog.isLoading && <div className="command-state">{t("settings.loading")}</div>}
              {catalog.isError && <div className="command-state error">{t("chat.modelLoadError")}</div>}
              {!catalog.isLoading && !catalog.isError && flattened.length === 0 && (
                <div className="command-state">{t("chat.modelEmpty")}</div>
              )}
              {selectable.map((entry) => (
                <div key={entry.provider.id} className="model-group">
                  <div className="model-group-header">{entry.provider.name}</div>
                  {entry.models.map((model) => {
                    const index = flattened.findIndex(
                      (item) => item.provider_id === entry.provider.id
                        && item.model_id === model.id,
                    );
                    const isCurrent = current?.provider_id === entry.provider.id
                      && current?.model_id === model.id;
                    return (
                      <button
                        key={model.id}
                        type="button"
                        className={index === activeIndex ? "model-option active" : "model-option"}
                        onMouseEnter={() => setActiveIndex(index)}
                        onClick={() => choose({ provider_id: entry.provider.id, model_id: model.id })}
                      >
                        <span className="model-option-label">{model.display_name || model.id}</span>
                        {isCurrent && <Check size={13} className="model-option-check" aria-hidden />}
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
