export type SseFrame = {
  data: unknown;
  event: string;
};

export type ChatStreamOptions = {
  baseUrl?: string;
  fetchFn?: typeof fetch;
  getAccessToken?: () => string | null | undefined;
  refresh?: () => Promise<void>;
  clearSession?: () => void;
};

export type ChatStreamSendOptions = {
  signal?: AbortSignal;
};

export type ChatStreamService = {
  sendMessageStream(
    sessionId: string,
    request: Record<string, unknown>,
    options?: ChatStreamSendOptions,
  ): Promise<Response>;
};

export function parseSseFrames(input: string): SseFrame[] {
  return input
    .split(/\r?\n\r?\n/)
    .filter((frame) => frame.trim())
    .map((frame) => {
      let event = "message";
      const dataLines: string[] = [];
      for (const line of frame.split(/\r?\n/)) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      const dataText = dataLines.join("\n");
      let data: unknown = dataText;
      try {
        data = dataText ? JSON.parse(dataText) : null;
      } catch {
        data = dataText;
      }
      return { event, data };
    });
}

function normalizeBaseUrl(baseUrl: string) {
  const trimmed = baseUrl.trim();
  if (!trimmed || trimmed === "/") return "";
  return trimmed.endsWith("/") ? trimmed.slice(0, -1) : trimmed;
}

export function createChatStreamService(
  options: ChatStreamOptions = {},
): ChatStreamService {
  const baseUrl = options.baseUrl ?? "/api";
  const fetchFn = options.fetchFn ?? fetch.bind(globalThis);
  let refreshPromise: Promise<void> | null = null;

  async function refreshOnce() {
    if (!options.refresh) return false;
    if (!refreshPromise) {
      refreshPromise = options.refresh().finally(() => {
        refreshPromise = null;
      });
    }
    await refreshPromise;
    return true;
  }

  async function send(
    sessionId: string,
    request: Record<string, unknown>,
    sendOptions: ChatStreamSendOptions,
    hasRetried: boolean,
  ): Promise<Response> {
    const headers: Record<string, string> = {
      Accept: "text/event-stream",
      "Content-Type": "application/json",
    };
    const token = options.getAccessToken?.();
    if (token) headers.Authorization = `Bearer ${token}`;
    const response = await fetchFn(
      `${normalizeBaseUrl(baseUrl)}/chat/sessions/${sessionId}/messages`,
      {
        body: JSON.stringify(request),
        headers,
        method: "POST",
        signal: sendOptions.signal,
      },
    );
    if (response.status === 401 && !hasRetried && options.refresh) {
      try {
        await refreshOnce();
      } catch (error) {
        options.clearSession?.();
        throw error;
      }
      return send(sessionId, request, sendOptions, true);
    }
    if (!response.ok) {
      const payload = await response.clone().json().catch(() => null) as
        | { detail?: string; error?: { message?: string } }
        | null;
      const message = payload?.error?.message || payload?.detail || response.statusText || "请求失败";
      const error = new Error(message) as Error & { status?: number };
      error.status = response.status;
      throw error;
    }
    return response;
  }

  return {
    sendMessageStream(sessionId, request, sendOptions = {}) {
      return send(sessionId, request, sendOptions, false);
    },
  };
}
