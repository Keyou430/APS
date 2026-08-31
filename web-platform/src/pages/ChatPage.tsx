import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChatService } from "../api/services/chatService";
import { parseSseFrames, type ChatStreamService } from "../api/services/chatStream";
import type { PipelineService, PipelineTaskRequest } from "../api/services/pipelineService";
import { getFreshnessNotice } from "../app/chatEvidence";
import { renderSafeAssistantMarkdown } from "../security/safeMarkdown";
import { asObject, errorStatus, readArray, readNumber, readString, type PageCache } from "./pageUtils";

type ChatPageProps = { cache: PageCache; organizationId: number | null; pipeline: PipelineService; service: ChatService; stream: ChatStreamService };
type PageStatus = "loading" | "empty" | "error" | "forbidden" | "success";
type Session = { id: string; title: string; createdAt: string; updatedAt: string };
type WebSource = { url: string; title: string; published_at?: string; searched_at?: string; ordinal?: number };
type WebSearchState = "searching" | "sourced" | "empty" | "failed";
type PlatformAction = { message: string; status: string; taskId?: string; runId?: string; draft?: PipelineTaskRequest; runNow?: boolean; pending?: boolean; error?: string };
type Message = { id: string; role: "user" | "assistant"; content: string; clientMessageId?: string; status?: "streaming" | "completed" | "failed" | "interrupted"; references?: unknown[]; webEvidence?: WebSource[]; webSearchState?: WebSearchState; webSearchUsed?: boolean; webSearchFailed?: boolean; platformAction?: PlatformAction };

function mapSession(value: unknown, index: number): Session {
  const item = asObject(value);
  const numericId = readNumber(item.id, NaN);
  const id = Number.isFinite(numericId)
    ? String(numericId)
    : readString(item.id, `session-${index + 1}`);
  return { id, title: readString(item.title, "新会话"), createdAt: readString(item.created_at, readString(item.createdAt)), updatedAt: readString(item.updated_at, readString(item.updatedAt)) };
}
function mapMessage(value: unknown, index: number): Message {
  const item = asObject(value);
  const role = readString(item.role, "assistant") === "user" ? "user" : "assistant";
  const webEvidence = readArray(item.web_sources).map((source) => asObject(source)).filter((source) => /^https?:\/\//i.test(readString(source.url))).map((source, ordinal) => ({
    url: readString(source.url), title: readString(source.title, readString(source.url)), published_at: readString(source.published_at), searched_at: readString(source.searched_at), ordinal,
  }));
  return { id: readString(item.id, `message-${index + 1}`), role, content: readString(item.content), status: role === "assistant" ? "completed" : undefined, references: readArray(item.citations ?? item.references), webEvidence, webSearchState: webEvidence.length ? "sourced" : undefined };
}
function items(value: unknown) { const item = asObject(value); return Array.isArray(value) ? value : readArray(item.items); }
function messageForError(error: unknown) { return errorStatus(error) === 403 ? "没有会话访问权限" : "聊天会话加载失败"; }
function messageForSendError(error: unknown) {
  if (errorStatus(error) === 429) return "运行额度被未完成会话占用，请等待会话结束后重试。";
  return error instanceof Error ? error.message : "消息发送失败";
}
function actionIdentifier(value: unknown) { return typeof value === "string" || typeof value === "number" ? String(value) : undefined; }
function createClientMessageId() { return `m_${Date.now()}`; }

