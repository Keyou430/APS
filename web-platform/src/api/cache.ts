type CachePart = string | number | boolean | null | undefined;

function buildCacheKey(organizationId: number | string, parts: CachePart[]) {
  return `${organizationId}:${parts.map((part) => String(part)).join(":")}`;
}

export function createOrganizationCache() {
  const values = new Map<string, unknown>();

  return {
    get<T>(organizationId: number | string, parts: CachePart[]): T | undefined {
      return values.get(buildCacheKey(organizationId, parts)) as T | undefined;
    },
    invalidateOrganization(organizationId: number | string) {
      const prefix = `${organizationId}:`;
      for (const key of values.keys()) {
        if (key.startsWith(prefix)) values.delete(key);
      }
    },
    set<T>(organizationId: number | string, parts: CachePart[], value: T) {
      values.set(buildCacheKey(organizationId, parts), value);
    },
  };
}

export function createOrganizationAbortRegistry() {
  const controllers = new Map<string, Set<AbortController>>();

  return {
    abortOrganization(organizationId: number | string) {
      const prefix = `${organizationId}:`;
      for (const [key, scopedControllers] of controllers.entries()) {
        if (!key.startsWith(prefix)) continue;
        scopedControllers.forEach((controller) => controller.abort());
        controllers.delete(key);
      }
    },
    createSignal(organizationId: number | string, scope: string) {
      const key = `${organizationId}:${scope}`;
      const controller = new AbortController();
      const scopedControllers = controllers.get(key) || new Set();
      scopedControllers.add(controller);
      controllers.set(key, scopedControllers);
      controller.signal.addEventListener(
        "abort",
        () => scopedControllers.delete(controller),
        { once: true },
      );
      return controller.signal;
    },
  };
}
