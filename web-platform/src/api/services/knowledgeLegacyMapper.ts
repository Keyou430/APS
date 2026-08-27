type AnyRecord = Record<string, unknown>;

export type LegacyKnowledgeCard = {
  display_name: string;
  enabled: boolean;
  id: string;
  is_default_import_target: boolean;
  link_url?: string;
  resource_id: string;
  resource_type: string;
  stale: boolean;
  title: string;
};

function stringValue(value: unknown, fallback = "") {
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  return fallback;
}

function isEnabled(entry: AnyRecord) {
  if (entry.enabled === false) return false;
  const status = stringValue(entry.status).toLowerCase();
  return entry.enabled !== false && status !== "archived" && status !== "deleted" && status !== "disabled";
}

function mapEntry(entry: unknown): LegacyKnowledgeCard {
  const item = (entry || {}) as AnyRecord;
  const id = stringValue(item.id);
  const title = stringValue(item.title, stringValue(item.name, `Knowledge ${id}`));
  const resourceType = stringValue(item.type, "knowledge");
  return {
    display_name: title,
    enabled: isEnabled(item),
    id,
    is_default_import_target: false,
    ...(resourceType === "link" ? { link_url: stringValue(item.url) } : {}),
    resource_id: id ? `knowledge-${id}` : "knowledge-entry",
    resource_type: resourceType,
    stale: false,
    title,
  };
}

export function mapKnowledgeEntriesToLegacyCards(
  response: { items?: unknown[] } | unknown[] | null | undefined,
): LegacyKnowledgeCard[] {
  const items = Array.isArray(response)
    ? response
    : Array.isArray(response?.items)
      ? response.items
      : [];
  return items.map(mapEntry);
}
