import type { ModelCatalog, ModelSelection } from "./types";

export interface ModelChoice {
  selection: ModelSelection;
  providerId: string;
  providerName: string;
  modelId: string;
  /** Display label for the model (display_name fallback to id). */
  label: string;
  hasKey: boolean;
}

export function flattenModelChoices(catalog: ModelCatalog): ModelChoice[] {
  const choices: ModelChoice[] = [];
  for (const provider of catalog.providers ?? []) {
    if (provider.enabled === false) {
      continue;
    }
    for (const model of provider.models ?? []) {
      if (model.enabled === false) {
        continue;
      }
      choices.push({
        selection: { provider_id: provider.id, model_id: model.id },
        providerId: provider.id,
        providerName: provider.name ?? provider.id,
        modelId: model.id,
        label: model.display_name ?? model.id,
        hasKey: provider.api_key_configured !== false,
      });
    }
  }
  return choices;
}

export function modelChoiceMatches(
  choice: ModelChoice,
  query: string,
): boolean {
  const normalized = query.trim().toLowerCase();
  if (!normalized) {
    return true;
  }
  return `${choice.label} ${choice.modelId} ${choice.providerId} ${choice.providerName}`
    .toLowerCase()
    .includes(normalized);
}

export function findModelChoice(
  choices: ModelChoice[],
  modelId: string,
): ModelChoice | null {
  const normalized = modelId.trim().toLowerCase();
  if (!normalized) {
    return null;
  }
  return (
    choices.find((choice) => choice.modelId.toLowerCase() === normalized) ??
    choices.find((choice) => choice.label.toLowerCase() === normalized) ??
    null
  );
}

export function formatModelChoiceLabel(choice: ModelChoice): string {
  return `${choice.providerId}/${choice.modelId}`;
}
