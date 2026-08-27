export type PageCache = {
  get<T>(organizationId: number, parts: string[]): T | undefined;
  invalidateOrganization(organizationId: number): void;
  set<T>(organizationId: number, parts: string[], value: T): void;
};

export function asObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

export function readString(value: unknown, fallback = "") {
  return typeof value === "string" ? value : fallback;
}

export function readNumber(value: unknown, fallback = 0) {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

export function readArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export function errorStatus(error: unknown): number | null {
  const value = asObject(error);
  return readNumber(value.status, readNumber(value.statusCode, 0)) || null;
}
