import type { EnterprisePortalResponse } from "./enterpriseService";
import type { DashboardDataResponse } from "./dashboardService";

type AnyRecord = Record<string, unknown>;

export type LegacyPortalBootstrap = {
  portal?: {
    dashboard?: AnyRecord;
    news?: AnyRecord[];
    preferences?: AnyRecord;
    services?: unknown[];
    systems?: unknown[];
  };
  workspace?: {
    dashboard?: AnyRecord;
    documents?: unknown[];
    notices?: AnyRecord[];
    resources?: unknown[];
    shortcuts?: string[][];
    tasks?: AnyRecord[];
  };
};

function stringValue(value: unknown, fallback = "") {
  return typeof value === "string" ? value : fallback;
}

function booleanValue(value: unknown, fallback = false) {
  return typeof value === "boolean" ? value : fallback;
}

function arrayValue(value: unknown) {
  return Array.isArray(value) ? value : [];
}

function mapTodo(todo: unknown): AnyRecord {
  const item = (todo || {}) as AnyRecord;
  return {
    id: stringValue(item.id),
    title: stringValue(item.title),
    deadline: item.dueAt ?? null,
    dueTime: item.dueAt ?? null,
    done: booleanValue(item.completed),
    href: item.href ?? null,
    priority: stringValue(item.priority, "medium"),
    tag: "门户待办",
  };
}

function mapAnnouncement(announcement: unknown): AnyRecord {
  const item = (announcement || {}) as AnyRecord;
  return {
    id: stringValue(item.id),
    title: stringValue(item.title),
    body: item.content ?? item.summary ?? "",
    category: stringValue(item.priority, "normal"),
    pinned: booleanValue(item.isPinned),
    published_at: item.publishedAt ?? null,
    read: booleanValue(item.isRead),
    source: stringValue(item.author, "enterprise"),
    summary: stringValue(item.summary),
  };
}

function mapActivity(activity: unknown): AnyRecord {
  const item = (activity || {}) as AnyRecord;
  return {
    id: stringValue(item.id),
    body: stringValue(item.summary),
    category: stringValue(item.type, "news"),
    date: item.occurredAt ?? null,
    published_at: item.occurredAt ?? null,
    source: "enterprise",
    title: stringValue(item.title),
  };
}

function mapQuickLink(link: unknown): string[] {
  const item = (link || {}) as AnyRecord;
  return [
    stringValue(item.name, "快捷入口"),
    stringValue(item.url, "#"),
    "app-blue",
  ];
}

export function mapEnterprisePortalToLegacyBootstrap(
  portal: EnterprisePortalResponse,
  dashboard: DashboardDataResponse = {},
): LegacyPortalBootstrap {
  const company = portal.company || {};
  const currentUser = portal.currentUser || {};

  return {
    portal: {
      dashboard: {
        company,
        collaborators: portal.collaborators,
        departments: portal.departments,
        people: portal.people,
        positions: portal.positions,
      },
      news: arrayValue(portal.activities).map(mapActivity),
      preferences: {
        favorite_documents: [],
        favorite_subsystems: [],
        hidden_cards: [],
        card_order: [],
        news_subscriptions: [],
      },
      services: [],
      systems: [],
    },
    workspace: {
      dashboard: {
        company,
        calendarEvents: dashboard.calendarEvents || [],
        metrics: dashboard.metrics || [],
        notifications: dashboard.notifications || [],
        pipelines: dashboard.pipelines || [],
        profile: {
          name: stringValue(currentUser.name),
          department: stringValue(currentUser.department),
          email: stringValue(currentUser.email),
          position: stringValue(currentUser.position),
        },
        quickActions: dashboard.quickActions || [],
        recentVisits: dashboard.recentVisits || [],
        todos: dashboard.todos || [],
      },
      documents: [],
      notices: arrayValue(portal.announcements).map(mapAnnouncement),
      resources: [],
      shortcuts: arrayValue(portal.quickLinks).map(mapQuickLink),
      tasks: arrayValue(portal.todos).map(mapTodo),
    },
  };
}
