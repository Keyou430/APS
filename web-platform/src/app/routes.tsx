export type RouteStatus =
  | "loading"
  | "empty"
  | "error"
  | "forbidden"
  | "conflict"
  | "success";

export type AppRoute = {
  id: string;
  label: string;
  path: string;
  permissions: string[];
  status: "legacy-host" | "react-ready" | "presentation-only";
  statuses: RouteStatus[];
};

const standardStatuses: RouteStatus[] = [
  "loading",
  "empty",
  "error",
  "forbidden",
  "conflict",
  "success",
];

export const appRoutes: AppRoute[] = [
  {
    id: "portal",
    label: "企业门户",
    path: "/portal",
    permissions: ["portal:read"],
    status: "react-ready",
    statuses: standardStatuses,
  },
  {
    id: "dashboard",
    label: "驾驶舱",
    path: "/",
    permissions: ["portal:read"],
    status: "legacy-host",
    statuses: standardStatuses,
  },
  {
    id: "organization",
    label: "组织架构",
    path: "/organization",
    permissions: ["org:read"],
    status: "react-ready",
    statuses: standardStatuses,
  },
  {
    id: "users",
    label: "用户管理",
    path: "/users",
    permissions: ["users:read"],
    status: "react-ready",
    statuses: standardStatuses,
  },
  {
    id: "invitations",
    label: "邀请管理",
    path: "/invitations",
    permissions: ["members:invite"],
    status: "react-ready",
    statuses: standardStatuses,
  },
  {
    id: "knowledge",
    label: "知识库",
    path: "/knowledge",
    permissions: ["knowledge:read"],
    status: "react-ready",
    statuses: standardStatuses,
  },
  {
    id: "chat",
    label: "会话",
    path: "/chat",
    permissions: ["chat:use"],
    status: "react-ready",
    statuses: standardStatuses,
  },
  {
    id: "pipeline",
    label: "Pipeline",
    path: "/pipeline",
    permissions: ["work_items:read"],
    status: "react-ready",
    statuses: standardStatuses,
  },
  {
    id: "work-items",
    label: "工作项",
    path: "/work-items",
    permissions: ["work_items:read"],
    status: "legacy-host",
    statuses: standardStatuses,
  },
  {
    id: "memory",
    label: "记忆",
    path: "/memory",
    permissions: ["memory:read"],
    status: "react-ready",
    statuses: standardStatuses,
  },
  {
    id: "skills",
    label: "技能",
    path: "/skills",
    permissions: ["skills:read"],
    status: "react-ready",
    statuses: standardStatuses,
  },
  {
    id: "reminders",
    label: "提醒",
    path: "/reminders",
    permissions: ["reminders:read"],
    status: "react-ready",
    statuses: standardStatuses,
  },
  {
    id: "hermes",
    label: "Hermes Profiles",
    path: "/hermes",
    permissions: ["agent:admin"],
    status: "react-ready",
    statuses: standardStatuses,
  },
];

const reactOwnedRouteIds = new Set([
  "chat",
  "hermes",
  "invitations",
  "organization",
  "pipeline",
  "portal",
  "users",
  "knowledge",
]);

export function resolveRoute(pathname: string): AppRoute {
  return (
    appRoutes.find((route) => route.path === pathname) ??
    appRoutes.find((route) => route.id === "dashboard") ??
    appRoutes[0]
  );
}

export function isReactOwnedRoute(pathname: string): boolean {
  return reactOwnedRouteIds.has(resolveRoute(pathname).id);
}
