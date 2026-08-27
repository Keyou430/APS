const allowedPrefixes = ["/auth/", "/chat/"];
const allowedExactPaths = new Set(["/health", "/ready"]);

export function assertMockNetworkAllowed(path: string) {
  const normalized = path.startsWith("/api/")
    ? path.slice("/api".length)
    : path.startsWith("/")
      ? path
      : `/${path}`;

  if (allowedExactPaths.has(normalized)) return;
  if (allowedPrefixes.some((prefix) => normalized.startsWith(prefix))) return;

  throw new Error(
    `Unexpected real request in mock mode: ${normalized}. Add a mock service adapter or explicitly allow the endpoint.`,
  );
}
