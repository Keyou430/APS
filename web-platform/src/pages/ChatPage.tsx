import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChatService } from "../api/services/chatService";
import { parseSseFrames, type ChatStreamService } from "../api/services/chatStream";
import type { KnowledgeService } from "../api/services/knowledgeService";
import { getFreshnessNotice } from "../app/chatEvidence";
import { renderSafeAssistantMarkdown } from "../security/safeMarkdown";
import { asObject, errorStatus, readArray, readNumber, readString, type PageCache } from "./pageUtils";

export type ChatSurface = "agent" | "knowledge";
type ChatPageProps = { cache: PageCache; initialSurface?: ChatSurface; knowledgeService: KnowledgeService; organizationId: number | null; service: ChatService; stream: ChatStreamService };
type PageStatus = "loading" | "empty" | "error" | "forbidden" | "success";
type KnowledgeScope = "all_visible" | "selected" | "none";
type Session = { id: string; title: string; createdAt: string; updatedAt: string; surface: ChatSurface; knowledge_scope: KnowledgeScope; source_ids: number[] };
type KnowledgeEntry = { id: number; title: string };
type ChatAttachment = { title: string; content: string };
type Citation = { ordinal: number; entryId?: number; title: string; contentSha256?: string; sourceLocator?: string };
type RetrievalMode = "hybrid" | "degraded_full_text" | "empty";
type CitationPreview = { title: string; content: string; sourceLocator?: string };
type WebSource = { url: string; title: string; published_at?: string; searched_at?: string; ordinal?: number };
type WebSearchState = "searching" | "sourced" | "empty" | "failed";
type PlatformAction = { message: string; status: string; taskId?: string; runId?: string };
type Message = { id: string; role: "user" | "assistant"; content: string; clientMessageId?: string; attachments?: ChatAttachment[]; status?: "streaming" | "completed" | "failed" | "interrupted"; turnId?: number; citations?: Citation[]; retrievalMode?: RetrievalMode; rejectedSourceCount?: number; webEvidence?: WebSource[]; webSearchState?: WebSearchState; webSearchUsed?: boolean; webSearchFailed?: boolean; platformAction?: PlatformAction };

function mapSession(value: unknown, index: number, fallbackSurface: ChatSurface): Session {
  const item = asObject(value);
  const numericId = readNumber(item.id, NaN);
  const id = Number.isFinite(numericId)
    ? String(numericId)
    : readString(item.id, `session-${index + 1}`);
  const rawSurface = readString(item.surface);
  const rawScope = readString(item.knowledge_scope);
  return {
    id,
    title: readString(item.title, "新会话"),
    createdAt: readString(item.created_at, readString(item.createdAt)),
    updatedAt: readString(item.updated_at, readString(item.updatedAt)),
    surface: rawSurface === "agent" || rawSurface === "knowledge" ? rawSurface : fallbackSurface,
    knowledge_scope: rawScope === "all_visible" || rawScope === "selected" || rawScope === "none" ? rawScope : "none",
    source_ids: readArray(item.source_ids).map((sourceId) => readNumber(sourceId, NaN)).filter(Number.isFinite),
  };
}
function mapCitation(value: unknown, index: number): Citation | null {
  const item = asObject(value);
  const ordinal = readNumber(item.ordinal, NaN);
  if (!Number.isFinite(ordinal)) return null;
  const entryId = readNumber(item.entry_id, NaN);
  const contentSha256 = readString(item.content_sha256);
  const sourceLocator = readString(item.source_locator);
  return {
    ordinal,
    entryId: Number.isFinite(entryId) ? entryId : undefined,
    title: readString(item.title, `知识来源 ${index + 1}`),
    contentSha256: contentSha256 || undefined,
    sourceLocator: sourceLocator || undefined,
  };
}
function mapRetrievalMode(value: unknown): RetrievalMode | undefined {
  const mode = readString(value);
  return mode === "hybrid" || mode === "degraded_full_text" || mode === "empty" ? mode : undefined;
}
function mapMessage(value: unknown, index: number): Message {
  const item = asObject(value);
  const role = readString(item.role, "assistant") === "user" ? "user" : "assistant";
  const turnId = readNumber(item.turn_id, NaN);
  const rejectedSourceCount = readNumber(item.rejected_source_count, NaN);
  const citations = readArray(item.citations).map(mapCitation).filter((citation): citation is Citation => citation !== null);
  const webEvidence = readArray(item.web_sources).map((source) => asObject(source)).filter((source) => /^https?:\/\//i.test(readString(source.url))).map((source, ordinal) => ({
    url: readString(source.url), title: readString(source.title, readString(source.url)), published_at: readString(source.published_at), searched_at: readString(source.searched_at), ordinal,
  }));
  return {
    id: readString(item.id, `message-${index + 1}`),
    role,
    content: readString(item.content),
    status: role === "assistant" ? "completed" : undefined,
    turnId: Number.isFinite(turnId) ? turnId : undefined,
    citations,
    retrievalMode: mapRetrievalMode(item.retrieval_mode),
    rejectedSourceCount: Number.isFinite(rejectedSourceCount) && rejectedSourceCount >= 0 ? rejectedSourceCount : undefined,
    webEvidence,
    webSearchState: webEvidence.length ? "sourced" : undefined,
  };
}
function items(value: unknown) { const item = asObject(value); return Array.isArray(value) ? value : readArray(item.items); }
function mapKnowledgeEntry(value: unknown): KnowledgeEntry | null {
  const item = asObject(value);
  const id = readNumber(item.id, NaN);
  if (!Number.isFinite(id) || readString(item.status).toLowerCase() === "archived" || item.enabled === false) return null;
  return { id, title: readString(item.title, `知识 ${id}`) };
}
function messageForError(error: unknown) { return errorStatus(error) === 403 ? "没有会话访问权限" : "聊天会话加载失败"; }
function actionIdentifier(value: unknown) { return typeof value === "string" || typeof value === "number" ? String(value) : undefined; }
function resolveInitialSurface(initialSurface?: ChatSurface): ChatSurface {
  if (initialSurface) return initialSurface;
  return typeof window !== "undefined" && new URLSearchParams(window.location.search).get("surface") === "knowledge" ? "knowledge" : "agent";
}

