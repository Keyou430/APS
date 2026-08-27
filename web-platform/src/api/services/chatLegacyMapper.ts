type AnyRecord = Record<string, unknown>;

export type LegacyChatMessage = {
  content: string;
  createdAt: string;
  id: string;
  references?: unknown[];
  role: string;
  status: string;
};

export type LegacyChatSession = {
  createdAt: string;
  id: string;
  messages: LegacyChatMessage[];
  title: string;
  updatedAt: string;
};

function stringValue(value: unknown, fallback = "") {
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  return fallback;
}

function dateTimeValue(value: unknown) {
  const text = stringValue(value);
  if (!text) return "";
  return `${text.slice(0, 10)} ${text.slice(11, 16)}`.trim();
}

function timeValue(value: unknown) {
  const text = stringValue(value);
  return text ? text.slice(11, 16) : "";
}

function itemsOf(payload: { items?: unknown[] } | unknown[] | null | undefined) {
  return Array.isArray(payload)
    ? payload
    : Array.isArray(payload?.items)
      ? payload.items
      : [];
}

export function mapChatMessagesToLegacyMessages(
  payload: { items?: unknown[] } | unknown[] | null | undefined,
): LegacyChatMessage[] {
  return itemsOf(payload).map((message) => {
    const item = (message || {}) as AnyRecord;
    return {
      content: stringValue(item.content),
      createdAt: timeValue(item.created_at ?? item.createdAt),
      id: `m_bk_${stringValue(item.id)}`,
      references: Array.isArray(item.references) ? item.references : undefined,
      role: stringValue(item.role, "assistant"),
      status: "completed",
    };
  });
}

export function mapChatSessionsToLegacySessions(
  payload: { items?: unknown[] } | unknown[] | null | undefined,
): LegacyChatSession[] {
  return itemsOf(payload).map((session) => {
    const item = (session || {}) as AnyRecord;
    return {
      createdAt: dateTimeValue(item.created_at ?? item.createdAt),
      id: stringValue(item.id),
      messages: [],
      title: stringValue(item.title),
      updatedAt: dateTimeValue(item.updated_at ?? item.updatedAt),
    };
  });
}