function renderPlatformAction(action: PlatformAction | undefined, onConfirm: () => void, onCancel: () => void) {
  if (!action) return null;
  const identifiers = [action.taskId ? `任务 #${action.taskId}` : "", action.runId ? `运行 #${action.runId}` : ""].filter(Boolean).join("，");
  return <div className="chat-evidence-notice" data-testid="chat-platform-action" role="status">
    <div>平台操作：{action.message}{identifiers ? `（${identifiers}）` : ""}</div>
    {action.draft ? <div className="chat-platform-draft">
      <strong>{readString(action.draft.title, "定时任务")}</strong>
      <span>{[readString(action.draft.schedule), readString(action.draft.timezone)].filter(Boolean).join(" · ")}</span>
      <div className="chat-platform-draft-actions">
        <button disabled={action.pending} onClick={onConfirm} type="button">{action.pending ? "创建中" : "确认创建"}</button>
        <button disabled={action.pending} onClick={onCancel} type="button">取消</button>
      </div>
    </div> : null}
    {action.error ? <div className="error-message" role="alert">{action.error}</div> : null}
  </div>;
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

export function ChatPage({ cache, organizationId, pipeline, service, stream }: ChatPageProps) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [status, setStatus] = useState<PageStatus>(organizationId === null ? "forbidden" : "loading");
  const [errorMessage, setErrorMessage] = useState<string | null>(organizationId === null ? "没有会话访问权限" : null);
  const [composer, setComposer] = useState("");
  const [sending, setSending] = useState(false);
  const [actionPending, setActionPending] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const activeRunIdRef = useRef<string | null>(null);
  const stopPromiseRef = useRef<Promise<unknown> | null>(null);
  const selectedIdRef = useRef<string | null>(null);
  const cacheKey = useMemo(() => ["chat", "sessions"], []);

  const loadMessages = useCallback(async (sessionId: string) => {
    const response = await service.getMessages(sessionId);
    setMessages(items(response).map(mapMessage));
  }, [service]);
  const loadSessions = useCallback(async () => {
    if (organizationId === null) { setStatus("forbidden"); setErrorMessage("没有会话访问权限"); return; }
    setStatus("loading"); setErrorMessage(null);
    try {
      const cached = cache.get<Session[]>(organizationId, cacheKey);
      const next = cached ?? items(await service.listSessions({ surface: "agent" })).map(mapSession);
      if (!cached) cache.set(organizationId, cacheKey, next);
      setSessions(next);
      const currentSelectedId = selectedIdRef.current;
      const nextId = next.some((session) => session.id === currentSelectedId) ? currentSelectedId : next[0]?.id ?? null;
      selectedIdRef.current = nextId;
      setSelectedId(nextId);
      if (nextId) await loadMessages(nextId);
      else setMessages([]);
      setStatus(next.length ? "success" : "empty");
    } catch (error) { setStatus(errorStatus(error) === 403 ? "forbidden" : "error"); setErrorMessage(messageForError(error)); setSessions([]); setMessages([]); }
  }, [cache, cacheKey, loadMessages, organizationId, service]);
  useEffect(() => { const timer = window.setTimeout(() => void loadSessions(), 0); return () => window.clearTimeout(timer); }, [loadSessions]);

  async function selectSession(sessionId: string) {
    selectedIdRef.current = sessionId;
    setSelectedId(sessionId); setErrorMessage(null); setStatus("loading");
    try { await loadMessages(sessionId); setStatus("success"); } catch (error) { setStatus("error"); setErrorMessage(messageForError(error)); }
  }
  async function createSession() {
    setActionPending("create"); setErrorMessage(null);
    try {
      const created = mapSession(await service.createSession({ surface: "agent", title: "新会话" }), sessions.length);
      const next = [...sessions, created]; setSessions(next); selectedIdRef.current = created.id; setSelectedId(created.id); setMessages([]); setStatus("success");
      if (organizationId !== null) { cache.invalidateOrganization(organizationId); cache.set(organizationId, cacheKey, next); }
    } catch (error) { setErrorMessage(error instanceof Error ? error.message : "新建会话失败"); }
    finally { setActionPending(null); }
  }
  async function sendMessage(contentOverride?: string, clientMessageId?: string) {
    const content = (contentOverride ?? composer).trim(); if (!content || !selectedId || sending) return;
    const userMessageId = clientMessageId ?? createClientMessageId();
    const assistant: Message = { id: `pending-${userMessageId}`, role: "assistant", content: "", status: "streaming" };
    setComposer(""); setSending(true); setErrorMessage(null); setMessages((current) => [...current, { id: `local-${userMessageId}`, role: "user", content, clientMessageId: userMessageId }, assistant]);
    const controller = new AbortController(); abortRef.current = controller; activeRunIdRef.current = null; stopPromiseRef.current = null;
    try {
      const response = await stream.sendMessageStream(selectedId, { content, attachments: [], client_message_id: userMessageId, links: [], metadata: { mode: "auto", command_mode: true } }, { signal: controller.signal });
      let pending = "";
      const apply = (event: string, data: unknown) => {
        const value = asObject(data);
        if (event === "run.created") activeRunIdRef.current = readString(value.run_id) || null;
        setMessages((current) => current.map((message) => {
          if (message.id !== assistant.id) return message;
          if (event === "response.output_text.delta") return { ...message, content: message.content + readString(value.delta, readString(value.text, readString(value.content))) };
          if (event === "knowledge.context") return { ...message, references: readArray(value.citations ?? value.references) };
          if (event === "platform.action") {
            const draft = asObject(value.draft);
            return {
              ...message,
              platformAction: {
                message: readString(value.message, "平台操作已处理"),
                status: readString(value.status, "processed"),
                taskId: actionIdentifier(value.task_id),
                runId: actionIdentifier(value.run_id),
                draft: Object.keys(draft).length ? draft : undefined,
                runNow: value.run_now === true,
              },
            };
          }
          if (event === "web.search.started") return { ...message, webSearchUsed: true, webSearchState: "searching" };
          if (event === "web.search.completed") {
            const sources = readArray(value.sources).map((source) => asObject(source)).filter((source) => /^https?:\/\//i.test(readString(source.url))).map((source, index) => ({ url: readString(source.url), title: readString(source.title, readString(source.url)), published_at: readString(source.published_at), searched_at: readString(source.searched_at), ordinal: index }));
            return { ...message, webSearchUsed: true, webEvidence: sources, webSearchState: sources.length ? "sourced" : "empty" };
          }
          if (event === "web.search.failed") return { ...message, webSearchUsed: true, webSearchFailed: true, webSearchState: "failed" };
          if (event === "response.completed") return { ...message, status: "completed" };
          if (event === "response.failed" || event === "response.cancelled" || event === "upstream.disconnected") return { ...message, status: event === "response.failed" ? "failed" : "interrupted", content: message.content || readString(value.message, "生成中断，请稍后重试。") };
          return message;
        }));
      };
      if (response.body?.getReader) {
        const reader = response.body.getReader(); const decoder = new TextDecoder();
        while (true) { const chunk = await reader.read(); if (chunk.done) break; pending += decoder.decode(chunk.value, { stream: true }); const parts = pending.split(/\r?\n\r?\n/); pending = parts.pop() ?? ""; for (const frame of parseSseFrames(parts.join("\n\n"))) apply(frame.event, frame.data); }
        pending += decoder.decode();
      } else if (response.text) pending = await response.text();
      for (const frame of parseSseFrames(`${pending}\n\n`)) apply(frame.event, frame.data);
      setMessages((current) => current.map((message) => message.id === assistant.id && message.status === "streaming" ? { ...message, status: "interrupted", content: message.content || "生成中断，请稍后重试。" } : message));
    } catch (error) { const message = messageForSendError(error); setMessages((current) => current.map((item) => item.id === assistant.id ? { ...item, status: controller.signal.aborted ? "interrupted" : "failed", content: item.content || message } : item)); setErrorMessage(message); }
    finally {
      await stopPromiseRef.current;
      setSending(false); abortRef.current = null; activeRunIdRef.current = null; stopPromiseRef.current = null;
    }
  }
  function stopGeneration() {
    const sessionId = selectedIdRef.current;
    if (sessionId && !stopPromiseRef.current) {
      stopPromiseRef.current = service.stopRun(sessionId, activeRunIdRef.current || "active").catch(() => undefined);
    }
    abortRef.current?.abort();
  }
  async function retryMessage(message: Message) {
    const previous = messages[messages.findIndex((item) => item.id === message.id) - 1];
    if (previous?.role === "user" && previous.clientMessageId) { void sendMessage(previous.content, previous.clientMessageId); }
  }
  async function confirmPlatformAction(messageId: string) {
    const action = messages.find((message) => message.id === messageId)?.platformAction;
    if (!action?.draft || action.pending) return;
    setMessages((current) => current.map((message) => message.id === messageId ? { ...message, platformAction: { ...action, pending: true, error: undefined } } : message));
    let taskId: number | string;
    try {
      const task = await pipeline.createTask({ ...action.draft, confirmed: true });
      taskId = task.id;
    } catch (error) {
      setMessages((current) => current.map((message) => message.id === messageId ? { ...message, platformAction: { ...action, pending: false, error: error instanceof Error ? error.message : "创建任务失败" } } : message));
      return;
    }
    if (!action.runNow) {
      setMessages((current) => current.map((message) => message.id === messageId ? { ...message, platformAction: { message: "已创建定时任务。", status: "created", taskId: String(taskId) } } : message));
      return;
    }
    try {
      const run = await pipeline.runTask(taskId);
      setMessages((current) => current.map((message) => message.id === messageId ? { ...message, platformAction: { message: "已创建定时任务，本次立即执行已入队。", status: readString(run.status, "queued"), taskId: String(taskId), runId: String(run.id) } } : message));
    } catch (error) {
      setMessages((current) => current.map((message) => message.id === messageId ? { ...message, platformAction: { message: "已创建定时任务，但立即执行失败。", status: "failed", taskId: String(taskId), error: error instanceof Error ? error.message : "立即执行失败" } } : message));
    } finally {
      pipeline.releaseRunIntent(String(taskId));
    }
  }
  function cancelPlatformAction(messageId: string) {
    setMessages((current) => current.map((message) => message.id === messageId ? { ...message, platformAction: { message: "已取消创建定时任务。", status: "cancelled" } } : message));
  }

  return <main aria-labelledby="chat-title" className="page-view chat-page">
    <header className="page-header"><div><h1 id="chat-title">会话</h1><p>与企业 AI 对话并查看历史消息。</p></div><button disabled={organizationId === null || actionPending !== null} onClick={() => void createSession()} type="button">新建会话</button></header>
    {errorMessage ? <p className="error-message" role="alert">{errorMessage}</p> : null}
    {status === "loading" ? <p>正在加载会话</p> : null}
    {status === "empty" ? <p>暂无会话，请新建一个会话。</p> : null}
    <section aria-label="会话工作台" className="chat-shell">
      <aside aria-label="会话列表"><h2>历史会话</h2>{sessions.length ? <ul>{sessions.map((session) => <li key={session.id}><button aria-pressed={selectedId === session.id} onClick={() => void selectSession(session.id)} type="button">{session.title}</button></li>)}</ul> : <p>暂无历史会话</p>}</aside>
      <section aria-label="消息记录" className="chat-transcript"><h2>{sessions.find((session) => session.id === selectedId)?.title ?? "消息记录"}</h2>{messages.length ? messages.map((message, index) => { const previous = messages[index - 1]; const freshnessNotice = message.role === "assistant" && previous?.role === "user" ? getFreshnessNotice({ userContent: previous.content, answer: { content: message.content, status: message.status, webEvidence: message.webEvidence }, webSearchUsed: message.webSearchUsed, webSearchFailed: message.webSearchFailed }) : ""; return <article key={message.id} data-role={message.role}><strong>{message.role === "user" ? "我" : "AI"}</strong>{message.role === "assistant" ? <div dangerouslySetInnerHTML={{ __html: renderSafeAssistantMarkdown(message.content || (message.status === "streaming" ? "正在生成..." : "")) }} /> : <p>{message.content}</p>}{message.role === "assistant" ? renderPlatformAction(message.platformAction, () => void confirmPlatformAction(message.id), () => cancelPlatformAction(message.id)) : null}{message.role === "assistant" ? renderWebEvidence(message) : null}{freshnessNotice ? <div className="chat-evidence-notice" data-testid="freshness-evidence-notice" role="status">{freshnessNotice}</div> : null}{message.status && message.role === "assistant" ? <small>{message.status === "streaming" ? "生成中" : message.status === "completed" ? "已完成" : message.status === "interrupted" ? "已中断" : "失败"}</small> : null}{message.status && ["failed", "interrupted"].includes(message.status) ? <button onClick={() => void retryMessage(message)} type="button">重试</button> : null}</article>; }) : <p>选择会话后开始对话。</p>}</section>
    </section>
    <form aria-label="发送消息" onSubmit={(event) => { event.preventDefault(); void sendMessage(); }}><label htmlFor="chat-composer">消息</label><textarea disabled={!selectedId || sending} id="chat-composer" onChange={(event) => setComposer(event.currentTarget.value)} value={composer} /><button disabled={!selectedId || sending || !composer.trim()} type="submit">{sending ? "发送中" : "发送"}</button>{sending ? <button onClick={stopGeneration} type="button">停止</button> : null}</form>
  </main>;
}