function renderPlatformAction(action: PlatformAction | undefined) {
  if (!action) return null;
  const identifiers = [action.taskId ? `任务 #${action.taskId}` : "", action.runId ? `运行 #${action.runId}` : ""].filter(Boolean).join("，");
  return <div className="chat-evidence-notice" data-testid="chat-platform-action" role="status">平台操作：{action.message}{identifiers ? `（${identifiers}）` : ""}</div>;
}

function renderWebEvidence(message: Message) {
  if (message.role !== "assistant") return null;
  if (message.webEvidence?.length) {
    return <div className="chat-references chat-web-sources" data-testid="chat-web-sources"><span className="ref-label">联网来源：</span>{message.webEvidence.map((source, index) => {
      const published = source.published_at?.slice(0, 10);
      const searched = source.searched_at?.slice(0, 10);
      const meta = [published ? `发布 ${published}` : "", searched ? `检索 ${searched}` : ""].filter(Boolean).join(" · ");
      return <a href={source.url} key={`${source.url}-${source.ordinal ?? index}`} rel="noopener noreferrer nofollow" target="_blank">{source.title}{meta ? <span className="web-source-meta">{meta}</span> : null}</a>;
    })}</div>;
  }
  if (message.webSearchState === "failed") return <div className="chat-evidence-notice" data-testid="web-search-failed-notice">联网搜索已执行，但未能取得可验证来源。</div>;
  if (message.webSearchState === "empty") return <div className="chat-evidence-notice" data-testid="web-search-empty-notice">联网搜索已完成，但没有可验证来源。</div>;
  return null;
}

function retrievalModeLabel(mode: RetrievalMode) {
  if (mode === "hybrid") return "混合检索";
  if (mode === "degraded_full_text") return "全文检索（降级）";
  return "未检索到内容";
}

function scopeDraft(session: Session | undefined, entries: KnowledgeEntry[], entriesLoaded: boolean) {
  if (!session) return { mode: "none" as KnowledgeScope, sourceIds: [] as number[] };
  if (session.knowledge_scope !== "selected" || !entriesLoaded) {
    return { mode: session.knowledge_scope, sourceIds: [...session.source_ids] };
  }
  const availableIds = new Set(entries.map((entry) => entry.id));
  return { mode: session.knowledge_scope, sourceIds: session.source_ids.filter((sourceId) => availableIds.has(sourceId)) };
}
const KNOWLEDGE_PAGE_SIZE = 100;

async function listAllKnowledgeEntries(knowledgeService: KnowledgeService) {
  const firstResponse = await knowledgeService.listEntries({ page: 1, page_size: KNOWLEDGE_PAGE_SIZE });
  const total = readNumber(asObject(firstResponse).total, NaN);
  const responsePageSize = readNumber(asObject(firstResponse).page_size, KNOWLEDGE_PAGE_SIZE);
  const pageSize = responsePageSize > 0 ? responsePageSize : KNOWLEDGE_PAGE_SIZE;
  const pageCount = Number.isFinite(total) ? Math.ceil(total / pageSize) : 1;
  const responses: unknown[] = [firstResponse];
  for (let page = 2; page <= pageCount; page += 1) {
    responses.push(await knowledgeService.listEntries({ page, page_size: KNOWLEDGE_PAGE_SIZE }));
  }
  const entriesById = new Map<number, KnowledgeEntry>();
  for (const response of responses) {
    for (const entry of items(response).map(mapKnowledgeEntry).filter((entry): entry is KnowledgeEntry => entry !== null)) {
      entriesById.set(entry.id, entry);
    }
  }
  return [...entriesById.values()];
}

