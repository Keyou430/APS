import { assertMockNetworkAllowed } from "./mockMode";

export type ApiRequestOptions = Omit<RequestInit, "body" | "headers"> & {
  accessToken?: string;
  body?: BodyInit | Record<string, unknown> | unknown[] | null;
  headers?: Record<string, string>;
  skipAuth?: boolean;
  skipRefresh?: boolean;
  responseType?: "json" | "blob";
};

export type ApiClient = {
  request<T = unknown>(path: string, options?: ApiRequestOptions): Promise<T>;
  upload?<T = unknown>(path: string, body: FormData, options?: ApiUploadOptions): Promise<T>;
};

export type ApiUploadOptions = {
  headers?: Record<string, string>;
  onProgress?: (loaded: number, total: number) => void;
};

export type ApiClientOptions = {
  baseUrl?: string;
  clearSession?: () => void;
  fetchFn?: typeof fetch;
  getAccessToken?: () => string | null | undefined;
  mockMode?: boolean;
  refresh?: () => Promise<void>;
  xhrFactory?: () => XMLHttpRequest;
};

export class ApiError extends Error {
  status: number;
  code?: string;
  details?: unknown;

  constructor(status: number, message: string, code?: string, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

let refreshPromise: Promise<void> | null = null;

function normalizeBaseUrl(baseUrl: string) {
  const trimmed = baseUrl.trim();
  if (!trimmed || trimmed === "/") return "";
  return trimmed.endsWith("/") ? trimmed.slice(0, -1) : trimmed;
}

function normalizePath(path: string) {
  if (/^https?:\/\//i.test(path)) return path;
  const withoutApiPrefix = path.startsWith("/api/")
    ? path.slice("/api".length)
    : path;
  return withoutApiPrefix.startsWith("/")
    ? withoutApiPrefix
    : `/${withoutApiPrefix}`;
}

function buildUrl(baseUrl: string, path: string) {
  if (/^https?:\/\//i.test(path)) return path;
  return `${normalizeBaseUrl(baseUrl)}${normalizePath(path)}`;
}

function isAuthEndpoint(path: string) {
  const normalized = normalizePath(path);
  return (
    normalized === "/auth/login" ||
    normalized === "/auth/token" ||
    normalized === "/auth/refresh" ||
    normalized === "/auth/logout"
  );
}

function isJsonBody(body: ApiRequestOptions["body"]) {
  if (body == null || typeof body === "string") return false;
  if (typeof FormData !== "undefined" && body instanceof FormData) return false;
  if (typeof Blob !== "undefined" && body instanceof Blob) return false;
  if (typeof URLSearchParams !== "undefined" && body instanceof URLSearchParams)
    return false;
  return true;
}

async function parseResponse(response: Response, responseType?: "json" | "blob") {
  if (response.status === 204) return undefined;
  if (responseType === "blob") return response.blob();
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) return response.json();
  return response.text();
}

async function throwApiError(response: Response): Promise<never> {
  const payload = await parseResponse(response).catch(() => null);
  const error =
    payload && typeof payload === "object" && "error" in payload
      ? (payload as { error?: { code?: string; message?: string; details?: unknown } }).error
      : null;
  const detail =
    payload && typeof payload === "object" && "detail" in payload
      ? (payload as { detail?: unknown }).detail
      : null;
  throw new ApiError(
    response.status,
    error?.message || (typeof detail === "string" ? detail : null) || response.statusText || "Request failed",
    error?.code,
    error?.details,
  );
}

export function createApiClient(options: ApiClientOptions = {}): ApiClient {
  const baseUrl = options.baseUrl ?? "/api";
  const fetchFn = options.fetchFn ?? fetch.bind(globalThis);

  async function ensureRefresh() {
    if (!options.refresh) return;
    if (!refreshPromise) {
      refreshPromise = options.refresh().finally(() => {
        refreshPromise = null;
      });
    }
    await refreshPromise;
  }

  async function request<T = unknown>(
    path: string,
    requestOptions: ApiRequestOptions = {},
    hasRetried = false,
  ): Promise<T> {
    if (options.mockMode) assertMockNetworkAllowed(path);
    const { responseType, ...fetchOptions } = requestOptions;
    const headers: Record<string, string> = {
      ...(requestOptions.headers || {}),
    };
    const token = requestOptions.accessToken ?? options.getAccessToken?.();
    if (token && !requestOptions.skipAuth) {
      headers.Authorization = `Bearer ${token}`;
    }

    let body = requestOptions.body as BodyInit | null | undefined;
    if (isJsonBody(requestOptions.body)) {
      headers["Content-Type"] = headers["Content-Type"] || "application/json";
      body = JSON.stringify(requestOptions.body);
    }

    const response = await fetchFn(buildUrl(baseUrl, path), {
      ...fetchOptions,
      headers,
      body,
    });

    if (
      response.status === 401 &&
      !hasRetried &&
      !requestOptions.skipRefresh &&
      !isAuthEndpoint(path) &&
      options.refresh &&
      token
    ) {
      try {
        await ensureRefresh();
      } catch (error) {
        options.clearSession?.();
        throw error;
      }
      return request(path, requestOptions, true);
    }

    if (!response.ok) await throwApiError(response);
    return parseResponse(response, responseType) as Promise<T>;
  }

  function upload<T = unknown>(
    path: string,
    body: FormData,
    uploadOptions: ApiUploadOptions = {},
  ): Promise<T> {
    if (options.mockMode) assertMockNetworkAllowed(path);
    const factory = options.xhrFactory ?? (() => new XMLHttpRequest());
    return new Promise<T>((resolve, reject) => {
      const xhr = factory();
      xhr.open("POST", buildUrl(baseUrl, path), true);
      const token = options.getAccessToken?.();
      if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
      Object.entries(uploadOptions.headers || {}).forEach(([name, value]) => {
        xhr.setRequestHeader(name, value);
      });
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) uploadOptions.onProgress?.(event.loaded, event.total);
      };
      xhr.onerror = () => reject(new ApiError(0, "Network request failed"));
      xhr.onabort = () => reject(new ApiError(0, "Upload cancelled"));
      xhr.onload = () => {
        const contentType = xhr.getResponseHeader("content-type") || "";
        let payload: unknown = xhr.responseText;
        if (contentType.includes("application/json") && xhr.responseText) {
          try {
            payload = JSON.parse(xhr.responseText);
          } catch {
            reject(new ApiError(xhr.status, "Invalid JSON response"));
            return;
          }
        }
        if (xhr.status < 200 || xhr.status >= 300) {
          const error = payload && typeof payload === "object" && "error" in payload
            ? (payload as { error?: { code?: string; message?: string; details?: unknown } }).error
            : null;
          reject(new ApiError(xhr.status, error?.message || xhr.statusText || "Request failed", error?.code, error?.details));
          return;
        }
        resolve(payload as T);
      };
      xhr.send(body);
    });
  }

  return { request, upload };
}