export function ChatPage({ cache, initialSurface, knowledgeService, organizationId, service, stream }: ChatPageProps) {
  const [surface, setSurface] = useState<ChatSurface>(() => resolveInitialSurface(initialSurface));
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [status, setStatus] = useState<PageStatus>(organizationId === null ? "forbidden" : "loading");
  const [errorMessage, setErrorMessage] = useState<string | null>(organizationId === null ? "没有会话访问权限" : null);
  const [composer, setComposer] = useState("");
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [attachmentPending, setAttachmentPending] = useState(false);
  const [attachmentError, setAttachmentError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [actionPending, setActionPending] = useState<string | null>(null);
  const [knowledgeEntries, setKnowledgeEntries] = useState<KnowledgeEntry[]>([]);
  const [knowledgeEntriesLoading, setKnowledgeEntriesLoading] = useState(surface === "knowledge" && organizationId !== null);
  const [knowledgeEntriesLoaded, setKnowledgeEntriesLoaded] = useState(false);
  const [knowledgeEntriesError, setKnowledgeEntriesError] = useState<string | null>(null);
  const [scopeMode, setScopeMode] = useState<KnowledgeScope>("none");
  const [draftSourceIds, setDraftSourceIds] = useState<number[]>([]);
  const [scopePending, setScopePending] = useState(false);
  const [scopeError, setScopeError] = useState<string | null>(null);
  const [citationPreview, setCitationPreview] = useState<CitationPreview | null>(null);
  const [citationPreviewLoading, setCitationPreviewLoading] = useState(false);
  const [citationPreviewError, setCitationPreviewError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const selectedIdRef = useRef<string | null>(null);
  const mountedRef = useRef(true);
  const organizationIdRef = useRef(organizationId);
  const previousOrganizationIdRef = useRef(organizationId);
  const surfaceGenerationRef = useRef(0);
  const sessionsRequestRef = useRef(0);
  const messagesRequestRef = useRef(0);
  const createRequestRef = useRef(0);
  const streamGenerationRef = useRef(0);
  const attachmentRequestRef = useRef(0);
  const knowledgeEntriesRequestRef = useRef(0);
  const scopeRequestRef = useRef(0);
  const citationPreviewRequestRef = useRef(0);
  const knowledgeEntriesRef = useRef<KnowledgeEntry[]>([]);
  const knowledgeEntriesLoadedRef = useRef(false);
  const clientMessageSequenceRef = useRef(0);
  const citationTriggerRef = useRef<HTMLButtonElement | null>(null);
  const citationPreviewRef = useRef<HTMLElement | null>(null);
  const cacheKey = useMemo(() => ["chat", "sessions", surface], [surface]);
  const selectedSession = useMemo(() => sessions.find((session) => session.id === selectedId), [selectedId, sessions]);
  const selectedKnowledgeIdsAreAvailable = selectedSession?.knowledge_scope === "selected"
    && selectedSession.source_ids.length > 0
    && selectedSession.source_ids.every((sourceId) => knowledgeEntries.some((entry) => entry.id === sourceId));
  const persistedKnowledgeScopeReady = selectedSession?.knowledge_scope === "all_visible"
    || (knowledgeEntriesLoaded && selectedKnowledgeIdsAreAvailable);
  const knowledgeSendingBlocked = surface === "knowledge" && (scopePending || !persistedKnowledgeScopeReady);
  const composerDisabled = !selectedId || status === "loading" || sending || actionPending !== null || attachmentPending || knowledgeSendingBlocked;

  useEffect(() => {
    if (citationPreview) citationPreviewRef.current?.focus();
  }, [citationPreview]);

  useEffect(() => () => {
    mountedRef.current = false;
    surfaceGenerationRef.current += 1;
    sessionsRequestRef.current += 1;
    messagesRequestRef.current += 1;
    createRequestRef.current += 1;
    streamGenerationRef.current += 1;
    attachmentRequestRef.current += 1;
    knowledgeEntriesRequestRef.current += 1;
    citationPreviewRequestRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  useEffect(() => {
    organizationIdRef.current = organizationId;
    if (previousOrganizationIdRef.current === organizationId) return;
    previousOrganizationIdRef.current = organizationId;
    surfaceGenerationRef.current += 1;
    sessionsRequestRef.current += 1;
    messagesRequestRef.current += 1;
    createRequestRef.current += 1;
    streamGenerationRef.current += 1;
    attachmentRequestRef.current += 1;
    knowledgeEntriesRequestRef.current += 1;
    citationPreviewRequestRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    selectedIdRef.current = null;
    setSending(false);
    setAttachments([]);
    setAttachmentPending(false);
    setAttachmentError(null);
    setActionPending(null);
    knowledgeEntriesRef.current = [];
    knowledgeEntriesLoadedRef.current = false;
    setKnowledgeEntries([]);
    setKnowledgeEntriesLoading(false);
    setKnowledgeEntriesLoaded(false);
    setKnowledgeEntriesError(null);
    setScopeMode("none");
    setDraftSourceIds([]);
    setScopePending(false);
    setScopeError(null);
    setCitationPreview(null);
    setCitationPreviewLoading(false);
    setCitationPreviewError(null);
    setSelectedId(null);
    setSessions([]);
    setMessages([]);
    setErrorMessage(organizationId === null ? "没有会话访问权限" : null);
    setStatus(organizationId === null ? "forbidden" : "loading");
  }, [organizationId]);

  useEffect(() => {
    const requestId = ++knowledgeEntriesRequestRef.current;
    if (surface !== "knowledge" || organizationId === null) return;
    const requestOrganizationId = organizationId;
    const surfaceGeneration = surfaceGenerationRef.current;
    const isCurrent = () => mountedRef.current
      && organizationIdRef.current === requestOrganizationId
      && surfaceGenerationRef.current === surfaceGeneration
      && knowledgeEntriesRequestRef.current === requestId;
    void Promise.resolve().then(async () => {
      if (!isCurrent()) return;
      setKnowledgeEntriesLoading(true);
      setKnowledgeEntriesError(null);
      try {
        const nextEntries = await listAllKnowledgeEntries(knowledgeService);
        if (!isCurrent()) return;
        knowledgeEntriesRef.current = nextEntries;
        knowledgeEntriesLoadedRef.current = true;
        setKnowledgeEntries(nextEntries);
        setKnowledgeEntriesLoaded(true);
        setDraftSourceIds((current) => {
          const availableIds = new Set(nextEntries.map((entry) => entry.id));
          const next = current.filter((sourceId) => availableIds.has(sourceId));
          return next.length === current.length ? current : next;
        });
        setKnowledgeEntriesLoading(false);
      } catch (error) {
        if (!isCurrent()) return;
        knowledgeEntriesRef.current = [];
        knowledgeEntriesLoadedRef.current = false;
        setKnowledgeEntriesLoading(false);
        setKnowledgeEntriesError(errorStatus(error) === 403 ? "没有知识库访问权限" : "知识条目加载失败");
      }
    });
    return () => {
      if (knowledgeEntriesRequestRef.current === requestId) knowledgeEntriesRequestRef.current += 1;
    };
  }, [knowledgeService, organizationId, surface]);

  const loadMessages = useCallback(async (
    sessionId: string,
    requestOrganizationId = organizationIdRef.current,
    surfaceGeneration = surfaceGenerationRef.current,
    requestId = ++messagesRequestRef.current,
  ) => {
    const response = await service.getMessages(sessionId);
    if (!mountedRef.current || organizationIdRef.current !== requestOrganizationId || surfaceGenerationRef.current !== surfaceGeneration || messagesRequestRef.current !== requestId || selectedIdRef.current !== sessionId) {
      return false;
    }
    setMessages(items(response).map(mapMessage));
    return true;
  }, [service]);
  const loadSessions = useCallback(async () => {
    if (organizationId === null) { setStatus("forbidden"); setErrorMessage("没有会话访问权限"); return; }
    const requestOrganizationId = organizationId;
    const surfaceGeneration = surfaceGenerationRef.current;
    const requestId = ++sessionsRequestRef.current;
    const messagesRequestId = ++messagesRequestRef.current;
    const isCurrent = () => mountedRef.current && organizationIdRef.current === requestOrganizationId && surfaceGenerationRef.current === surfaceGeneration && sessionsRequestRef.current === requestId;
    setStatus("loading"); setErrorMessage(null);
    try {
      const cached = cache.get<Session[]>(requestOrganizationId, cacheKey);
      const next = cached ?? items(await service.listSessions({ surface })).map((item, index) => mapSession(item, index, surface));
      if (!isCurrent()) return;
      if (!cached) cache.set(requestOrganizationId, cacheKey, next);
      setSessions(next);
      const currentSelectedId = selectedIdRef.current;
      const nextId = next.some((session) => session.id === currentSelectedId) ? currentSelectedId : next[0]?.id ?? null;
      const nextSession = next.find((session) => session.id === nextId);
      selectedIdRef.current = nextId;
      setSelectedId(nextId);
      if (surface === "knowledge") {
        const draft = scopeDraft(nextSession, knowledgeEntriesRef.current, knowledgeEntriesLoadedRef.current);
        setScopeMode(draft.mode);
        setDraftSourceIds(draft.sourceIds);
        setScopeError(null);
      }
      if (nextId) {
        const loaded = await loadMessages(nextId, requestOrganizationId, surfaceGeneration, messagesRequestId);
        if (!loaded || !isCurrent()) return;
      } else {
        if (!isCurrent()) return;
        setMessages([]);
      }
      if (!isCurrent()) return;
      setStatus(next.length ? "success" : "empty");
    } catch (error) {
      if (!isCurrent()) return;
      selectedIdRef.current = null;
      setSelectedId(null);
      setScopeMode("none");
      setDraftSourceIds([]);
      setStatus(errorStatus(error) === 403 ? "forbidden" : "error"); setErrorMessage(messageForError(error)); setSessions([]); setMessages([]);
    }
  }, [cache, cacheKey, loadMessages, organizationId, service, surface]);
  useEffect(() => { const timer = window.setTimeout(() => void loadSessions(), 0); return () => window.clearTimeout(timer); }, [loadSessions]);

  async function selectSession(sessionId: string) {
    const requestOrganizationId = organizationIdRef.current;
    if (requestOrganizationId === null || scopePending || actionPending !== null) return;
    if (selectedIdRef.current === sessionId) return;
    streamGenerationRef.current += 1;
    attachmentRequestRef.current += 1;
    citationPreviewRequestRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    setSending(false);
    setAttachments([]);
    setAttachmentPending(false);
    setAttachmentError(null);
    setScopePending(false);
    setScopeError(null);
    setCitationPreview(null);
    setCitationPreviewLoading(false);
    setCitationPreviewError(null);
    setMessages([]);
    const surfaceGeneration = surfaceGenerationRef.current;
    const requestId = ++messagesRequestRef.current;
    const isCurrent = () => mountedRef.current && organizationIdRef.current === requestOrganizationId && surfaceGenerationRef.current === surfaceGeneration && messagesRequestRef.current === requestId && selectedIdRef.current === sessionId;
    if (surface === "knowledge") {
      const draft = scopeDraft(sessions.find((session) => session.id === sessionId), knowledgeEntriesRef.current, knowledgeEntriesLoadedRef.current);
      setScopeMode(draft.mode);
      setDraftSourceIds(draft.sourceIds);
      setScopeError(null);
    }
    selectedIdRef.current = sessionId;
    setSelectedId(sessionId); setErrorMessage(null); setStatus("loading");
    try {
      const loaded = await loadMessages(sessionId, requestOrganizationId, surfaceGeneration, requestId);
      if (!loaded || !isCurrent()) return;
      setStatus("success");
    } catch (error) {
      if (!isCurrent()) return;
      selectedIdRef.current = null;
      setSelectedId(null);
      setScopeMode("none");
      setDraftSourceIds([]);
      setMessages([]);
      setStatus("error"); setErrorMessage(messageForError(error));
    }
  }
  function switchSurface(nextSurface: ChatSurface) {
    if (nextSurface === surface || scopePending) return;
    surfaceGenerationRef.current += 1;
    sessionsRequestRef.current += 1;
    messagesRequestRef.current += 1;
    createRequestRef.current += 1;
    streamGenerationRef.current += 1;
    attachmentRequestRef.current += 1;
    knowledgeEntriesRequestRef.current += 1;
      citationPreviewRequestRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    setSending(false);
    setAttachments([]);
    setAttachmentPending(false);
    setAttachmentError(null);
    setActionPending(null);
    knowledgeEntriesRef.current = [];
    knowledgeEntriesLoadedRef.current = false;
    setKnowledgeEntries([]);
    setKnowledgeEntriesLoading(nextSurface === "knowledge" && organizationId !== null);
    setKnowledgeEntriesLoaded(false);
    setKnowledgeEntriesError(null);
    setScopeMode("none");
    setDraftSourceIds([]);
    setScopePending(false);
    setScopeError(null);
    setCitationPreview(null);
    setCitationPreviewLoading(false);
    setCitationPreviewError(null);
    selectedIdRef.current = null;
    setSelectedId(null);
    setSessions([]);
    setMessages([]);
    setErrorMessage(null);
    setStatus(organizationId === null ? "forbidden" : "loading");
    setSurface(nextSurface);
  }
  async function createSession() {
    const requestOrganizationId = organizationIdRef.current;
    if (requestOrganizationId === null || status === "loading" || scopePending || attachmentPending || actionPending !== null) return;
    const requestSurface = surface;
    const requestCacheKey = [...cacheKey];
    const surfaceGeneration = surfaceGenerationRef.current;
    const requestId = ++createRequestRef.current;
    const isCurrent = () => mountedRef.current && organizationIdRef.current === requestOrganizationId && surfaceGenerationRef.current === surfaceGeneration && createRequestRef.current === requestId;
    const canUseRequestOrganization = () => mountedRef.current && organizationIdRef.current === requestOrganizationId;
    streamGenerationRef.current += 1;
    attachmentRequestRef.current += 1;
    scopeRequestRef.current += 1;
    citationPreviewRequestRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    setSending(false);
    setAttachments([]);
    setAttachmentPending(false);
    setAttachmentError(null);
    setScopePending(false);
    setScopeError(null);
    setCitationPreview(null);
    setCitationPreviewLoading(false);
    setCitationPreviewError(null);
    setActionPending("create"); setErrorMessage(null);
    let nextForCache: Session[] | null = null;
    try {
      let created = mapSession(await service.createSession({ surface: requestSurface, title: "新会话" }), sessions.length, requestSurface);
      if (requestSurface === "knowledge") {
        if (!canUseRequestOrganization()) return;
        try {
          await service.setKnowledgeScope(created.id, { mode: "all_visible", source_ids: [] });
        } catch {
          if (!canUseRequestOrganization()) return;
          try {
            await service.deleteSession(created.id);
          } catch {
            throw new Error("知识范围初始化失败；会话清理未完成，请刷新会话列表");
          }
          throw new Error("知识范围初始化失败");
        }
        created = { ...created, knowledge_scope: "all_visible", source_ids: [] };
      }
      if (!isCurrent()) return;
      const next = [...sessions, created]; setSessions(next); selectedIdRef.current = created.id; setSelectedId(created.id); setMessages([]); setStatus("success");
      if (requestSurface === "knowledge") {
        setScopeMode(created.knowledge_scope);
        setDraftSourceIds([...created.source_ids]);
        setScopeError(null);
      }
      nextForCache = next;
    } catch (error) {
      if (isCurrent()) setErrorMessage(error instanceof Error && error.message.startsWith("知识范围初始化失败") ? error.message : "新建会话失败");
    }
    finally {
      cache.invalidateOrganization(requestOrganizationId);
      if (isCurrent()) {
        if (nextForCache) cache.set(requestOrganizationId, requestCacheKey, nextForCache);
        setActionPending(null);
      }
    }
  }
  function toggleKnowledgeSource(sourceId: number, checked: boolean) {
    setScopeError(null);
    if (checked) {
      if (draftSourceIds.includes(sourceId)) return;
      if (draftSourceIds.length >= 50) {
        setScopeError("最多选择 50 条知识");
        return;
      }
      setDraftSourceIds([...draftSourceIds, sourceId]);
      return;
    }
    setDraftSourceIds(draftSourceIds.filter((id) => id !== sourceId));
  }
  async function uploadAttachments(fileList: FileList | null) {
    const files = fileList ? Array.from(fileList).slice(0, Math.max(0, 5 - attachments.length)) : [];
    if (!files.length || attachmentPending || organizationIdRef.current === null || !selectedIdRef.current) return;
    const requestOrganizationId = organizationIdRef.current;
    const requestSurface = surface;
    const requestSessionId = selectedIdRef.current;
    const requestId = ++attachmentRequestRef.current;
    const isCurrent = () => mountedRef.current
      && organizationIdRef.current === requestOrganizationId
      && surface === requestSurface
      && selectedIdRef.current === requestSessionId
      && attachmentRequestRef.current === requestId;
    setAttachmentPending(true);
    setAttachmentError(null);
    try {
      const uploaded: ChatAttachment[] = [];
      for (const file of files) {
        const form = new FormData();
        form.append("file", file);
        const payload = asObject(await service.prepareAttachment(form));
        const content = readString(payload.content);
        if (!isCurrent()) return;
        if (!content) throw new Error("附件内容为空");
        uploaded.push({ title: readString(payload.title, file.name), content });
      }
      if (isCurrent()) setAttachments((current) => [...current, ...uploaded].slice(0, 5));
    } catch {
      if (isCurrent()) setAttachmentError("附件上传失败");
    } finally {
      if (isCurrent()) setAttachmentPending(false);
    }
  }
  function removeAttachment(index: number) {
    setAttachments((current) => current.filter((_attachment, attachmentIndex) => attachmentIndex !== index));
  }
  async function applyKnowledgeScope() {
    const requestOrganizationId = organizationIdRef.current;
    if (surface !== "knowledge" || requestOrganizationId === null || !selectedId || scopePending || sending || actionPending !== null) return;
    if (scopeMode === "none" || (scopeMode === "selected" && draftSourceIds.length === 0)) return;
    if (scopeMode === "selected" && !knowledgeEntriesLoaded) return;
    const requestSessionId = selectedId;
    const requestSurfaceGeneration = surfaceGenerationRef.current;
    const requestCacheKey = [...cacheKey];
    const requestId = ++scopeRequestRef.current;
    const confirmedSession = sessions.find((session) => session.id === requestSessionId);
    if (!confirmedSession) return;
    const sourceIds = scopeMode === "selected"
      ? draftSourceIds.filter((sourceId) => knowledgeEntries.some((entry) => entry.id === sourceId))
      : [];
    if (scopeMode === "selected" && sourceIds.length === 0) return;
    const isRequestActive = () => mountedRef.current && scopeRequestRef.current === requestId;
    const isSameContext = () => isRequestActive()
      && organizationIdRef.current === requestOrganizationId
      && surfaceGenerationRef.current === requestSurfaceGeneration;
    const isCurrent = () => isSameContext()
      && selectedIdRef.current === requestSessionId;
    setScopePending(true);
    setScopeError(null);
    try {
      const scopeRequest = scopeMode === "selected"
        ? { mode: "selected" as const, source_ids: sourceIds }
        : { mode: scopeMode, source_ids: [] as [] };
      await service.setKnowledgeScope(requestSessionId, scopeRequest);
      if (!isRequestActive()) return;
      const next = sessions.map((session) => session.id === requestSessionId
        ? { ...session, knowledge_scope: scopeMode, source_ids: sourceIds }
        : session);
      cache.set(requestOrganizationId, requestCacheKey, next);
      if (isSameContext()) setSessions(next);
      if (isCurrent()) {
        setScopeMode(scopeMode);
        setDraftSourceIds(sourceIds);
        setScopeError(null);
      }
    } catch {
      if (!isCurrent()) return;
      const restoredDraft = scopeDraft(confirmedSession, knowledgeEntriesRef.current, knowledgeEntriesLoadedRef.current);
      setScopeMode(confirmedSession.knowledge_scope);
      setDraftSourceIds(restoredDraft.sourceIds);
      setScopeError("知识范围保存失败");
    } finally {
      if (isSameContext()) setScopePending(false);
    }
  }
  async function sendMessage(contentOverride?: string, clientMessageId?: string, attachmentsOverride?: ChatAttachment[]) {
    const content = (contentOverride ?? composer).trim(); if (!content || !selectedId || status === "loading" || sending || actionPending !== null || attachmentPending || knowledgeSendingBlocked) return;
    const requestOrganizationId = organizationIdRef.current;
    if (requestOrganizationId === null) return;
    const requestSurfaceGeneration = surfaceGenerationRef.current;
    const requestSessionId = selectedId;
    const attemptId = ++clientMessageSequenceRef.current;
    const userMessageId = clientMessageId ?? `m_${attemptId}`;
    const messageAttachments = [...(attachmentsOverride ?? attachments)];
    const assistant: Message = { id: `pending-${userMessageId}-${attemptId}`, role: "assistant", content: "", status: "streaming" };
    setComposer(""); setAttachments([]); setAttachmentError(null); setSending(true); setErrorMessage(null); setMessages((current) => [...current, { id: `local-${userMessageId}-${attemptId}`, role: "user", content, clientMessageId: userMessageId, attachments: messageAttachments }, assistant]);
    const controller = new AbortController(); abortRef.current = controller;
    const streamGeneration = ++streamGenerationRef.current;
    const isCurrentStream = () => mountedRef.current && organizationIdRef.current === requestOrganizationId && surfaceGenerationRef.current === requestSurfaceGeneration && selectedIdRef.current === requestSessionId && streamGenerationRef.current === streamGeneration;
    const ownsCurrentController = () => isCurrentStream() && abortRef.current === controller;
    try {
      const response = await stream.sendMessageStream(requestSessionId, { content, attachments: messageAttachments, client_message_id: userMessageId, links: [], metadata: { mode: "auto", command_mode: true } }, { signal: controller.signal });
      if (!isCurrentStream()) return;
      let pending = "";
      const apply = (event: string, data: unknown) => {
        if (!isCurrentStream()) return;
        const value = asObject(data);
        setMessages((current) => isCurrentStream() ? current.map((message) => {
          if (message.id !== assistant.id) return message;
          if (event === "response.output_text.delta") return { ...message, content: message.content + readString(value.delta, readString(value.text, readString(value.content))) };
          if (event === "knowledge.context") {
            const turnId = readNumber(value.turn_id, NaN);
            const rejectedSourceCount = readNumber(value.rejected_source_count, NaN);
            return {
              ...message,
              turnId: Number.isFinite(turnId) ? turnId : undefined,
              citations: readArray(value.citations).map(mapCitation).filter((citation): citation is Citation => citation !== null),
              retrievalMode: mapRetrievalMode(value.mode),
              rejectedSourceCount: Number.isFinite(rejectedSourceCount) && rejectedSourceCount >= 0 ? rejectedSourceCount : undefined,
            };
          }
          if (event === "platform.action") return {
            ...message,
            platformAction: {
              message: readString(value.message, "平台操作已处理"),
              status: readString(value.status, "processed"),
              taskId: actionIdentifier(value.task_id),
              runId: actionIdentifier(value.run_id),
            },
          };
          if (event === "web.search.started") return { ...message, webSearchUsed: true, webSearchState: "searching" };
          if (event === "web.search.completed") {
            const sources = readArray(value.sources).map((source) => asObject(source)).filter((source) => /^https?:\/\//i.test(readString(source.url))).map((source, index) => ({ url: readString(source.url), title: readString(source.title, readString(source.url)), published_at: readString(source.published_at), searched_at: readString(source.searched_at), ordinal: index }));
            return { ...message, webSearchUsed: true, webEvidence: sources, webSearchState: sources.length ? "sourced" : "empty" };
          }
          if (event === "web.search.failed") return { ...message, webSearchUsed: true, webSearchFailed: true, webSearchState: "failed" };
          if (event === "response.completed") return { ...message, status: "completed" };
          if (event === "response.failed" || event === "response.cancelled" || event === "upstream.disconnected") return { ...message, status: event === "response.failed" ? "failed" : "interrupted", content: message.content || (event === "response.failed" ? "生成失败，请稍后重试。" : "生成中断，请稍后重试。") };
          return message;
        }) : current);
      };
      if (response.body?.getReader) {
        const reader = response.body.getReader(); const decoder = new TextDecoder();
        while (true) { const chunk = await reader.read(); if (!isCurrentStream()) return; if (chunk.done) break; pending += decoder.decode(chunk.value, { stream: true }); const parts = pending.split(/\r?\n\r?\n/); pending = parts.pop() ?? ""; for (const frame of parseSseFrames(parts.join("\n\n"))) apply(frame.event, frame.data); }
        pending += decoder.decode();
      } else if (response.text) pending = await response.text();
      for (const frame of parseSseFrames(`${pending}\n\n`)) apply(frame.event, frame.data);
      if (!isCurrentStream()) return;
      setMessages((current) => isCurrentStream() ? current.map((message) => message.id === assistant.id && message.status === "streaming" ? { ...message, status: "interrupted", content: message.content || "生成中断，请稍后重试。" } : message) : current);
    } catch {
      if (ownsCurrentController()) {
        setMessages((current) => current.map((message) => message.id === assistant.id ? { ...message, status: controller.signal.aborted ? "interrupted" : "failed", content: message.content || (controller.signal.aborted ? "生成中断，请稍后重试。" : "消息发送失败") } : message));
        setErrorMessage(controller.signal.aborted ? "生成已停止" : "消息发送失败");
      }
    } finally {
      if (ownsCurrentController()) {
        setSending(false);
        abortRef.current = null;
      }
    }
  }
  async function retryMessage(message: Message) {
    const previous = messages[messages.findIndex((item) => item.id === message.id) - 1];
    if (previous?.role === "user" && previous.clientMessageId) { void sendMessage(previous.content, previous.clientMessageId, previous.attachments); }
  }
  async function openCitationPreview(message: Message, citation: Citation, trigger: HTMLButtonElement) {
    const requestOrganizationId = organizationIdRef.current;
    const requestSessionId = selectedIdRef.current;
    if (surface !== "knowledge" || requestOrganizationId === null || requestSessionId === null || message.turnId === undefined) return;
    const requestSurfaceGeneration = surfaceGenerationRef.current;
    const requestId = ++citationPreviewRequestRef.current;
    citationTriggerRef.current = trigger;
    const isCurrent = () => mountedRef.current
      && organizationIdRef.current === requestOrganizationId
      && surfaceGenerationRef.current === requestSurfaceGeneration
      && selectedIdRef.current === requestSessionId
      && citationPreviewRequestRef.current === requestId;
    setCitationPreview(null);
    setCitationPreviewError(null);
    setCitationPreviewLoading(true);
    try {
      const resolved = asObject(await knowledgeService.resolveCitation(String(message.turnId) as `${number}`, citation.ordinal));
      if (!isCurrent()) return;
      const entryId = readNumber(resolved.entry_id, NaN);
      if (!Number.isFinite(entryId)) throw new Error("Citation entry is unavailable");
      const preview = asObject(await knowledgeService.previewContent(entryId));
      if (!isCurrent()) return;
      const sourceLocator = readString(resolved.source_locator);
      setCitationPreview({
        title: readString(preview.title, readString(resolved.title, citation.title)),
        content: readString(preview.content).trim(),
        sourceLocator: sourceLocator || undefined,
      });
    } catch (error) {
      if (!isCurrent()) return;
      setCitationPreview(null);
      setCitationPreviewError(errorStatus(error) === 403 ? "没有知识来源访问权限" : "知识来源当前不可用");
    } finally {
      if (isCurrent()) setCitationPreviewLoading(false);
    }
  }
  function closeCitationPreview() {
    citationPreviewRequestRef.current += 1;
    setCitationPreview(null);
    setCitationPreviewLoading(false);
    setCitationPreviewError(null);
    citationTriggerRef.current?.focus();
  }

  return <main aria-labelledby="chat-title" className="page-view chat-page">
    <header className="page-header"><div><h1 id="chat-title">会话</h1><p>与企业 AI 对话并查看历史消息。</p></div><div aria-label="会话模式" role="group"><button aria-pressed={surface === "agent"} disabled={scopePending} onClick={() => switchSurface("agent")} type="button">普通对话</button><button aria-pressed={surface === "knowledge"} disabled={scopePending} onClick={() => switchSurface("knowledge")} type="button">知识问答</button></div><button disabled={organizationId === null || status === "loading" || actionPending !== null || scopePending || attachmentPending} onClick={() => void createSession()} type="button">新建会话</button></header>
    {errorMessage ? <p className="error-message" role="alert">{errorMessage}</p> : null}
    {status === "loading" ? <p>正在加载会话</p> : null}
    {status === "empty" ? <p>暂无会话，请新建一个会话。</p> : null}
    {surface === "knowledge" ? <section aria-labelledby="knowledge-scope-title">
      <h2 id="knowledge-scope-title">知识范围</h2>
      {knowledgeEntriesError ? <p className="error-message" role="alert">{knowledgeEntriesError}</p> : null}
      <fieldset disabled={!selectedId || scopePending || sending || actionPending !== null}>
        <legend>知识范围模式</legend>
        <label><input checked={scopeMode === "all_visible"} name="knowledge-scope" onChange={() => { setScopeMode("all_visible"); setScopeError(null); }} type="radio" />全部可见知识</label>
        <label><input checked={scopeMode === "selected"} name="knowledge-scope" onChange={() => { setScopeMode("selected"); setScopeError(null); }} type="radio" />指定知识</label>
      </fieldset>
      {scopeMode === "selected" ? <fieldset disabled={!selectedId || scopePending || sending || actionPending !== null}>
        <legend>知识条目</legend>
        {knowledgeEntriesLoading ? <p>知识条目加载中</p> : knowledgeEntries.length ? <ul>{knowledgeEntries.map((entry) => <li key={entry.id}><label><input checked={draftSourceIds.includes(entry.id)} onChange={(event) => toggleKnowledgeSource(entry.id, event.currentTarget.checked)} type="checkbox" />{entry.title}</label></li>)}</ul> : <p>暂无可选知识</p>}
      </fieldset> : null}
      {scopeMode === "selected" && draftSourceIds.length === 0 ? <p>请至少选择一条知识</p> : null}
      {scopeError ? <p className="error-message" role="alert">{scopeError}</p> : null}
      <button disabled={!selectedId || scopePending || sending || actionPending !== null || scopeMode === "none" || (scopeMode === "selected" && (!knowledgeEntriesLoaded || draftSourceIds.length === 0))} onClick={() => void applyKnowledgeScope()} type="button">{scopePending ? "应用中" : "应用知识范围"}</button>
    </section> : null}
    <section aria-label="会话工作台" className="chat-shell">
      <aside aria-label="会话列表"><h2>历史会话</h2>{sessions.length ? <ul>{sessions.map((session) => <li key={session.id}><button aria-pressed={selectedId === session.id} disabled={scopePending || actionPending !== null} onClick={() => void selectSession(session.id)} type="button">{session.title}</button></li>)}</ul> : <p>暂无历史会话</p>}</aside>
      <section aria-label="消息记录" className="chat-transcript"><h2>{sessions.find((session) => session.id === selectedId)?.title ?? "消息记录"}</h2>{messages.length ? messages.map((message, index) => { const previous = messages[index - 1]; const freshnessNotice = message.role === "assistant" && previous?.role === "user" ? getFreshnessNotice({ userContent: previous.content, answer: { content: message.content, status: message.status, webEvidence: message.webEvidence }, webSearchUsed: message.webSearchUsed, webSearchFailed: message.webSearchFailed }) : ""; const showKnowledgeEvidence = surface === "knowledge" && message.role === "assistant" && (message.citations?.length || message.retrievalMode || (message.rejectedSourceCount ?? 0) > 0); return <article key={message.id} data-role={message.role}><strong>{message.role === "user" ? "我" : "AI"}</strong>{message.role === "assistant" ? <div dangerouslySetInnerHTML={{ __html: renderSafeAssistantMarkdown(message.content || (message.status === "streaming" ? "正在生成..." : "")) }} /> : <p>{message.content}</p>}{message.role === "assistant" ? renderPlatformAction(message.platformAction) : null}{message.role === "assistant" ? renderWebEvidence(message) : null}{showKnowledgeEvidence ? <div className="chat-references chat-knowledge-sources" data-testid="chat-knowledge-sources"><span className="ref-label">知识来源</span>{message.turnId === undefined ? message.citations?.map((citation) => <span key={`${message.id}-${citation.ordinal}`}>{citation.title}</span>) : message.citations?.map((citation) => <button key={`${message.id}-${citation.ordinal}`} onClick={(event) => void openCitationPreview(message, citation, event.currentTarget)} type="button">{citation.title}</button>)}{message.turnId === undefined && message.citations?.length ? <span>来源详情当前不可用</span> : null}{message.retrievalMode ? <span>检索方式：{retrievalModeLabel(message.retrievalMode)}</span> : null}{(message.rejectedSourceCount ?? 0) > 0 ? <span>有 {message.rejectedSourceCount} 个来源当前不可用</span> : null}</div> : null}{freshnessNotice ? <div className="chat-evidence-notice" data-testid="freshness-evidence-notice" role="status">{freshnessNotice}</div> : null}{message.status && message.role === "assistant" ? <small>{message.status === "streaming" ? "生成中" : message.status === "completed" ? "已完成" : message.status === "interrupted" ? "已中断" : "失败"}</small> : null}{message.status && ["failed", "interrupted"].includes(message.status) ? <button onClick={() => void retryMessage(message)} type="button">重试</button> : null}</article>; }) : <p>选择会话后开始对话。</p>}</section>
    </section>
    {citationPreviewLoading ? <section aria-label="知识来源预览" aria-live="polite" className="citation-preview" role="status"><p>知识来源加载中</p><button aria-label="关闭来源预览" onClick={closeCitationPreview} type="button">关闭</button></section> : null}
    {citationPreviewError ? <p className="error-message" role="alert">{citationPreviewError}</p> : null}
    {citationPreview ? <section aria-labelledby="citation-preview-title" className="citation-preview" ref={citationPreviewRef} tabIndex={-1}><header><h2 id="citation-preview-title">{citationPreview.title}</h2><button aria-label="关闭来源预览" onClick={closeCitationPreview} type="button">关闭</button></header><p>{citationPreview.content || "暂无可预览正文"}</p>{citationPreview.sourceLocator ? <p>{citationPreview.sourceLocator}</p> : null}</section> : null}
    <form aria-label="发送消息" onSubmit={(event) => { event.preventDefault(); void sendMessage(); }}>
      <label htmlFor="chat-composer">消息</label>
      {surface === "agent" ? <label className="chat-attachment-control">添加附件<input aria-label="添加附件" disabled={composerDisabled || attachments.length >= 5} multiple onChange={(event) => { void uploadAttachments(event.currentTarget.files); event.currentTarget.value = ""; }} type="file" /></label> : null}
      {attachments.length ? <ul aria-label="待发送附件" className="chat-attachment-list">{attachments.map((attachment, index) => <li key={`${attachment.title}-${index}`}><span>{attachment.title}</span><button aria-label={`移除附件 ${attachment.title}`} disabled={composerDisabled} onClick={() => removeAttachment(index)} type="button">移除</button></li>)}</ul> : null}
      {attachmentPending ? <p role="status">附件上传中</p> : null}
      {attachmentError ? <p className="error-message" role="alert">{attachmentError}</p> : null}
      <textarea disabled={composerDisabled} id="chat-composer" onChange={(event) => setComposer(event.currentTarget.value)} value={composer} />
      <button disabled={composerDisabled || !composer.trim()} type="submit">{sending ? "发送中" : "发送"}</button>
      {sending ? <button onClick={() => abortRef.current?.abort()} type="button">停止</button> : null}
      {surface === "knowledge" && selectedId && !persistedKnowledgeScopeReady ? <p>请先设置知识范围</p> : null}
    </form>
  </main>;
}
