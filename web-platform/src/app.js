import { createAiMobileOverlayController } from "./app/aiMobileOverlay.js"
import { installAppShellScale } from "./app/appShellScale.js"
import { isCockpitDecisionDemoMode } from "./app/cockpitDecisionDemoMode.js"
import { getFreshnessNotice } from "./app/chatEvidence"
import { normalizeChatLink } from "./app/chatLinkContext"
import { createCustomWebsite, parseCustomWebsites } from "./app/customWebsites"

const viewStorageKey = "collab-active-view"
const taskStorageKey = "collab-workspace-tasks"
const pendingDeletesStorageKey = "collab-pending-task-deletes"
const eventStorageKey = "collab-calendar-events"
const embedStorageKey = "collab-embed-urls"
const chatSessionsStorageKey = "collab-chat-sessions"
const profileStorageKey = "collab-portal-profile"
const newsSubsStorageKey = "collab-news-subs"
const lastUserIdKey = "collab-last-user-id"
const cockpitLayoutKey = "collab-cockpit-layout"
const cockpitTaskRangeKey = "collab-cockpit-task-range"
const cockpitFavoritesKey = "collab-cockpit-favorites"
const cockpitEntriesKey = "collab-cockpit-entries"
const customWebsitesStorageKey = "collab-custom-websites"

// ── AI workbench storage keys ──────────────────────────────────
const aiFavoritesKey = "collab-ai-favorites"
const aiMemoryKey = "collab-ai-memory"
const aiTemplatesKey = "collab-ai-templates"
const aiTrashKey = "collab-ai-trash"
const aiLinksKey = "collab-ai-links"
const aiContextKey = "collab-ai-context"
const aiPanelKey = "collab-ai-panel"

// ── User-scoped localStorage helpers ──────────────────────────────
function _scopedKey(baseKey) {
  var uid = (window.App && window.App._authUserId) || null
  if (!uid) {
    // Fallback: read last-user-id marker so page-reload (before login) can
    // still find the previous session's scoped data.
    try {
      uid = window.localStorage.getItem(lastUserIdKey)
    } catch (e) {}
  }
  return uid ? baseKey + ":" + uid : baseKey
}

function _saveScoped(key, value) {
  try {
    window.localStorage.setItem(_scopedKey(key), value)
  } catch (e) {
    /* quota exceeded — degrade gracefully */
  }
}

function _loadScoped(key, fallback) {
  try {
    var raw = window.localStorage.getItem(_scopedKey(key))
    return raw !== null ? raw : fallback
  } catch (e) {
    return fallback
  }
}

function _removeScoped(key) {
  try {
    window.localStorage.removeItem(_scopedKey(key))
  } catch (e) {
    /* ignore */
  }
}

function getToken() {
  return (
    (window.App && window.App._authToken) ||
    (window.__contractAuth &&
      window.__contractAuth.getToken &&
      window.__contractAuth.getToken()) ||
    (window.__auth && window.__auth.getToken && window.__auth.getToken()) ||
    null
  )
}

function getContractAuth() {
  return window.__contractAuth || null
}

function getAppRuntimeService(name) {
  return (
    window.__agentRuntime &&
    window.__agentRuntime.services &&
    window.__agentRuntime.services[name]
  )
}

function requireAppRuntimeService(name, methodName) {
  var service = getAppRuntimeService(name)
  if (!service || !service[methodName] || !isLoggedIn()) {
    throw new Error(name + " 契约服务未初始化")
  }
  return service
}

function renderAssistantMessageContent(content) {
  var security = window.__agentRuntime && window.__agentRuntime.security
  if (security && typeof security.renderAssistantMessage === "function") {
    return security.renderAssistantMessage(content || "")
  }
  return escapeHTML(content || "").replace(/\n/g, "<br>")
}

function loadPortalPreferencesFromLocalCache() {
  try {
    var raw = _loadScoped(profileStorageKey + ":portal-preferences", "")
    return raw ? JSON.parse(raw) : null
  } catch (error) {
    return null
  }
}

function savePortalPreferencesToLocalCache(preferences) {
  try {
    _saveScoped(
      profileStorageKey + ":portal-preferences",
      JSON.stringify(preferences || {}),
    )
  } catch (error) {
    /* ignore */
  }
}

function getDashboardLayoutRevision() {
  var dashboard = state.portalDashboard || {}
  if (typeof dashboard.layoutRevision === "number") return dashboard.layoutRevision
  if (typeof dashboard.revision === "number") return dashboard.revision
  if (dashboard.layout && typeof dashboard.layout.revision === "number") {
    return dashboard.layout.revision
  }
  return null
}

function cockpitOrderToDashboardLayouts(order) {
  function mapBreakpoint(columns) {
    var width = 4
    var height = 2
    var perRow = Math.max(1, Math.floor(columns / width))
    return order.map((id, index) => ({
      i: id,
      x: (index % perRow) * width,
      y: Math.floor(index / perRow) * height,
      w: width,
      h: height,
    }))
  }
  return {
    lg: mapBreakpoint(12),
    md: mapBreakpoint(8),
    sm: mapBreakpoint(4),
  }
}

function dashboardLayoutsToCockpitOrder(layouts, fallbackOrder) {
  var lg = layouts && Array.isArray(layouts.lg) ? layouts.lg : []
  if (!lg.length) return fallbackOrder
  var positioned = lg
    .filter((item) => item && item.i)
    .slice()
    .sort((left, right) => left.y - right.y || left.x - right.x)
    .map((item) => item.i)
  var missing = fallbackOrder.filter((id) => positioned.indexOf(id) === -1)
  return positioned.concat(missing)
}

function applyDashboardLayoutResponse(layoutResponse) {
  if (!layoutResponse) return
  state.portalDashboard = {
    ...(state.portalDashboard || {}),
    layout: layoutResponse,
    layoutRevision: layoutResponse.revision,
  }
  if (layoutResponse.layouts) {
    state.cockpitKpiLayout = dashboardLayoutsToCockpitOrder(
      layoutResponse.layouts,
      state.cockpitKpiLayout,
    )
    _saveScoped(cockpitLayoutKey, JSON.stringify(state.cockpitKpiLayout))
  }
}

function mapKnowledgeEntriesToLegacyCards(response) {
  var items = Array.isArray(response)
    ? response
    : response && Array.isArray(response.items)
      ? response.items
      : []
  return items.map((entry) => {
    var id = entry && entry.id != null ? String(entry.id) : ""
    var title =
      (entry && (entry.title || entry.name || entry.display_name)) ||
      (id ? "Knowledge " + id : "Knowledge entry")
    var status = entry && entry.status ? String(entry.status).toLowerCase() : ""
    var linkUrl = entry && entry.type === "link" ? normalizeChatLink(entry.url) : ""
    return {
      display_name: String(title),
      enabled:
        !(entry && entry.enabled === false) &&
        status !== "archived" &&
        status !== "deleted" &&
        status !== "disabled",
      id: id,
      is_default_import_target: false,
      link_url: linkUrl,
      resource_id: id ? "knowledge-" + id : "knowledge-entry",
      resource_type: (entry && entry.type) || "knowledge",
      stale: false,
      title: String(title),
    }
  })
}

function mapContractUsersToLegacyUsers(response) {
  var items = Array.isArray(response)
    ? response
    : response && Array.isArray(response.items)
      ? response.items
      : []
  return items.map((user) => ({
    ...user,
    display_name:
      user.display_name || user.displayName || user.name || user.username || "",
    is_active: user.is_active !== false && user.isActive !== false,
    last_login_at: user.last_login_at || user.lastLoginAt || null,
    roles: Array.isArray(user.roles)
      ? user.roles
      : user.role
        ? [user.role]
        : [],
  }))
}

function mapKnowledgeSearchToLegacyResults(response) {
  var items = Array.isArray(response)
    ? response
    : response && Array.isArray(response.items)
      ? response.items
      : response && Array.isArray(response.results)
        ? response.results
        : []
  return items.map((item) => {
    var id = item.id || item.entry_id || item.entryId || item.source_id || ""
    var title =
      item.title ||
      item.name ||
      item.display_name ||
      item.chunk_title ||
      item.content ||
      "Knowledge result"
    return {
      href: id ? "knowledge#" + id : "#",
      status: item.status || item.mode || "",
      subtitle:
        item.subtitle ||
        item.summary ||
        item.snippet ||
        item.content ||
        item.text ||
        "",
      title: String(title),
      type: item.type || "knowledge",
    }
  })
}

function mapAnnouncementsToAdminNews(response) {
  var items = Array.isArray(response)
    ? response
    : response && Array.isArray(response.items)
      ? response.items
      : []
  return {
    items: items.map((item) => ({
      ...item,
      body: item.body || item.content || item.summary || "",
      category: item.category || item.priority || "",
      id: item.id,
      pinned: item.pinned || item.isPinned || false,
      published_at: item.published_at || item.publishedAt || "",
      source: item.source || item.author || "",
      title: item.title || "",
    })),
    total:
      response && typeof response.total === "number"
        ? response.total
        : items.length,
  }
}

function mapAdminNewsToAnnouncementPayload(payload) {
  return {
    title: payload.title,
    summary: payload.body,
    content: payload.body,
    priority: payload.category === "重要" || payload.category === "important"
      ? "important"
      : "normal",
  }
}

function mapWorkItemToLegacyTask(item) {
  var status = item && item.status ? String(item.status) : "pending"
  return {
    ...item,
    deadline:
      (item && (item.dueAt || item.due_at || item.deadline || item.dueTime)) ||
      null,
    done: status === "completed",
    id: item && item.id != null ? item.id : Date.now(),
    tag: (item && (item.tag || item.priority || item.origin)) || "跟进",
    title: (item && item.title) || "",
  }
}

function mapLegacyTaskToWorkItemCreate(title, tag, deadline) {
  return {
    dueAt: deadline || null,
    metadata: { tag },
    priority: "normal",
    title,
  }
}

function mapLegacyTaskToWorkItemUpdate(task) {
  return {
    dueAt: task.deadline || null,
    metadata: { tag: task.tag || "跟进" },
    title: task.title,
  }
}

function mapChatMessagesToLegacyMessages(response) {
  var items = Array.isArray(response)
    ? response
    : response && Array.isArray(response.items)
      ? response.items
      : []
  return items.map((message) => ({
    id: "m_bk_" + (message && message.id != null ? String(message.id) : ""),
    role: (message && message.role) || "assistant",
    content: (message && message.content) || "",
    references:
      message && Array.isArray(message.citations)
        ? message.citations
        : message && Array.isArray(message.references)
          ? message.references
          : undefined,
    webEvidence:
      message && Array.isArray(message.web_sources) ? message.web_sources : undefined,
    webSearchState:
      message && Array.isArray(message.web_sources) && message.web_sources.length
        ? "sourced"
        : undefined,
    turnId: (message && (message.turn_id || message.turnId)) || "",
    status: "completed",
    createdAt:
      message && (message.created_at || message.createdAt)
        ? String(message.created_at || message.createdAt).slice(11, 16)
        : "",
  }))
}

function isBackendChatSessionId(sessionId) {
  return /^\d+$/.test(String(sessionId || ""))
}

function mapChatSessionsToLegacySessions(response) {
  var items = Array.isArray(response)
    ? response
    : response && Array.isArray(response.items)
      ? response.items
      : []
  return items.map((session) => ({
    id: session && session.id != null ? String(session.id) : "",
    title: (session && session.title) || "",
    messages: [],
    surface: (session && session.surface) || "agent",
    createdAt:
      session && (session.created_at || session.createdAt)
        ? String(session.created_at || session.createdAt).slice(0, 16).replace("T", " ")
        : "",
    updatedAt:
      session && (session.updated_at || session.updatedAt)
        ? String(session.updated_at || session.updatedAt).slice(0, 16).replace("T", " ")
        : "",
    requestGeneration: 0,
    activeAbortController: null,
    activeChatRunId: null,
    activeStopPromise: null,
  }))
}

function parseChatSseFrame(frameText) {
  var event = "message"
  var dataLines = []
  frameText.split(/\r?\n/).forEach((line) => {
    if (line.startsWith("event:")) event = line.slice(6).trim()
    if (line.startsWith("data:")) dataLines.push(line.slice(5).trim())
  })
  var dataText = dataLines.join("\n")
  var data = dataText
  try {
    data = dataText ? JSON.parse(dataText) : null
  } catch (error) {
    data = dataText
  }
  return { data, event }
}

function isCurrentChatRequest(session, generation) {
  return (
    !!session &&
    session.requestGeneration === generation &&
    state.chatSessions.activeSessionId === session.id
  )
}

function applyChatSseFrame(frame, assistantMsg, session, generation) {
  // Every browser-visible update is session-scoped. A late SSE frame from a
  // window that has been switched away from must never repaint the active one.
  if (!isCurrentChatRequest(session, generation)) return true
  var event = frame.event || "message"
  var data = frame.data || {}
  if (event === "run.created" && data.run_id) {
    session.activeChatRunId = data.run_id
    state.activeChatRunId = data.run_id
    return false
  }
  if (event === "response.output_text.delta") {
    assistantMsg.content += data.delta || data.text || data.content || ""
    updateStreamingAssistantMessage(assistantMsg)
    return false
  }
  if (
    event === "knowledge.context" &&
    (Array.isArray(data.citations) || Array.isArray(data.references))
  ) {
    assistantMsg.references = data.citations || data.references
    assistantMsg.turnId = data.turn_id || data.turnId || assistantMsg.turnId || ""
    updateStreamingAssistantMessage(assistantMsg)
    return false
  }
  if (event === "approval.request") {
    assistantMsg.approval = {
      runId: data.run_id || state.activeChatRunId || "",
      title: data.title || data.message || data.prompt || data.summary || "助手请求确认",
      detail: data.detail || data.reason || data.description || "",
      status: "pending",
    }
    renderChatTranscript()
    return false
  }
  if (event === "web.search.started") {
    assistantMsg.webSearchState = "searching"
    return false
  }
  if (event === "web.search.completed") {
    assistantMsg.webEvidence = Array.isArray(data.sources) ? data.sources : []
    assistantMsg.webSearchState = assistantMsg.webEvidence.length ? "sourced" : "empty"
    updateStreamingAssistantMessage(assistantMsg)
    return false
  }
  if (event === "web.search.failed") {
    assistantMsg.webSearchFailed = true
    assistantMsg.webSearchState = "failed"
    updateStreamingAssistantMessage(assistantMsg)
    return false
  }
  if (event === "platform.action") {
    assistantMsg.platformAction = data
    assistantMsg.toolStatus = data.message || data.status || "平台操作已处理"
    updateStreamingAssistantMessage(assistantMsg)
    return false
  }
  if (event.indexOf("tool.") === 0) {
    var toolName = data.tool || data.name || data.title || event.slice(5)
    if (/web/i.test(String(toolName))) assistantMsg.webSearchUsed = true
    assistantMsg.toolStatus = toolName
    updateStreamingAssistantMessage(assistantMsg)
    return false
  }
  if (event === "response.completed") {
    assistantMsg.status = "completed"
    if (!assistantMsg.platformAction) assistantMsg.toolStatus = null
    renderChatTranscript()
    return true
  }
  if (
    event === "response.failed" ||
    event === "response.cancelled" ||
    event === "upstream.disconnected"
  ) {
    assistantMsg.status = event === "response.failed" ? "failed" : "interrupted"
    if (!assistantMsg.platformAction) assistantMsg.toolStatus = null
    if (!assistantMsg.content) {
      assistantMsg.content =
        data.message || data.error || "生成中断，请稍后重试。"
    }
    return true
  }
  return false
}

function drainChatSseBuffer(buffer, assistantMsg, session, generation) {
  var terminalReceived = false
  var parts = buffer.split(/\r?\n\r?\n/)
  var remainder = parts.pop() || ""
  parts.forEach((part) => {
    if (!part.trim()) return
    terminalReceived =
      applyChatSseFrame(parseChatSseFrame(part), assistantMsg, session, generation) ||
      terminalReceived
  })
  return { remainder, terminalReceived }
}

async function readChatSseResponse(response, assistantMsg, session, generation) {
  if (!response || !response.ok) {
    throw new Error("Chat SSE request failed")
  }
  var terminalReceived = false
  var pending = ""
  if (response.body && response.body.getReader && window.TextDecoder) {
    var reader = response.body.getReader()
    var decoder = new TextDecoder()
    while (true) {
      var result = await reader.read()
      if (result.done) break
      pending += decoder.decode(result.value, { stream: true })
      var drained = drainChatSseBuffer(pending, assistantMsg, session, generation)
      pending = drained.remainder
      terminalReceived = terminalReceived || drained.terminalReceived
    }
    pending += decoder.decode()
  } else if (response.text) {
    pending = await response.text()
  }
  var finalDrain = drainChatSseBuffer(
    pending + "\n\n",
    assistantMsg,
    session,
    generation,
  )
  terminalReceived = terminalReceived || finalDrain.terminalReceived
  if (!terminalReceived && isCurrentChatRequest(session, generation)) {
    assistantMsg.status = "interrupted"
    if (!assistantMsg.content) assistantMsg.content = "生成中断，请稍后重试。"
  }
}

const defaultEmbedUrls = {
  feishu: "https://www.feishu.cn/",
  dingtalk: "https://www.dingtalk.com/",
}
const apiBaseUrl =
  window.COLLAB_API_BASE_URL ||
  (window.location.protocol === "file:" ? "http://localhost:8000" : "")
const authBaseUrl = apiBaseUrl + "/api/auth"

function frontendContractMissing(context = {}) {
  console.warn("Frontend contract missing.", context)
  return new Error("该功能后端接口尚未纳入前端契约")
}
const validViews = new Set([
  "workspace",
  "portal",
  "subsystem",
  "notice-center",
  "document-center",
  "resource-center",
  "service-center",
  "news-center",
  "portal-dashboard",
  "calendar",
  "knowledge",
  "feishu",
  "dingtalk",
  "admin",
  "org-structure",
])
const customWebsiteNewView = "custom-website-new"

function getCustomWebsiteViewId(id) {
  return "custom-website-" + id
}

function isCustomWebsiteViewFor(websites, view) {
  return websites.some((site) => getCustomWebsiteViewId(site.id) === view)
}

function hasCustomWebsiteViewPrefix(view) {
  return typeof view === "string" && view.startsWith("custom-website-")
}

function isInitialViewAllowed(view, websites) {
  return (
    validViews.has(view) ||
    view === customWebsiteNewView ||
    isCustomWebsiteViewFor(websites, view)
  )
}
const allNewsSources = [
  { id: "enterprise", label: "企业资讯" },
  { id: "operations", label: "运营中心" },
  { id: "knowledge", label: "知识中心" },
  { id: "security", label: "安全办公室" },
  { id: "weibo", label: "微博头条" },
  { id: "people-daily", label: "人民日报" },
  { id: "xinhua", label: "新华社" },
  { id: "cctv", label: "央视新闻" },
]
const allNewsSourcesById = Object.fromEntries(
  allNewsSources.map((s) => [s.id, s.label]),
)
const ASSISTANT_MOCK_MESSAGES = [
  { actor: "张三", action: "修改了《2026年度预算报告》", time: "10:24" },
  { actor: "李四", action: "评论了《部门季度工作复盘表》", time: "09:12" },
  { actor: "王五", action: "分享了《会议纪要模板》", time: "昨天" },
]

const portalNewsItems = [
  {
    title: "欢迎使用星纪云1.0 — 点击订阅管理配置资讯源",
    source: "enterprise",
    tags: ["入门"],
    date: "",
  },
]
// ── Auth state (Phase 2) ─────────────────────────────────────
// Anonymous /auth/me succeeds only when the backend enables single-user mode.
let _singleUserMode = false
let _authToken = null
let _authUser = null
let _authRefreshing = false
let _authRefreshPromise = null
let _authSyncTimer = null

// Sync auth state into the TS module (window.__auth).
// The module script may not have executed yet when initAuth() completes
// (type="module" is deferred), so retry a few times if needed.
function _syncAuthModule(token, user) {
  if (window.__auth && window.__auth._syncState) {
    window.__auth._syncState(token, user)
    return
  }
  // Module not ready yet — retry with backoff
  var retries = 0
  var maxRetries = 20 // up to ~2 seconds total
  if (_authSyncTimer) clearTimeout(_authSyncTimer)
  ;(function retry() {
    if (window.__auth && window.__auth._syncState) {
      window.__auth._syncState(token, user)
      _authSyncTimer = null
    } else if (retries < maxRetries) {
      retries++
      _authSyncTimer = setTimeout(retry, 100)
    }
  })()
}

function setAuth(token, user) {
  _authToken = token
  _authUser = user
  window.App = window.App || {}
  window.App._authToken = token
  window.App._authUserId = user && user.id ? user.id : null
  // Mark last logged-in user so page reload can scope localStorage correctly
  if (user && user.id) {
    try {
      window.localStorage.setItem(lastUserIdKey, String(user.id))
    } catch (e) {}
  }
  _syncAuthModule(token, user)
  updateAuthUI()
}

function clearAuth() {
  _authToken = null
  _authUser = null
  window.App = window.App || {}
  window.App._authToken = null
  window.App._authUserId = null
  _syncAuthModule(null, null)
  updateAuthUI()
  // ── Clear user-data localStorage to prevent cross-user data leaks ──
  var userDataKeys = [
    taskStorageKey,
    pendingDeletesStorageKey,
    eventStorageKey,
    embedStorageKey,
    customWebsitesStorageKey,
    chatSessionsStorageKey,
    profileStorageKey,
    newsSubsStorageKey,
    lastUserIdKey,
    viewStorageKey,
  ]
  for (var i = 0; i < userDataKeys.length; i++) {
    try {
      window.localStorage.removeItem(userDataKeys[i])
    } catch (e) {
      /* ignore */
    }
  }
  _resetUserState()
}

async function restoreSingleUserIdentity() {
  _authToken = null
  _authUser = null
  window.App = window.App || {}
  window.App._authToken = null
  window.App._authUserId = null
  _syncAuthModule(null, null)
  await loadCurrentUser()
  return _authUser !== null
}

window.addEventListener("agent-platform:session-cleared", function () {
  if (_authToken !== null || _authUser !== null) {
    void restoreSingleUserIdentity().then(function (restored) {
      if (!restored) showLoginOverlay()
    })
  }
})

// ── Reset all user-specific state fields to defaults ──────────────
function _resetUserState() {
  state.tasks = defaultTasks.map((t) => Object.assign({}, t))
  state.events = defaultEvents.map((e) => Object.assign({}, e))
  state.pendingDeletes = new Set()
  state.embedUrls = Object.assign({}, defaultEmbedUrls)
  state.customWebsites = []
  state.chatSessions = { activeSessionId: null, sessions: [] }
  state.portalProfile = Object.assign({}, defaultProfile)
  state.newsSubscriptions = []
  state.notices = []
  state.documents = []
  state.resources = []
  state.news = []
  state.knowledge = []
  state.knowledgeImports = []
  state.portalDashboard = {}
  state.portalPreferences = {
    favorite_subsystems: [],
    favorite_documents: [],
    hidden_cards: [],
    card_order: [],
    news_subscriptions: [],
  }
  state.adminUsers = []
  state.adminRoles = []
  state.selectedSubsystem = null
  state.selectedAsset = null
  state.activeView = "workspace"
  state.activeSubTab = null
  state.tabs = []
  state.expandedNav = "workspace"
  renderTabs()
  renderCustomWebsiteNavigation()
  renderCustomWebsiteViews()
}

function isSuperAdmin() {
  return !!(
    _authUser &&
    ((Array.isArray(_authUser.roles) &&
      (_authUser.roles.includes("super_admin") ||
        _authUser.roles.includes("admin"))) ||
      (Array.isArray(_authUser.permissions) &&
        _authUser.permissions.includes("*")))
  )
}

function isLoggedIn() {
  return _authUser !== null
}

async function refreshAuthToken() {
  if (_singleUserMode && !_authToken) return null
  // Single-flight guard: if a refresh is already in progress, wait for it
  if (_authRefreshing && _authRefreshPromise) {
    try {
      await _authRefreshPromise
    } catch (e) {
      /* result checked below */
    }
    if (!_authToken) throw new Error("会话已过期，请重新登录")
    return
  }
  _authRefreshing = true
  _authRefreshPromise = (async () => {
    var contractAuth = getContractAuth()
    if (contractAuth && contractAuth.refresh) {
      var contractData = await contractAuth.refresh()
      _authToken = contractData.access_token
      window.App = window.App || {}
      window.App._authToken = _authToken
      _syncAuthModule(_authToken, _authUser)
      return contractData
    }
    const resp = await fetch(authBaseUrl + "/refresh", {
      method: "POST",
      credentials: "include",
    })
    if (!resp.ok) {
      clearAuth()
      throw new Error("会话已过期，请重新登录")
    }
    const data = await resp.json()
    _authToken = data.access_token
    window.App = window.App || {}
    window.App._authToken = _authToken
    _syncAuthModule(_authToken, _authUser)
    return data
  })()
  try {
    return await _authRefreshPromise
  } finally {
    _authRefreshing = false
    _authRefreshPromise = null
  }
}

async function loadCurrentUser() {
  try {
    var contractAuth = getContractAuth()
    if (contractAuth && contractAuth.fetchMe) {
      _authToken = contractAuth.getToken ? contractAuth.getToken() : _authToken
      _singleUserMode = !_authToken
      _authUser = await contractAuth.fetchMe()
      window.App = window.App || {}
      window.App._authUserId = _authUser && _authUser.id ? _authUser.id : null
      if (_authUser && _authUser.id) {
        try {
          window.localStorage.setItem(lastUserIdKey, String(_authUser.id))
        } catch (e) {}
      }
      _syncAuthModule(_authToken, _authUser)
      updateAuthUI()
      return
    }
    var resp = await fetch(authBaseUrl + "/me", {
      headers: _authToken ? { Authorization: `Bearer ${_authToken}` } : {},
    })
    if (resp.ok) {
      _singleUserMode = !_authToken
      _authUser = await resp.json()
      window.App = window.App || {}
      window.App._authUserId = _authUser && _authUser.id ? _authUser.id : null
      if (_authUser && _authUser.id) {
        try {
          window.localStorage.setItem(lastUserIdKey, String(_authUser.id))
        } catch (e) {}
      }
      _syncAuthModule(_authToken, _authUser)
      updateAuthUI()
      return
    }
    // On 401, try to refresh the access token once before giving up
    if (resp.status === 401 && _authToken) {
      try {
        await refreshAuthToken()
        resp = await fetch(authBaseUrl + "/me", {
          headers: { Authorization: `Bearer ${_authToken}` },
        })
        if (resp.ok) {
          _authUser = await resp.json()
          window.App = window.App || {}
          window.App._authUserId =
            _authUser && _authUser.id ? _authUser.id : null
          if (_authUser && _authUser.id) {
            try {
              window.localStorage.setItem(lastUserIdKey, String(_authUser.id))
            } catch (e) {}
          }
          _syncAuthModule(_authToken, _authUser)
          updateAuthUI()
          return
        }
      } catch (refreshErr) {
        // Refresh failed — session truly expired
      }
      clearAuth()
    }
  } catch (e) {
    if (!_authToken && e && e.status === 401) _singleUserMode = false
    console.warn("Failed to load current user", e)
  }
}

async function refreshAuthenticatedWorkbenchData() {
  await Promise.allSettled([
    fetchChatSessionsFromBackend(),
    fetchKnowledgeMappings(),
    fetchCockpitDecisions(),
  ])
  renderAiWorkbench()
}

async function handleLogin(username, password) {
  const errorEl = document.getElementById("loginError")
  const submitBtn = document.getElementById("loginSubmitBtn")
  errorEl.classList.remove("show")
  submitBtn.disabled = true
  submitBtn.textContent = "登录中…"

  try {
    var contractAuth = getContractAuth()
    if (contractAuth && contractAuth.login) {
      var contractData = await contractAuth.login(username, password)
      setAuth(contractData.access_token, contractData.user)
      document.getElementById("loginOverlay").classList.remove("show")
      await refreshAuthenticatedWorkbenchData()
      if (contractData.must_change_password) {
        showChangePasswordOverlay()
      }
      return
    }
    const resp = await fetch(authBaseUrl + "/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ username, password }),
    })
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: "登录失败" }))
      errorEl.textContent = err.detail || "登录失败"
      errorEl.classList.add("show")
      submitBtn.disabled = false
      submitBtn.textContent = "登录"
      return
    }
    const data = await resp.json()
    setAuth(data.access_token, data.user)

    // Close login overlay
    document.getElementById("loginOverlay").classList.remove("show")
    await refreshAuthenticatedWorkbenchData()

    // Check if must change password
    if (data.must_change_password) {
      showChangePasswordOverlay()
    }
  } catch (e) {
    if (e && typeof e === "object" && Number(e.status) === 401) {
      errorEl.textContent = "用户名或密码错误"
    } else if (e instanceof TypeError || !e || !e.message) {
      errorEl.textContent = "网络错误，请稍后再试"
    } else {
      errorEl.textContent = e.message
    }
    errorEl.classList.add("show")
  }
  submitBtn.disabled = false
  submitBtn.textContent = "登录"
}

function toggleLoginMode() {
  setLoginMode(_loginMode === "login" ? "register" : "login")
  document.getElementById("loginForm").reset()
  document.getElementById("loginError").classList.remove("show")
}

async function handleRegister(username, password, displayName, email) {
  void username
  void password
  void displayName
  void email
  var errorEl = document.getElementById("loginError")
  var submitBtn = document.getElementById("loginSubmitBtn")
  errorEl.classList.remove("show")
  frontendContractMissing({
    operationId: "missing_auth_register",
    method: "POST",
    path: "/auth/register",
    permission: "anonymous",
  })
  errorEl.textContent = "注册接口尚未纳入前端契约"
  errorEl.classList.add("show")
  submitBtn.disabled = false
  submitBtn.textContent = "注册"
}

function withTimeout(promise, timeoutMs, message) {
  let timeoutId
  const timeout = new Promise((_, reject) => {
    timeoutId = window.setTimeout(() => reject(new Error(message)), timeoutMs)
  })
  return Promise.race([promise, timeout]).finally(() => window.clearTimeout(timeoutId))
}

async function handleLogout() {
  document.getElementById("userPopover").classList.remove("show")
  try {
    var contractAuth = getContractAuth()
    if (contractAuth && contractAuth.logout && contractAuth.getToken()) {
      await withTimeout(contractAuth.logout(), 8000, "logout timeout")
    }
  } catch (e) {
    // Local session state is still cleared below.
  }
  clearAuth()
  if (!(await restoreSingleUserIdentity())) showLoginOverlay()
}

async function handleChangePassword(currentPassword, newPassword) {
  void currentPassword
  void newPassword
  const errorEl = document.getElementById("changePasswordError")
  const submitBtn = document.getElementById("changePasswordSubmitBtn")
  errorEl.classList.remove("show")
  frontendContractMissing({
    operationId: "missing_auth_change_password",
    method: "POST",
    path: "/auth/change-password",
    permission: "authenticated",
  })
  errorEl.textContent = "修改密码接口尚未纳入前端契约"
  errorEl.classList.add("show")
  submitBtn.disabled = false
  submitBtn.textContent = "保存新密码"
}

var _loginMode = "login" // "login" | "register"

function setLoginMode(mode) {
  _loginMode = mode
  var isRegister = mode === "register"
  document.getElementById("loginCardTitle").textContent = isRegister
    ? "注册"
    : "登录"
  document.getElementById("loginCardSub").textContent = isRegister
    ? "创建新账号加入星纪云1.0"
    : "使用你的账号登录星纪云1.0"
  document.getElementById("loginSubmitBtn").textContent = isRegister
    ? "注册"
    : "登录"
  document.getElementById("regDisplayNameField").style.display = isRegister
    ? ""
    : "none"
  document.getElementById("regEmailField").style.display = isRegister
    ? ""
    : "none"
  document.getElementById("loginSwitchText").textContent = isRegister
    ? "已有账号？"
    : "没有账号？"
  document.getElementById("loginSwitchBtn").textContent = isRegister
    ? "去登录"
    : "注册新账号"
  document.getElementById("loginError").classList.remove("show")
}

function showLoginOverlay() {
  setLoginMode("login")
  document.getElementById("loginOverlay").classList.add("show")
  document.getElementById("loginForm").reset()
  setTimeout(() => {
    document.getElementById("loginUsername").focus()
  }, 100)
}

function showChangePasswordOverlay() {
  document.getElementById("changePasswordOverlay").classList.add("show")
  document.getElementById("changePasswordError").classList.remove("show")
  document.getElementById("changePasswordForm").reset()
}

function updateAuthUI() {
  var loggedIn = isLoggedIn()
  var user = _authUser

  // Sidebar avatar/name
  var sidebarAvatar = document.getElementById("sidebarAvatar")
  var sidebarName = document.getElementById("sidebarName")
  var userTrigger = document.querySelector(".user-trigger")
  var userAvatar = userTrigger ? userTrigger.querySelector(".avatar") : null
  var userNameSpan = userTrigger
    ? userTrigger.querySelector(".avatar + span")
    : null

  if (loggedIn && user) {
    var initial = user.display_name ? user.display_name.charAt(0) : "?"
    if (sidebarAvatar) sidebarAvatar.textContent = initial
    if (sidebarName) sidebarName.textContent = user.display_name
    if (userAvatar) userAvatar.textContent = initial
    if (userNameSpan) userNameSpan.textContent = user.display_name
    document.body.classList.remove("auth-guest")

    // Sync portal profile card with auth user data
    var profileChanged = false
    if (
      state.portalProfile.name !== (user.display_name || user.username || "")
    ) {
      state.portalProfile.name = user.display_name || user.username || ""
      profileChanged = true
    }
    if (state.portalProfile.email !== (user.email || "")) {
      state.portalProfile.email = user.email || ""
      profileChanged = true
    }
    if (profileChanged) saveProfile()
    // Always refresh portal card — it may have rendered before auth was ready
    syncProfileUI()
  } else {
    if (sidebarAvatar) sidebarAvatar.textContent = "?"
    if (sidebarName) sidebarName.textContent = "未登录"
    if (userAvatar) userAvatar.textContent = "?"
    if (userNameSpan) userNameSpan.textContent = "未登录"
    document.body.classList.add("auth-guest")
  }
  updateAdminUI()
}

function updateAdminUI() {
  var navItem = document.getElementById("navAdmin")
  var show = isSuperAdmin()
  if (navItem) navItem.hidden = !show
  if (show) {
    fetchAdminUsers().catch(() => {})
    fetchAdminRoles().catch(() => {})
  }
}

// Try to restore session on page load (with retry for slow backend startup).
// The promise is exposed so auth-dependent API calls can defer until it resolves.
var _initAuthReady = (async function initAuth() {
  var maxRetries = 3
  for (var attempt = 0; attempt < maxRetries; attempt++) {
    try {
      await loadCurrentUser()
      if (_authUser) break
      var contractAuth = getContractAuth()
      if (contractAuth && contractAuth.refresh) {
        var contractData = await contractAuth.refresh()
        _authToken = contractData.access_token
        await loadCurrentUser()
        break
      }
      var resp = await fetch(authBaseUrl + "/refresh", {
        method: "POST",
        credentials: "include",
      })
      if (resp.ok) {
        var data = await resp.json()
        _authToken = data.access_token
        await loadCurrentUser()
        break // success — exit retry loop
      }
      // 401/403 — no valid session, don't retry
      if (resp.status === 401 || resp.status === 403) break
    } catch (e) {
      // Network error — may retry after short delay
      if (attempt < maxRetries - 1) {
        await new Promise((r) => {
          setTimeout(r, 500 * (attempt + 1))
        })
      }
    }
  }
  updateAuthUI()
})()

function dateKey(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`
}
const currentDate = new Date()
const todayKey = dateKey(currentDate)
function getInitialView(customWebsites) {
  try {
    var scoped = _loadScoped(viewStorageKey, null)
    if (scoped && isInitialViewAllowed(scoped, customWebsites)) return scoped
  } catch (e) {}
  const savedView = window.localStorage.getItem(viewStorageKey)
  return isInitialViewAllowed(savedView, customWebsites) ? savedView : "workspace"
}
// Capture which user's localStorage data was loaded at page init.
// If a different user logs in later, applyPortalBootstrap will discard
// the stale data before merging server results.
var _pageLoadUserId = null
try {
  _pageLoadUserId = window.localStorage.getItem(lastUserIdKey)
} catch (e) {}
const defaultTasks = []
const defaultEvents = []
function getInitialTasks() {
  try {
    // Prefer user-scoped key (defence-in-depth against cross-user leaks)
    var raw = _loadScoped(taskStorageKey, null)
    if (raw) {
      var parsed = JSON.parse(raw)
      if (Array.isArray(parsed))
        return parsed.map((t) =>
          Object.assign({}, t, {
            deadline: t.deadline || t.dueTime || t.due_time || null,
          }),
        )
    }
    // Fallback: unscoped key (backward compatibility)
    var savedTasks = JSON.parse(
      window.localStorage.getItem(taskStorageKey) || "null",
    )
    if (Array.isArray(savedTasks))
      return savedTasks.map((t) =>
        Object.assign({}, t, {
          deadline: t.deadline || t.dueTime || t.due_time || null,
        }),
      )
  } catch (error) {
    window.localStorage.removeItem(taskStorageKey)
  }
  return defaultTasks.map((task) => Object.assign({}, task))
}

function getInitialEvents() {
  try {
    var raw = _loadScoped(eventStorageKey, null)
    if (raw) {
      var parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) return parsed
    }
    const savedEvents = JSON.parse(
      window.localStorage.getItem(eventStorageKey) || "null",
    )
    if (Array.isArray(savedEvents)) return savedEvents
  } catch (error) {
    window.localStorage.removeItem(eventStorageKey)
  }
  return defaultEvents.map((event) => Object.assign({}, event))
}

function getInitialEmbedUrls() {
  try {
    var raw = _loadScoped(embedStorageKey, null)
    if (raw) {
      var parsed = JSON.parse(raw)
      if (parsed && typeof parsed === "object")
        return Object.assign({}, defaultEmbedUrls, parsed)
    }
    const savedUrls = JSON.parse(
      window.localStorage.getItem(embedStorageKey) || "null",
    )
    return Object.assign(
      {},
      defaultEmbedUrls,
      savedUrls && typeof savedUrls === "object" ? savedUrls : {},
    )
  } catch (error) {
    window.localStorage.removeItem(embedStorageKey)
    return Object.assign({}, defaultEmbedUrls)
  }
}

function getInitialCustomWebsites() {
  try {
    var raw = _loadScoped(customWebsitesStorageKey, "[]")
    return parseCustomWebsites(JSON.parse(raw))
  } catch (error) {
    _removeScoped(customWebsitesStorageKey)
    return []
  }
}

function getInitialChatSessions() {
  try {
    var raw = _loadScoped(chatSessionsStorageKey, null)
    if (raw) {
      var parsed = JSON.parse(raw)
      if (
        parsed &&
        typeof parsed === "object" &&
        Array.isArray(parsed.sessions)
      )
        return parsed
    }
    const saved = JSON.parse(
      window.localStorage.getItem(chatSessionsStorageKey) || "null",
    )
    if (saved && typeof saved === "object" && Array.isArray(saved.sessions))
      return saved
  } catch (error) {
    window.localStorage.removeItem(chatSessionsStorageKey)
  }
  return { activeSessionId: null, sessions: [] }
}

function saveChatSessions() {
  var data = JSON.stringify(state.chatSessions)
  _saveScoped(chatSessionsStorageKey, data)
  try {
    window.localStorage.setItem(chatSessionsStorageKey, data)
  } catch (e) {}
}

const defaultProfile = { name: "", department: "", email: "", phone: "" }
function getInitialProfile() {
  try {
    var raw = _loadScoped(profileStorageKey, null)
    if (raw) {
      var parsed = JSON.parse(raw)
      if (parsed && typeof parsed === "object")
        return Object.assign({}, defaultProfile, parsed)
    }
    const saved = JSON.parse(
      window.localStorage.getItem(profileStorageKey) || "null",
    )
    return saved && typeof saved === "object"
      ? Object.assign({}, defaultProfile, saved)
      : Object.assign({}, defaultProfile)
  } catch (error) {
    window.localStorage.removeItem(profileStorageKey)
    return Object.assign({}, defaultProfile)
  }
}
function saveProfile() {
  var data = JSON.stringify(state.portalProfile)
  _saveScoped(profileStorageKey, data)
  try {
    window.localStorage.setItem(profileStorageKey, data)
  } catch (e) {}
}

const defaultNewsSubs = allNewsSources.slice(0, 4).map((s) => s.id)
function getInitialNewsSubs() {
  try {
    var raw = _loadScoped(newsSubsStorageKey, null)
    if (raw) {
      var parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) return parsed
    }
    const saved = JSON.parse(
      window.localStorage.getItem(newsSubsStorageKey) || "null",
    )
    if (Array.isArray(saved)) return saved
  } catch (error) {
    window.localStorage.removeItem(newsSubsStorageKey)
  }
  return [].concat(defaultNewsSubs)
}
function saveNewsSubs() {
  var data = JSON.stringify(state.newsSubscriptions)
  _saveScoped(newsSubsStorageKey, data)
  try {
    window.localStorage.setItem(newsSubsStorageKey, data)
  } catch (e) {}
}

function getInitialServiceSubs() {
  try {
    var raw = _loadScoped(serviceSubsStorageKey, null)
    if (raw) {
      var parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) return parsed
    }
    const saved = JSON.parse(
      window.localStorage.getItem(serviceSubsStorageKey) || "null",
    )
    if (Array.isArray(saved)) return saved
  } catch (error) {
    window.localStorage.removeItem(serviceSubsStorageKey)
  }
  return ["教职工考勤", "教职工请假", "教职工信息变更管理", "离退休人员管理"]
}
function saveServiceSubs() {
  var data = JSON.stringify(state.serviceSubscriptions)
  _saveScoped(serviceSubsStorageKey, data)
  try {
    window.localStorage.setItem(serviceSubsStorageKey, data)
  } catch (e) {}
}

function getInitialPendingDeletes() {
  try {
    var raw = _loadScoped(pendingDeletesStorageKey, null)
    if (raw) {
      var parsedScoped = JSON.parse(raw)
      if (Array.isArray(parsedScoped))
        return new Set(parsedScoped.filter((id) => typeof id === "number"))
    }
    const saved = JSON.parse(
      window.localStorage.getItem(pendingDeletesStorageKey) || "null",
    )
    if (Array.isArray(saved))
      return new Set(saved.filter((id) => typeof id === "number"))
  } catch (error) {
    window.localStorage.removeItem(pendingDeletesStorageKey)
  }
  return new Set()
}

function savePendingDeletes() {
  var data = JSON.stringify(
    [].concat(state.pendingDeletes ? Array.from(state.pendingDeletes) : []),
  )
  _saveScoped(pendingDeletesStorageKey, data)
  try {
    window.localStorage.setItem(pendingDeletesStorageKey, data)
  } catch (e) {}
}

async function apiJson(path, options = {}) {
  if (path && path.startsWith("/__frontend_missing_contract__/")) {
    throw frontendContractMissing({ path, options })
  }
  const isFormData = options.body instanceof FormData
  const headers = {
    ...(isFormData ? {} : { "Content-Type": "application/json" }),
    ...(options.headers || {}),
  }
  // Phase 2: attach access token if available
  if (_authToken) {
    headers["Authorization"] = `Bearer ${_authToken}`
  }
  let response = await fetch(`${apiBaseUrl}${path}`, {
    ...options,
    headers,
    credentials: "include",
  })

  // Phase 2: on 401, try refresh once
  if (response.status === 401 && _authToken && !options._retried) {
    try {
      await refreshAuthToken()
      headers["Authorization"] = `Bearer ${_authToken}`
      response = await fetch(`${apiBaseUrl}${path}`, {
        ...options,
        headers,
        credentials: "include",
        _retried: true,
      })
    } catch (e) {
      // refresh failed — let original 401 propagate
    }
  }

  if (!response.ok) throw new Error(await readApiError(response))
  return response.json()
}

async function readApiError(response) {
  try {
    const payload = await response.json()
    if (typeof payload.detail === "string") return payload.detail
    if (payload.detail && typeof payload.detail.message === "string")
      return payload.detail.message
  } catch (error) {
    console.warn("API error response was not JSON.", error)
  }
  return `API request failed: ${response.status}`
}

function listItems(payload, fallback = []) {
  return payload && Array.isArray(payload.items) ? payload.items : fallback
}

async function fetchWorkItemsPayload() {
  var workItems = getAppRuntimeService("workItems")
  if (workItems && workItems.listWorkItems && isLoggedIn()) {
    var payload = await workItems.listWorkItems()
    return {
      items: listItems(payload, []).map(mapWorkItemToLegacyTask),
      total: payload && typeof payload.total === "number" ? payload.total : 0,
    }
  }
  return null
}

function mergeTasks(serverPayload, localTasks) {
  if (!serverPayload || !Array.isArray(serverPayload.items)) {
    return { merged: localTasks, localOnly: [], diverged: [] }
  }
  // Normalize snake_case from server + legacy dueTime to deadline
  const normalize = (t) => ({
    ...t,
    deadline: t.deadline || t.dueTime || t.due_time || null,
  })
  const serverTasks = serverPayload.items
    .filter((t) => !state.pendingDeletes.has(t.id))
    .map(normalize)
  const serverMap = new Map(serverTasks.map((t) => [t.id, t]))
  const localMap = new Map(localTasks.map((t) => [t.id, t]))
  const serverIds = new Set(serverTasks.map((t) => t.id))

  // Prefer local version when both exist (preserves offline done-toggle / edits)
  const merged = serverTasks.map((st) => localMap.get(st.id) || st)
  // Track diverged tasks (exist on both, but local state differs from server)
  const diverged = []
  for (const lt of localTasks) {
    const st = serverMap.get(lt.id)
    if (
      st &&
      (st.done !== lt.done ||
        st.title !== lt.title ||
        st.tag !== lt.tag ||
        (st.deadline || null) !== (lt.deadline || null))
    ) {
      diverged.push(lt)
    }
  }
  // Append local-only tasks (created offline — need to create on server)
  const localOnly = []
  for (const lt of localTasks) {
    if (!serverIds.has(lt.id)) {
      merged.push(lt)
      localOnly.push(lt)
    }
  }
  return { merged, localOnly, diverged }
}

async function syncLocalTasksToServer(localOnly, diverged) {
  // Create local-only tasks on server
  for (const task of localOnly) {
    try {
      const created = await createTaskRemote(
        task.title,
        task.tag,
        task.deadline,
      )
      const idx = state.tasks.findIndex((t) => t.id === task.id)
      if (idx !== -1) {
        state.tasks[idx] = { ...created, done: task.done }
        if (task.done) {
          await updateTaskRemote(state.tasks[idx]).catch(() => {})
        }
      }
    } catch (e) {
      console.warn("Local task sync deferred.", e)
    }
  }
  // Push diverged local state back to server
  for (const task of diverged) {
    try {
      await updateTaskRemote(task)
    } catch (e) {
      console.warn("Task update sync deferred.", e)
    }
  }
}

async function retryPendingDeletes() {
  const ids = [...state.pendingDeletes]
  for (const taskId of ids) {
    try {
      await deleteTaskRemote(taskId)
      state.pendingDeletes.delete(taskId)
    } catch (e) {
      // Remove from pending if server confirms task doesn't exist (404)
      const msg = e && e.message ? e.message : ""
      if (msg.includes("404") || msg.includes("not found")) {
        state.pendingDeletes.delete(taskId)
      }
      // Otherwise keep in set — will retry on next bootstrap
    }
  }
  if (ids.length !== state.pendingDeletes.size) {
    savePendingDeletes()
  }
}

async function applyPortalBootstrap(payload) {
  if (!payload || typeof payload !== "object") return
  // ── Detect user switch: if localStorage data belongs to a different user, ──
  // discard it so stale data from a previous session never leaks in.
  var currentUserId = _authUser && _authUser.id ? String(_authUser.id) : null
  if (currentUserId && _pageLoadUserId && _pageLoadUserId !== currentUserId) {
    // Different user — reset all state before merging server data
    _resetUserState()
    // Clear old user's scoped localStorage data
    var _oldKeys = [
      taskStorageKey,
      pendingDeletesStorageKey,
      eventStorageKey,
      embedStorageKey,
      customWebsitesStorageKey,
      chatSessionsStorageKey,
      profileStorageKey,
      newsSubsStorageKey,
      viewStorageKey,
    ]
    for (var _i = 0; _i < _oldKeys.length; _i++) {
      try {
        window.localStorage.removeItem(_oldKeys[_i])
      } catch (e) {}
    }
    // Also clear old user's scoped keys
    try {
      for (var _j = 0; _j < _oldKeys.length; _j++) {
        try {
          window.localStorage.removeItem(_oldKeys[_j] + ":" + _pageLoadUserId)
        } catch (e) {}
      }
    } catch (e) {}
  }
  // Update page-load marker so subsequent bootstraps in the same session
  // don't re-trigger the reset.
  _pageLoadUserId = currentUserId
  state.customWebsites = getInitialCustomWebsites()
  renderCustomWebsiteNavigation()
  renderCustomWebsiteViews()
  if (payload.embed_urls && typeof payload.embed_urls === "object") {
    state.embedUrls = {
      ...state.embedUrls,
      ...Object.fromEntries(
        Object.entries(payload.embed_urls).filter(
          ([, value]) => typeof value === "string" && value.trim(),
        ),
      ),
    }
    saveEmbedUrls()
  }
  var taskPayload = payload.workspace?.tasks
  try {
    taskPayload = (await fetchWorkItemsPayload()) || taskPayload
  } catch (error) {
    console.warn("Work items unavailable; using bootstrap tasks.", error)
  }
  const { merged, localOnly, diverged } = mergeTasks(taskPayload, state.tasks)
  state.tasks = merged
  state.events = listItems(payload.calendar?.events, state.events)
  state.knowledge = listItems(payload.knowledge?.spaces, state.knowledge)
  state.systems = listItems(payload.portal?.systems, state.systems)
  state.services = listItems(payload.portal?.services, state.services)
  state.notices = listItems(payload.workspace?.notices, state.notices)
  state.documents = listItems(payload.workspace?.documents, state.documents)
  state.resources = listItems(payload.workspace?.resources, state.resources)
  state.news = listItems(payload.portal?.news, state.news)
  if (payload.portal?.preferences)
    state.portalPreferences = payload.portal.preferences
  if (payload.portal?.dashboard)
    state.portalDashboard = payload.portal.dashboard
  if (payload.workspace?.dashboard)
    state.portalDashboard = {
      ...state.portalDashboard,
      ...payload.workspace.dashboard,
    }
  state.newsSubscriptions = state.portalPreferences.news_subscriptions?.length
    ? state.portalPreferences.news_subscriptions
    : state.newsSubscriptions
  if (Array.isArray(payload.workspace?.shortcuts))
    state.shortcuts = payload.workspace.shortcuts
  // Sync local-only and diverged tasks to server before saving
  if (localOnly.length > 0 || diverged.length > 0) {
    await syncLocalTasksToServer(localOnly, diverged)
  }
  // Retry pending deletes (tasks deleted while server was unreachable)
  if (state.pendingDeletes.size > 0) {
    await retryPendingDeletes()
  }
  saveTasks()
  saveEvents()
  renderTasks()
  updateSidebarBadge()
  renderWorkspaceAssets()
  renderPortalDashboard()
  renderWorkbenchSchedule()
  renderPortal()
  renderCalendar()
  renderAiWorkbench()
  renderEmbeds()
}

async function fetchPortalBootstrap() {
  try {
    var enterpriseService = requireAppRuntimeService(
      "enterprise",
      "getLegacyBootstrap",
    )
    var dashboardPayload = {}
    var dashboardService = getAppRuntimeService("dashboard")
    if (dashboardService && dashboardService.getDashboard) {
      try {
        dashboardPayload = await dashboardService.getDashboard()
      } catch (dashboardError) {
        console.warn("Dashboard data unavailable.", dashboardError)
      }
    }
    var portalPayload =
      await enterpriseService.getLegacyBootstrap(dashboardPayload)
    await applyPortalBootstrap(portalPayload)
  } catch (error) {
    console.warn("Portal bootstrap unavailable; using local defaults.", error)
  }
}

const initialCustomWebsites = getInitialCustomWebsites()
const state = {
  customWebsites: initialCustomWebsites,
  activeView: getInitialView(initialCustomWebsites),
  activeSubTab: null,
  month: currentDate.getMonth(),
  year: currentDate.getFullYear(),
  selectedScheduleDate: todayKey,
  taskFilter: "todo",
  kbFilter: "all",
  editingEventIndex: null,
  events: getInitialEvents(),
  tasks: getInitialTasks(),
  cockpitPipelineTasks: [],
  cockpitDecisions: [],
  cockpitDecisionFilter: "all",
  cockpitDecisionContractsAvailable: false,
  cockpitDecisionError: "",
  cockpitDecisionRejectingId: null,
  cockpitTaskRange: _loadScoped(cockpitTaskRangeKey, "day"),
  cockpitKpiLayout: JSON.parse(
    _loadScoped(
      cockpitLayoutKey,
      '["business","staff","market","production","other"]',
    ),
  ),
  cockpitExpandedKpi: null,
  cockpitEditMode: false,
  cockpitFavorites: JSON.parse(_loadScoped(cockpitFavoritesKey, "[]")),
  cockpitEntries: JSON.parse(_loadScoped(cockpitEntriesKey, "[]")),
  pendingDeletes: getInitialPendingDeletes(),
  shortcuts: [
    ["公告", "通知中心", "app-orange"],
    ["智能问答", "AI 助手", "app-purple"],
    ["会议", "会议管理", "app-blue"],
    ["表单", "流程申请", "app-cyan"],
    ["轻审批", "审批中心", "app-red"],
    ["笔记", "我的笔记", "app-orange"],
    ["汇报", "工作汇报", "app-blue"],
    ["日历", "日程管理", "app-blue"],
    ["待办中心", "任务管理", "app-green"],
    ["融合门户", "门户首页", "app-red"],
  ],
  embedUrls: getInitialEmbedUrls(),
  systems: [
    {
      code: "oa",
      name: "OA",
      category: "办公行政类",
      description: "公文流转、流程审批、通知公告等协同办公一体化平台",
      status: "active",
      entry_type: "internal",
      owner_department: "行政管理部",
      owner_name: "OA 支持",
      support_contact: "OA 支持",
      icon_tone: "app-blue",
    },
    {
      code: "supervision",
      name: "督办",
      category: "办公行政类",
      description: "重点工作任务分解、进度追踪、责任落实的闭环管理系统",
      status: "active",
      entry_type: "internal",
      owner_department: "行政管理部",
      owner_name: "综合服务台",
      support_contact: "综合服务台",
      icon_tone: "app-blue",
    },
    {
      code: "hr",
      name: "HR 人事",
      category: "人力组织类",
      description: "组织架构、入转调离、合同档案、人事基础数据中心",
      status: "active",
      entry_type: "internal",
      owner_department: "人力资源部",
      owner_name: "人事服务台",
      support_contact: "人事服务台",
      icon_tone: "app-green",
    },
    {
      code: "recruit",
      name: "招聘",
      category: "人力组织类",
      description: "岗位发布、简历筛选、面试安排、录用审批全流程管理",
      status: "active",
      entry_type: "internal",
      owner_department: "人力资源部",
      owner_name: "招聘专员",
      support_contact: "招聘专员",
      icon_tone: "app-green",
    },
    {
      code: "training",
      name: "培训",
      category: "人力组织类",
      description: "培训计划制定、课程发布、学员管理、培训效果评估",
      status: "active",
      entry_type: "internal",
      owner_department: "人力资源部",
      owner_name: "培训专员",
      support_contact: "培训专员",
      icon_tone: "app-green",
    },
    {
      code: "care",
      name: "员工关怀",
      category: "人力组织类",
      description: "员工福利、健康关怀、团建活动、生日节日慰问管理",
      status: "active",
      entry_type: "internal",
      owner_department: "人力资源部",
      owner_name: "员工关系",
      support_contact: "员工关系",
      icon_tone: "app-green",
    },
    {
      code: "crm",
      name: "CRM",
      category: "经营业务类",
      description: "客户信息管理、销售机会跟踪、客户关系维护一体化平台",
      status: "active",
      entry_type: "internal",
      owner_department: "销售管理部",
      owner_name: "CRM 支持",
      support_contact: "CRM 支持",
      icon_tone: "app-orange",
    },
    {
      code: "erp",
      name: "ERP",
      category: "经营业务类",
      description: "企业资源计划管理系统，涵盖采购、库存、生产、销售全链路",
      status: "active",
      entry_type: "internal",
      owner_department: "运营管理部",
      owner_name: "ERP 支持",
      support_contact: "ERP 支持",
      icon_tone: "app-orange",
    },
    {
      code: "ticket",
      name: "售后工单",
      category: "经营业务类",
      description: "客户报修、投诉处理、服务请求的工单流转与闭环管理",
      status: "active",
      entry_type: "internal",
      owner_department: "客户服务部",
      owner_name: "工单中心",
      support_contact: "工单中心",
      icon_tone: "app-orange",
    },
    {
      code: "supply-chain",
      name: "供应链生产",
      category: "经营业务类",
      description: "供应商管理、采购计划、生产排程、物流配送协同平台",
      status: "active",
      entry_type: "internal",
      owner_department: "供应链管理部",
      owner_name: "供应链支持",
      support_contact: "供应链支持",
      icon_tone: "app-orange",
    },
    {
      code: "finance",
      name: "财务",
      category: "财资后勤 & 支撑类",
      description: "财务核算、预算管理、费用报销、财务报表一体化管理系统",
      status: "active",
      entry_type: "internal",
      owner_department: "财务管理部",
      owner_name: "财务服务台",
      support_contact: "财务服务台",
      icon_tone: "app-purple",
    },
    {
      code: "fixed-assets",
      name: "固定资产",
      category: "财资后勤 & 支撑类",
      description: "资产登记、领用、调拨、盘点、报废全生命周期管理",
      status: "active",
      entry_type: "internal",
      owner_department: "资产管理部",
      owner_name: "资产管理",
      support_contact: "资产管理",
      icon_tone: "app-purple",
    },
    {
      code: "property",
      name: "厂区物业",
      category: "财资后勤 & 支撑类",
      description: "厂区设施管理、安全巡查、环境卫生、绿化养护服务",
      status: "active",
      entry_type: "internal",
      owner_department: "物业管理部",
      owner_name: "物业服务",
      support_contact: "物业服务",
      icon_tone: "app-purple",
    },
    {
      code: "repair",
      name: "报修",
      category: "财资后勤 & 支撑类",
      description: "设备设施故障报修、维修派单、进度跟踪、满意度评价",
      status: "active",
      entry_type: "internal",
      owner_department: "后勤保障部",
      owner_name: "报修中心",
      support_contact: "报修中心",
      icon_tone: "app-purple",
    },
    {
      code: "data-hub",
      name: "数据中台",
      category: "财资后勤 & 支撑类",
      description: "企业数据汇聚、治理、分析、可视化的统一数据服务平台",
      status: "active",
      entry_type: "internal",
      owner_department: "数据管理部",
      owner_name: "数据中台",
      support_contact: "数据中台",
      icon_tone: "app-purple",
    },
    {
      code: "party",
      name: "党建风控",
      category: "财资后勤 & 支撑类",
      description: "党建管理、纪检监察、风险控制、合规审计综合管理平台",
      status: "active",
      entry_type: "internal",
      owner_department: "党群工作部",
      owner_name: "党建支持",
      support_contact: "党建支持",
      icon_tone: "app-purple",
    },
  ],
  services: [
    "教职工考勤",
    "教职工请假",
    "教职工信息变更管理",
    "离退休人员管理",
    "教职工进校",
    "教职工招聘",
    "在职教职工工资查询与统计",
    "在职证明",
    "因公外出报备申请",
  ],
  notices: [],
  documents: [],
  resources: [],
  news: [],
  portalDashboard: {},
  portalPreferences: {
    favorite_subsystems: [],
    favorite_documents: [],
    hidden_cards: [],
    card_order: [],
    news_subscriptions: [],
  },
  selectedSubsystem: null,
  selectedAsset: null,
  knowledge: [],
  knowledgeImports: [],
  chatSessions: getInitialChatSessions(),
  isStreaming: false,
  chatSessionCreationPromise: null,
  pendingRetryMessage: null,
  activeAbortController: null,
  activeChatRunId: null,
  portalEditMode: false,
  portalProfile: getInitialProfile(),
  newsSubscriptions: getInitialNewsSubs(),
  _lastOverdueIds: null,
  adminUsers: [],
  adminRoles: [],
  tabs: [],
  expandedNav: "workspace",
}

const icon = (id, extra = "") =>
  `<svg class="icon ${extra}"><use href="#${id}"></use></svg>`
const $ = (selector) => document.querySelector(selector)
const $$ = (selector) => [...document.querySelectorAll(selector)]
const moduleSidebar = $("#moduleSidebar")
const sidebarToggle = $("#sidebarToggle")
const sidebarResizer = $("#sidebarResizer")
window.App = window.App || {}
window.App.aiMobileOverlay = createAiMobileOverlayController({
  getLeft: () => $("#aiLeft"),
  getOverlay: () => $("#aiMobileOverlay"),
  getToggle: () => $("#aiMobileToggle"),
  isMobile: () => window.matchMedia("(max-width: 767px)").matches,
})
window.addEventListener("resize", () => {
  window.App.aiMobileOverlay.render()
})

function showToast(message) {
  const toast = $("#toast")
  toast.textContent = message
  toast.classList.add("show")
  window.clearTimeout(showToast.timer)
  showToast.timer = window.setTimeout(
    () => toast.classList.remove("show"),
    2200,
  )
}

// ── Admin panel ────────────────────────────────────────────────
var _adminKbUserId = null
var _adminPage = 1
var _adminPageSize = 15
var _adminTotalUsers = 0
var _adminSearchTerm = ""

async function fetchAdminUsers() {
  if (!isSuperAdmin()) return
  try {
    var usersService = requireAppRuntimeService("users", "listUsers")
    var contractPayload = await usersService.listUsers({
      page: _adminPage,
      page_size: _adminPageSize,
      search: _adminSearchTerm || undefined,
    })
    state.adminUsers = mapContractUsersToLegacyUsers(contractPayload)
    _adminTotalUsers =
      contractPayload.total || contractPayload.count || state.adminUsers.length
    renderAdminUsers()
    renderAdminRoles()
  } catch (e) {
    console.warn("Admin users fetch failed", e)
    showToast(e.message || "用户列表加载失败")
  }
}

function renderAdminUsers() {
  var tbody = $("#adminUserTableBody")
  if (!tbody) return
  var countEl = $("#adminUserCount")
  if (countEl) countEl.textContent = "(" + _adminTotalUsers + " 位用户)"
  if (!state.adminUsers || state.adminUsers.length === 0) {
    tbody.innerHTML =
      '<tr><td colspan="8" style="text-align:center;padding:32px;color:#8a94a6">' +
      (_adminSearchTerm ? "无匹配用户" : "暂无用户") +
      "</td></tr>"
    // Pagination
    var pageInfo = $("#adminPageInfo")
    if (pageInfo) pageInfo.textContent = "共 0 条"
    $("#adminPagePrev").disabled = true
    $("#adminPageNext").disabled = true
    return
  }
  tbody.innerHTML = state.adminUsers
    .map((u) => {
      var initial = (u.display_name || u.username || "?").charAt(0)
      var roleChips =
        u.roles.length > 0
          ? u.roles
              .map(
                (c) =>
                  '<span class="role-chip' +
                  (c === "super_admin" ? " admin-chip" : "") +
                  '">' +
                  escapeHTML(c) +
                  "</span>",
              )
              .join("")
          : '<span style="color:#8a94a6">—</span>'
      var statusHtml = u.is_active
        ? '<span class="status-pill active">启用</span>'
        : '<span class="status-pill disabled">禁用</span>'
      var lastLogin = u.last_login_at
        ? '<span class="admin-login-time" title="' +
          escapeHTML(u.last_login_at) +
          '">' +
          escapeHTML(u.last_login_at.slice(0, 16).replace("T", " ")) +
          "</span>"
        : '<span style="color:#8a94a6">从未登录</span>'
      var toggleLabel = u.is_active ? "禁用" : "启用"
      var toggleClass = u.is_active ? "btn-action-danger" : "btn-action-success"
      return (
        "<tr>" +
        '<td><span class="admin-avatar">' +
        escapeHTML(initial) +
        "</span></td>" +
        "<td><strong>" +
        escapeHTML(u.username) +
        "</strong></td>" +
        "<td>" +
        escapeHTML(u.display_name || "—") +
        "</td>" +
        "<td>" +
        (u.email
          ? '<a href="mailto:' +
            escapeHTML(u.email) +
            '">' +
            escapeHTML(u.email) +
            "</a>"
          : "—") +
        "</td>" +
        "<td>" +
        roleChips +
        "</td>" +
        "<td>" +
        statusHtml +
        "</td>" +
        "<td>" +
        lastLogin +
        "</td>" +
        '<td><div class="admin-actions">' +
        '<button class="btn btn-sm" data-admin-reset-pwd="' +
        u.id +
        '">重置密码</button>' +
        '<button class="btn btn-sm" data-admin-roles="' +
        u.id +
        '">分配角色</button>' +
        '<button class="btn btn-sm ' +
        toggleClass +
        '" data-admin-toggle="' +
        u.id +
        '">' +
        toggleLabel +
        "</button>" +
        (u.id !== (_authUser ? _authUser.id : null)
          ? '<button class="btn btn-sm btn-action-danger" data-admin-delete="' +
            u.id +
            '">删除</button>'
          : "") +
        "</div></td>" +
        "</tr>"
      )
    })
    .join("")
  // Bind role edit buttons
  $$("#adminUserTableBody [data-admin-roles]").forEach((btn) => {
    btn.addEventListener("click", () => {
      openAdminKbAuthModal(parseInt(btn.dataset.adminRoles))
    })
  })
  // Bind toggle buttons
  $$("#adminUserTableBody [data-admin-toggle]").forEach((btn) => {
    btn.addEventListener("click", () => {
      toggleAdminUserActive(parseInt(btn.dataset.adminToggle))
    })
  })
  // Bind reset-password buttons
  $$("#adminUserTableBody [data-admin-reset-pwd]").forEach((btn) => {
    btn.addEventListener("click", () => {
      openAdminResetPwdModal(parseInt(btn.dataset.adminResetPwd))
    })
  })
  $$("#adminUserTableBody [data-admin-delete]").forEach((btn) => {
    btn.addEventListener("click", () => {
      deleteAdminUser(parseInt(btn.dataset.adminDelete))
    })
  })

  // ── Pagination ──────────────────────────────────────────
  var totalPages = Math.max(1, Math.ceil(_adminTotalUsers / _adminPageSize))
  var pageInfo = $("#adminPageInfo")
  if (pageInfo) {
    var start = (_adminPage - 1) * _adminPageSize + 1
    var end = Math.min(_adminPage * _adminPageSize, _adminTotalUsers)
    pageInfo.textContent =
      "显示 " + start + "-" + end + "，共 " + _adminTotalUsers + " 条"
  }
  $("#adminPagePrev").disabled = _adminPage <= 1
  $("#adminPageNext").disabled = _adminPage >= totalPages
}

async function fetchAdminRoles() {
  frontendContractMissing({
    operationId: "missing_admin_roles_list",
    method: "GET",
    path: "/admin/roles",
    permission: "admin",
  })
  state.adminRoles = []
  renderAdminRoles()
}

function renderAdminRoles() {
  var container = $("#adminRoleList")
  if (!container) return
  if (!state.adminRoles || state.adminRoles.length === 0) {
    container.innerHTML =
      '<div style="padding:20px;text-align:center;color:#8a94a6">暂无角色数据</div>'
    return
  }
  container.innerHTML = state.adminRoles
    .map((role) => {
      var kbPerms = (role.permissions || []).filter((p) => p.startsWith("kb:"))
      var otherPerms = (role.permissions || []).filter(
        (p) => !p.startsWith("kb:"),
      )
      var userCount = (state.adminUsers || []).filter(
        (u) => u.roles && u.roles.includes(role.code),
      ).length
      var permSummary = []
      if (kbPerms.length > 0)
        permSummary.push(
          '<span class="role-perm-tag kb">知识库:' +
            kbPerms.length +
            "项</span>",
        )
      if (otherPerms.length > 0)
        permSummary.push(
          '<span class="role-perm-tag">其他:' + otherPerms.length + "项</span>",
        )
      if (permSummary.length === 0)
        permSummary.push('<span class="role-perm-tag none">无权限</span>')
      return (
        '<div class="admin-role-item">' +
        '<div class="admin-role-left"><span class="role-chip' +
        (role.code === "super_admin" ? " admin-chip" : "") +
        '" style="font-size:12px">' +
        escapeHTML(role.code) +
        "</span></div>" +
        '<div class="admin-role-body"><strong>' +
        escapeHTML(role.name) +
        "</strong>" +
        (role.description
          ? '<span class="admin-role-desc">' +
            escapeHTML(role.description) +
            "</span>"
          : "") +
        '<span class="admin-role-meta">' +
        permSummary.join("") +
        " · " +
        userCount +
        " 位用户</span></div>" +
        "</div>"
      )
    })
    .join("")
}

function openAdminUserModal() {
  $("#adminUserForm").reset()
  $("#adminUserModal").classList.add("show")
}

function closeAdminUserModal() {
  $("#adminUserModal").classList.remove("show")
}

async function createAdminUser(event) {
  event.preventDefault()
  var username = $("#adminUsername").value.trim()
  var password = $("#adminPassword").value
  var displayName = $("#adminDisplayName").value.trim() || null
  var email = $("#adminEmail").value.trim() || null
  var isAdmin = $("#adminIsAdmin").value === "admin"
  if (!username || !password) return
  if (password.length < 8) {
    showToast("密码至少 8 位")
    return
  }
  try {
    var usersService = requireAppRuntimeService("users", "createUser")
    var payload = {
      username: username,
      password: password,
      display_name: displayName,
      email: email,
      role: isAdmin ? "admin" : undefined,
    }
    await usersService.createUser(payload)
    closeAdminUserModal()
    showToast("账号已创建")
    fetchAdminUsers()
  } catch (e) {
    showToast(e.message || "创建失败")
  }
}

async function toggleAdminUserActive(userId) {
  var user = (state.adminUsers || []).find((u) => u.id === userId)
  if (!user) return
  var newActive = !user.is_active
  var actionLabel = newActive ? "启用" : "禁用"
  if (!window.confirm("确认" + actionLabel + "账号 " + user.username + "？"))
    return
  try {
    var usersService = requireAppRuntimeService("users", "updateUser")
    await usersService.updateUser(userId, { is_active: newActive })
    showToast("账号已" + actionLabel)
    fetchAdminUsers()
  } catch (e) {
    showToast(e.message || "操作失败")
  }
}

async function deleteAdminUser(userId) {
  var user = (state.adminUsers || []).find((u) => u.id === userId)
  if (!user) return
  if (
    !window.confirm(
      "确认永久删除账号 " +
        (user.display_name || user.username) +
        "？此操作不可恢复。",
    )
  )
    return
  try {
    var usersService = requireAppRuntimeService("users", "deleteUser")
    await usersService.deleteUser(userId)
    showToast("账号已删除")
    fetchAdminUsers()
  } catch (e) {
    showToast(e.message || "删除失败")
  }
}

async function openAdminKbAuthModal(userId) {
  var user = (state.adminUsers || []).find((u) => u.id === userId)
  if (!user) return
  _adminKbUserId = userId
  $("#adminKbAuthUserName").textContent = user.display_name || user.username
  if (!state.adminRoles || state.adminRoles.length === 0)
    await fetchAdminRoles()
  var roleList = $("#adminKbAuthRoleList")
  var userRoles = user.roles || []
  roleList.innerHTML = (state.adminRoles || [])
    .map((role) => {
      var allPerms = role.permissions || []
      // Show a summary of all permissions — group by resource for readability
      var permGroups = {}
      allPerms.forEach((p) => {
        var resource = p.split(":")[0]
        if (!permGroups[resource]) permGroups[resource] = []
        permGroups[resource].push(p)
      })
      var permSummary = Object.keys(permGroups)
        .sort()
        .map(
          (res) =>
            '<span class="role-perm-tag">' +
            escapeHTML(res) +
            ":" +
            permGroups[res].length +
            "项</span>",
        )
        .join(" ")
      if (!permSummary)
        permSummary = '<span class="role-perm-tag none">无权限</span>'
      var checked = userRoles.includes(role.code) ? " checked" : ""
      return (
        '<label style="display:flex;align-items:flex-start;gap:8px;padding:8px 0;border-bottom:1px solid var(--line);cursor:pointer">' +
        '<input type="checkbox" value="' +
        escapeHTML(role.code) +
        '"' +
        checked +
        ' style="margin-top:2px;flex-shrink:0">' +
        '<div style="min-width:0"><strong>' +
        escapeHTML(role.name) +
        '</strong> <span style="color:var(--subtle);font-size:11px">(' +
        escapeHTML(role.code) +
        ")</span>" +
        (role.description
          ? '<br><span style="font-size:11px;color:var(--muted)">' +
            escapeHTML(role.description) +
            "</span>"
          : "") +
        '<br><span style="font-size:11px">' +
        permSummary +
        "</span></div></label>"
      )
    })
    .join("")
  $("#adminKbAuthModal").classList.add("show")
}

function closeAdminKbAuthModal() {
  $("#adminKbAuthModal").classList.remove("show")
  _adminKbUserId = null
}

// ── Admin: reset password modal ────────────────────────────────────
var _adminResetPwdUserId = null

function openAdminResetPwdModal(userId) {
  var user = state.adminUsers.find((u) => u.id === userId)
  if (!user) return
  _adminResetPwdUserId = userId
  // Reset to step 1
  $("#adminResetPwdStep1").removeAttribute("hidden")
  $("#adminResetPwdStep2").setAttribute("hidden", "")
  $("#adminResetPwdConfirmBtn").style.display = ""
  $("#adminResetPwdDoneBtn").setAttribute("hidden", "")
  $("#adminResetPwdCancelBtn").style.display = ""
  $("#adminResetPwdUserName").textContent = user.display_name || user.username
  $("#adminPwdModeAuto").checked = true
  $("#adminResetPwdCustomField").style.display = "none"
  $("#adminResetPwdInput").value = ""
  $("#adminResetPwdOutput").textContent = ""
  $("#adminResetPwdOutputUser").textContent = ""
  $("#adminResetPwdModal").classList.add("show")

  // Radio toggle for custom password field
  $("#adminPwdModeAuto").onchange = () => {
    $("#adminResetPwdCustomField").style.display = "none"
  }
  $("#adminPwdModeCustom").onchange = () => {
    $("#adminResetPwdCustomField").style.display = ""
  }

  // Confirm button handler
  $("#adminResetPwdConfirmBtn").onclick = () => {
    resetAdminPassword()
  }

  // Copy button handler
  $("#adminResetPwdCopyBtn").onclick = () => {
    var pwd = $("#adminResetPwdOutput").textContent
    if (pwd && navigator.clipboard) {
      navigator.clipboard
        .writeText(pwd)
        .then(() => {
          showToast("密码已复制到剪贴板")
        })
        .catch(() => {
          showToast("复制失败，请手动选择复制")
        })
    }
  }

  // Done button handler
  $("#adminResetPwdDoneBtn").onclick = () => {
    closeAdminResetPwdModal()
  }
}

async function resetAdminPassword() {
  if (!_adminResetPwdUserId) return
  var isAuto = $("#adminPwdModeAuto").checked
  var customPwd = ""
  if (!isAuto) {
    customPwd = $("#adminResetPwdInput").value.trim()
    if (customPwd.length < 8) {
      showToast("密码至少需要 8 位字符")
      return
    }
  }
  try {
    var body = isAuto ? {} : { password: customPwd }
    var data = await apiJson(
      "/__frontend_missing_contract__/admin/users/" + _adminResetPwdUserId + "/reset-password-missing-contract",
      {
        method: "POST",
        body: JSON.stringify(body),
      },
    )
    // Switch to step 2
    $("#adminResetPwdStep1").setAttribute("hidden", "")
    $("#adminResetPwdStep2").removeAttribute("hidden")
    $("#adminResetPwdOutputUser").textContent = data.username
    $("#adminResetPwdOutput").textContent = data.password
    $("#adminResetPwdConfirmBtn").style.display = "none"
    $("#adminResetPwdDoneBtn").removeAttribute("hidden")
    $("#adminResetPwdCancelBtn").style.display = "none"
    showToast("密码已重置")
  } catch (e) {
    showToast(e.message || "密码重置失败")
  }
}

function closeAdminResetPwdModal() {
  $("#adminResetPwdModal").classList.remove("show")
  // Clear sensitive data from DOM
  $("#adminResetPwdOutput").textContent = ""
  $("#adminResetPwdOutputUser").textContent = ""
  $("#adminResetPwdInput").value = ""
  _adminResetPwdUserId = null
}

async function saveAdminKbAuth() {
  if (!_adminKbUserId) return
  var checked = []
  $$("#adminKbAuthRoleList input:checked").forEach((cb) => {
    checked.push(cb.value)
  })
  try {
    var usersService = requireAppRuntimeService("users", "assignRoles")
    await usersService.assignRoles(_adminKbUserId, { role_codes: checked })
    closeAdminKbAuthModal()
    showToast("角色已更新")
    fetchAdminUsers().then(() => {
      renderAdminRoles()
    })
  } catch (e) {
    showToast(e.message || "授权失败")
  }
}

// ═══════════════════════════════════════════════════════════════
// Phase 6: Admin sub-tabs + Audit / Sessions / Anomalies
// ═══════════════════════════════════════════════════════════════

var _adminSubTab = "users"
var _adminAuditPage = 1
var _adminAIQueryPage = 1
var _adminNewsPage = 1
var _serviceCategory = null
var _adminSessionPage = 1

function switchAdminSubTab(tab) {
  _adminSubTab = tab
  $$(".admin-subtab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.adminPanel === tab)
  })
  $$(".admin-panel").forEach((panel) => {
    panel.classList.toggle(
      "active",
      panel.id === "adminPanel" + tab.charAt(0).toUpperCase() + tab.slice(1),
    )
  })
  if (tab === "users") {
    fetchAdminUsers()
  } else if (tab === "audit") {
    fetchAdminAudit()
  } else if (tab === "aiquery") {
    fetchAdminAIQueries()
  } else if (tab === "sessions") {
    fetchAdminSessions()
  } else if (tab === "anomalies") {
    fetchAdminAnomalies()
  } else if (tab === "news") {
    fetchAdminNews()
  }
}

// ── Audit logs ──────────────────────────────────────────────

async function fetchAdminAudit() {
  var action = $("#adminAuditAction").value.trim()
  var decision = $("#adminAuditDecision").value
  try {
    var auditService = requireAppRuntimeService("audit", "listAuditEvents")
    var data = await auditService.listAuditEvents({
      action: action || undefined,
      decision: decision || undefined,
      page: _adminAuditPage,
      page_size: 20,
    })
    renderAdminAudit(data)
  } catch (e) {
    console.warn("Admin audit fetch failed", e)
    showToast(e.message || "审计日志加载失败")
  }
}

function renderAdminAudit(data) {
  var tbody = $("#adminAuditTableBody")
  var countEl = $("#adminAuditCount")
  if (!data || !data.items) {
    tbody.innerHTML =
      "<tr><td colspan='6' style='padding:20px;text-align:center;color:var(--muted)'>暂无数据</td></tr>"
    return
  }
  countEl.textContent = data.total + " 条"
  tbody.innerHTML = data.items
    .map((item) => {
      var time = (item.created_at || "").replace("T", " ").substring(0, 19)
      var decisionClass =
        item.decision === "deny" ? "color:var(--red)" : "color:var(--green)"
      return (
        "<tr>" +
        "<td style='white-space:nowrap;font-size:11px'>" +
        escapeHTML(time) +
        "</td>" +
        "<td style='font-size:12px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap' title='" +
        escapeHTML(item.action) +
        "'>" +
        escapeHTML(item.action) +
        "</td>" +
        "<td>" +
        (item.user_id || "-") +
        "</td>" +
        "<td style='" +
        decisionClass +
        ";font-weight:600'>" +
        escapeHTML(item.decision) +
        "</td>" +
        "<td style='font-size:11px;color:var(--muted);max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>" +
        escapeHTML(item.reason || "") +
        "</td>" +
        "<td style='font-size:11px;color:var(--subtle)'>" +
        escapeHTML(item.ip_address || "-") +
        "</td>" +
        "</tr>"
      )
    })
    .join("")
  $("#adminAuditPageInfo").textContent =
    "第 " + _adminAuditPage + " 页 / 共 " + Math.ceil(data.total / 20) + " 页"
  $("#adminAuditPagePrev").disabled = _adminAuditPage <= 1
  $("#adminAuditPageNext").disabled = _adminAuditPage * 20 >= data.total
}

function adminAuditPrev() {
  if (_adminAuditPage > 1) {
    _adminAuditPage--
    fetchAdminAudit()
  }
}
function adminAuditNext() {
  _adminAuditPage++
  fetchAdminAudit()
}

// ── AI Query logs ──────────────────────────────────────────

async function fetchAdminAIQueries() {
  var params = new URLSearchParams({ page: _adminAIQueryPage, page_size: 20 })
  var decision = $("#adminAIQueryDecision").value
  var risk = $("#adminAIQueryRisk").value
  if (decision) params.set("decision", decision)
  if (risk) params.set("risk_label", risk)
  try {
    var data = await apiJson("/__frontend_missing_contract__/admin/audit/ai-queries?" + params)
    renderAdminAIQueries(data)
  } catch (e) {
    /* silently fail */
  }
}

function renderAdminAIQueries(data) {
  var tbody = $("#adminAIQueryTableBody")
  var countEl = $("#adminAIQueryCount")
  if (!data || !data.items) {
    tbody.innerHTML =
      "<tr><td colspan='7' style='padding:20px;text-align:center;color:var(--muted)'>暂无数据</td></tr>"
    return
  }
  countEl.textContent = data.total + " 条"
  tbody.innerHTML = data.items
    .map((item) => {
      var time = (item.created_at || "").replace("T", " ").substring(0, 19)
      var decisionClass =
        item.decision === "blocked" ? "color:var(--red)" : "color:var(--green)"
      return (
        "<tr>" +
        "<td style='white-space:nowrap;font-size:11px'>" +
        escapeHTML(time) +
        "</td>" +
        "<td>" +
        (item.user_id || "-") +
        "</td>" +
        "<td style='font-size:10px;font-family:monospace;max-width:100px;overflow:hidden;text-overflow:ellipsis'>" +
        escapeHTML((item.query_hash || "").substring(0, 12)) +
        "</td>" +
        "<td style='font-size:11px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap' title='" +
        escapeHTML(item.query_snippet || "") +
        "'>" +
        escapeHTML(item.query_snippet || "") +
        "</td>" +
        "<td><span style='font-size:10px;padding:2px 5px;border-radius:4px;background:" +
        (item.risk_label === "PROMPT_INJECTION"
          ? "var(--red-soft)"
          : "var(--blue-soft)") +
        ";color:" +
        (item.risk_label === "PROMPT_INJECTION"
          ? "var(--red)"
          : "var(--blue)") +
        "'>" +
        escapeHTML(item.risk_label || "GENERAL") +
        "</span></td>" +
        "<td style='" +
        decisionClass +
        ";font-weight:600'>" +
        escapeHTML(item.decision) +
        "</td>" +
        "<td style='font-size:11px'>" +
        (item.response_time_ms || "-") +
        "</td>" +
        "</tr>"
      )
    })
    .join("")
  $("#adminAIQueryPageInfo").textContent =
    "第 " + _adminAIQueryPage + " 页 / 共 " + Math.ceil(data.total / 20) + " 页"
  $("#adminAIQueryPagePrev").disabled = _adminAIQueryPage <= 1
  $("#adminAIQueryPageNext").disabled = _adminAIQueryPage * 20 >= data.total
}

function adminAIQueryPrev() {
  if (_adminAIQueryPage > 1) {
    _adminAIQueryPage--
    fetchAdminAIQueries()
  }
}
function adminAIQueryNext() {
  _adminAIQueryPage++
  fetchAdminAIQueries()
}

// ── Session management ──────────────────────────────────────

async function fetchAdminSessions() {
  var params = new URLSearchParams({ page: _adminSessionPage, page_size: 20 })
  if ($("#adminSessionActiveOnly").checked) params.set("active_only", "true")
  try {
    var data = await apiJson("/__frontend_missing_contract__/admin/sessions?" + params)
    renderAdminSessions(data)
  } catch (e) {
    /* silently fail */
  }
}

function renderAdminSessions(data) {
  var tbody = $("#adminSessionTableBody")
  var countEl = $("#adminSessionCount")
  if (!data || !data.items) {
    tbody.innerHTML =
      "<tr><td colspan='7' style='padding:20px;text-align:center;color:var(--muted)'>暂无数据</td></tr>"
    return
  }
  countEl.textContent = data.total + " 个"
  tbody.innerHTML = data.items
    .map((item) => {
      var created = (item.created_at || "").replace("T", " ").substring(0, 16)
      var expires = (item.expires_at || "").replace("T", " ").substring(0, 16)
      var statusHtml = item.is_active
        ? "<span style='color:var(--green);font-weight:600'>● 活跃</span>"
        : "<span style='color:var(--muted)'>○ " +
          (item.revoked_at ? "已撤销" : "已过期") +
          "</span>"
      return (
        "<tr>" +
        "<td style='font-size:10px;font-family:monospace'>" +
        escapeHTML((item.id || "").substring(0, 16)) +
        "</td>" +
        "<td>" +
        escapeHTML(item.display_name || item.username || "-") +
        "</td>" +
        "<td style='font-size:11px;font-family:monospace'>" +
        escapeHTML(item.ip_address || "-") +
        "</td>" +
        "<td style='font-size:11px'>" +
        escapeHTML(created) +
        "</td>" +
        "<td style='font-size:11px'>" +
        escapeHTML(expires) +
        "</td>" +
        "<td>" +
        statusHtml +
        "</td>" +
        "<td>" +
        (item.is_active
          ? "<button class='btn' style='min-height:26px;padding:0 8px;font-size:11px' onclick='revokeAdminSession(\"" +
            item.id +
            "\")'>撤销</button>"
          : "-") +
        "</td>" +
        "</tr>"
      )
    })
    .join("")
  $("#adminSessionPageInfo").textContent =
    "第 " + _adminSessionPage + " 页 / 共 " + Math.ceil(data.total / 20) + " 页"
  $("#adminSessionPagePrev").disabled = _adminSessionPage <= 1
  $("#adminSessionPageNext").disabled = _adminSessionPage * 20 >= data.total
}

async function revokeAdminSession(sessionId) {
  if (!confirm("确认撤销此会话？用户将被强制登出。")) return
  try {
    await apiJson("/__frontend_missing_contract__/admin/sessions/" + sessionId, { method: "DELETE" })
    showToast("会话已撤销")
    fetchAdminSessions()
  } catch (e) {
    showToast(e.message || "撤销失败")
  }
}

function adminSessionPrev() {
  if (_adminSessionPage > 1) {
    _adminSessionPage--
    fetchAdminSessions()
  }
}
function adminSessionNext() {
  _adminSessionPage++
  fetchAdminSessions()
}

// ── Anomaly statistics ──────────────────────────────────────

async function fetchAdminAnomalies() {
  try {
    var data = await apiJson("/__frontend_missing_contract__/admin/anomalies")
    renderAdminAnomalies(data)
  } catch (e) {
    /* silently fail */
  }
}

function renderAdminAnomalies(data) {
  $("#anomTotalUsers").textContent = data.total_users
  $("#anomActiveUsers").textContent = data.active_users
  $("#anomDisabledUsers").textContent = data.disabled_users
  $("#anomActiveSessions").textContent = data.active_sessions
  $("#anomFailedLogins").textContent = data.recent_failed_logins_24h
  $("#anom403").textContent = data.recent_403_24h
  $("#anomAIBlocks").textContent = data.recent_ai_blocks_24h
  $("#anomInjections").textContent = data.recent_injections_24h
  // Update badge on anomaly tab
  var totalWarnings =
    data.recent_failed_logins_24h +
    data.recent_403_24h +
    data.recent_ai_blocks_24h +
    data.recent_injections_24h
  var badge = $("#adminAnomalyBadge")
  if (totalWarnings > 0) {
    badge.textContent = totalWarnings > 99 ? "99+" : totalWarnings
    badge.hidden = false
  } else {
    badge.hidden = true
  }
}

// ── Admin news CRUD ─────────────────────────────────────────

async function fetchAdminNews() {
  try {
    var enterpriseService = requireAppRuntimeService(
      "enterprise",
      "listAnnouncements",
    )
    var data = mapAnnouncementsToAdminNews(
      await enterpriseService.listAnnouncements({
        page: _adminNewsPage,
        page_size: 20,
      }),
    )
    renderAdminNews(data)
  } catch (e) {
    /* silently fail */
  }
}

function renderAdminNews(data) {
  var tbody = $("#adminNewsTableBody")
  if (!tbody) return
  state.adminNews = data.items || []
  tbody.innerHTML =
    state.adminNews
      .map(
        (item) =>
          "<tr>" +
          "<td>" +
          escapeHTML(item.title) +
          "</td>" +
          "<td>" +
          escapeHTML(item.source) +
          "</td>" +
          "<td>" +
          escapeHTML(item.category) +
          "</td>" +
          "<td>" +
          (item.published_at ? item.published_at.slice(0, 16) : "") +
          "</td>" +
          "<td>" +
          (item.pinned ? "是" : "否") +
          "</td>" +
          '<td><button class="card-link" data-news-edit="' +
          item.id +
          '">编辑</button> ' +
          '<button class="card-link danger" data-news-delete="' +
          item.id +
          '">删除</button></td>' +
          "</tr>",
      )
      .join("") ||
    '<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:20px">暂无资讯</td></tr>'

  var total = data.total || 0
  var maxPage = Math.max(1, Math.ceil(total / 20))
  $("#adminNewsPageInfo").textContent =
    "第 " + _adminNewsPage + " / " + maxPage + " 页，共 " + total + " 条"
  $("#adminNewsPagePrev").disabled = _adminNewsPage <= 1
  $("#adminNewsPageNext").disabled = _adminNewsPage >= maxPage

  // Wire edit/delete buttons
  $$("[data-news-edit]").forEach((btn) => {
    btn.onclick = () => {
      openNewsModal(parseInt(btn.dataset.newsEdit))
    }
  })
  $$("[data-news-delete]").forEach((btn) => {
    btn.onclick = () => {
      deleteNewsById(parseInt(btn.dataset.newsDelete))
    }
  })
}

function openNewsModal(newsId) {
  var modal = $("#adminNewsModal")
  if (!modal) return
  $("#adminNewsModalTitle").textContent = newsId ? "编辑资讯" : "新建资讯"
  $("#adminNewsDeleteBtn").hidden = !newsId
  if (newsId) {
    var item = (state.adminNews || []).find((n) => n.id === newsId)
    if (item) {
      $("#adminNewsTitle").value = item.title || ""
      $("#adminNewsSource").value = item.source || ""
      $("#adminNewsCategory").value = item.category || ""
      $("#adminNewsBody").value = item.body || ""
      $("#adminNewsPinned").checked = item.pinned
      $("#adminNewsPublishedAt").value = (item.published_at || "").slice(0, 16)
    }
    $("#adminNewsForm").dataset.editingId = newsId
  } else {
    $("#adminNewsForm").reset()
    $("#adminNewsForm").dataset.editingId = ""
  }
  modal.classList.add("show")
}

async function deleteNewsById(newsId) {
  if (!confirm("确定要撤回这条资讯吗？")) return
  try {
    var enterpriseService = requireAppRuntimeService(
      "enterprise",
      "withdrawAnnouncement",
    )
    await enterpriseService.withdrawAnnouncement(newsId)
    showToast("资讯已撤回")
    fetchAdminNews()
  } catch (e) {
    showToast("撤回失败")
  }
}

async function createAdminNews(payload) {
  var enterpriseService = requireAppRuntimeService(
    "enterprise",
    "createPublishedAnnouncement",
  )
  var announcement = await enterpriseService.createPublishedAnnouncement(
    mapAdminNewsToAnnouncementPayload(payload),
  )
  if (payload.pinned && announcement?.id) {
    announcement = await enterpriseService.pinAnnouncement(announcement.id, {
      isPinned: true,
    })
  }
  return announcement
}

async function updateAdminNews(newsId, payload) {
  var enterpriseService = requireAppRuntimeService(
    "enterprise",
    "updateAnnouncement",
  )
  return enterpriseService.updateAnnouncement(
    newsId,
    mapAdminNewsToAnnouncementPayload(payload),
  )
}

function canPublishNotices() {
  if (!_authUser) return false
  return (
    (_authUser.roles || []).some((role) =>
      role === "super_admin" || role === "admin",
    ) ||
    (_authUser.permissions || []).indexOf("notice:publish") !== -1
  )
}

function openNoticePublishModal() {
  var modal = $("#noticePublishModal")
  if (!modal) return
  var now = new Date()
  var pad = (n) => String(n).padStart(2, "0")
  $("#noticePublishPublishedAt").value =
    now.getFullYear() +
    "-" +
    pad(now.getMonth() + 1) +
    "-" +
    pad(now.getDate()) +
    "T" +
    pad(now.getHours()) +
    ":" +
    pad(now.getMinutes())
  $("#noticePublishForm").reset()
  modal.classList.add("show")
}

async function publishNoticeRemote(payload) {
  var enterpriseService = requireAppRuntimeService(
    "enterprise",
    "createPublishedAnnouncement",
  )
  return enterpriseService.createPublishedAnnouncement({
    content: payload.body,
    summary: payload.body,
    title: payload.title,
  })
}

function updatePlatformTime() {
  const now = new Date()
  const weekdays = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]
  const dateText = `${weekdays[now.getDay()]}，${now.getFullYear()} 年 ${now.getMonth() + 1} 月 ${now.getDate()} 日`
  const timeText = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}:${String(now.getSeconds()).padStart(2, "0")}`
  const clock = $("#platformClock")
  if (clock) {
    clock.dateTime = now.toISOString()
    clock.textContent = `${dateText} ${timeText}`
  }
  const summary = $("#workspaceTodaySummary")
  if (summary) summary.textContent = `${dateText} · 驾驶舱今日概览`
}

function setSidebarCollapsed(collapsed) {
  moduleSidebar.classList.toggle("collapsed", collapsed)
  document.body.classList.toggle("sidebar-collapsed", collapsed)
  sidebarToggle.setAttribute("aria-expanded", String(!collapsed))
  sidebarToggle.setAttribute(
    "aria-label",
    collapsed ? "展开模块侧边栏" : "收起模块侧边栏",
  )
  sidebarResizer.setAttribute("aria-hidden", String(collapsed))
}

function setSidebarWidth(width) {
  const nextWidth = Math.max(180, Math.min(380, width))
  document.documentElement.style.setProperty("--sidebar", `${nextWidth}px`)
  sidebarResizer.setAttribute("aria-valuenow", String(nextWidth))
}

function getViewLabel(view) {
  var customWebsite = getCustomWebsiteForView(view)
  if (customWebsite) return customWebsite.name
  if (view === customWebsiteNewView) return "添加自定义网站"
  var labels = {
    workspace: "驾驶舱",
    portal: "企业门户",
    knowledge: "AI 服务",
    calendar: "日历",
    feishu: "飞书",
    dingtalk: "钉钉",
    admin: "账号管理",
    subsystem: "子系统",
    "notice-center": "公告中心",
    "document-center": "文档中心",
    "resource-center": "资源库",
    "service-center": "服务中心",
    "news-center": "资讯中心",
    "portal-dashboard": "经营看板",
    "org-structure": "组织架构",
  }
  return labels[view] || view
}

function getCustomWebsiteForView(view) {
  return state.customWebsites.find(
    (site) => getCustomWebsiteViewId(site.id) === view,
  )
}

function isCustomWebsiteView(view) {
  return isCustomWebsiteViewFor(state.customWebsites, view)
}

function isAllowedView(view) {
  return (
    validViews.has(view) || view === customWebsiteNewView || isCustomWebsiteView(view)
  )
}

var viewEnterHooks = {
  admin: () => {
    switchAdminSubTab(_adminSubTab)
  },
  knowledge: () => {
    renderAiWorkbench()
  },
}

function openTab(view, opts) {
  opts = opts || {}
  if (!isAllowedView(view)) return
  state.activeView = view
  state.activeSubTab = null
  _saveScoped(viewStorageKey, view)
  try {
    window.localStorage.setItem(viewStorageKey, view)
  } catch (e) {}
  var exists = state.tabs.some((t) => t.view === view)
  if (!exists) {
    state.tabs.push({ view: view, label: getViewLabel(view) })
  }
  renderTabs()
  $$(".view").forEach((section) => {
    section.classList.toggle("active", section.id === view)
  })
  syncSidebarActive(view)
  var hook = viewEnterHooks[view]
  if (hook) {
    hook()
  }
  if (!opts.isInit) {
    window.scrollTo({ top: 0, behavior: "smooth" })
  }
}

function openSubTab(parentView, scrollTarget, label) {
  if (!parentView || !scrollTarget) return
  // Switch to the parent view first
  if (state.activeView !== parentView) {
    openTab(parentView, { isInit: true })
  }
  // Create compound key for this submenu tab
  var compoundView = parentView + "#" + scrollTarget
  var exists = state.tabs.some((t) => t.view === compoundView)
  if (!exists) {
    state.tabs.push({
      view: compoundView,
      label: label,
      scrollTarget: scrollTarget,
      parentView: parentView,
    })
  }
  state.activeView = parentView
  state.activeSubTab = compoundView
  _saveScoped(viewStorageKey, parentView)
  try {
    window.localStorage.setItem(viewStorageKey, parentView)
  } catch (e) {}
  renderTabs()
  // Scroll to the target section
  setTimeout(() => {
    var section = document.getElementById(scrollTarget)
    if (section) {
      section.scrollIntoView({ behavior: "smooth", block: "start" })
      // Flash highlight the target card
      section.classList.add("cockpit-flash")
      section.addEventListener("animationend", function _onFlashEnd() {
        section.classList.remove("cockpit-flash")
        section.removeEventListener("animationend", _onFlashEnd)
      })
      // Highlight sidebar link
      $$("#sidebarContent .side-link").forEach((item) => {
        item.classList.remove("active")
      })
      var link = document.querySelector(
        '.side-link[data-scroll-target="' + scrollTarget + '"]',
      )
      if (link) link.classList.add("active")
    }
  }, 100)
}

function closeTab(view) {
  var idx = -1
  for (var i = 0; i < state.tabs.length; i++) {
    if (state.tabs[i].view === view) {
      idx = i
      break
    }
  }
  if (idx === -1) return
  var closedTab = state.tabs[idx]
  var isCompound = closedTab.scrollTarget != null
  state.tabs.splice(idx, 1)
  if (
    state.activeView === (isCompound ? closedTab.parentView : view) ||
    view === state.activeView
  ) {
    var next = state.tabs[Math.min(idx, state.tabs.length - 1)]
    if (next) {
      if (next.scrollTarget != null) {
        openSubTab(next.parentView, next.scrollTarget, next.label)
      } else {
        openTab(next.view)
      }
    } else {
      openTab("workspace")
    }
  }
  renderTabs()
}

function renderTabs() {
  var container = document.getElementById("tabBar")
  if (!container) return
  var html = ""
  state.tabs.forEach((tab) => {
    var isActive = state.activeSubTab
      ? tab.view === state.activeSubTab
      : tab.view === state.activeView
    var customTab = isCustomWebsiteView(tab.view)
    html +=
      '<div class="tab-item' +
      (isActive ? " active" : "") +
      '"><button class="tab-item-label" data-tab-view="' +
      escapeHTML(tab.view) +
      '"' +
      (customTab ? ' aria-label="切换至' + escapeHTML(tab.label) + '"' : "") +
      ">" +
      escapeHTML(tab.label) +
      '</button><button class="tab-close" data-close-tab="' +
      escapeHTML(tab.view) +
      '" aria-label="关闭' +
      escapeHTML(tab.label) +
      '">×</button></div>'
  })
  container.innerHTML = html
  container.querySelectorAll(".tab-item-label").forEach((btn) => {
    btn.addEventListener("click", () => {
      var view = btn.dataset.tabView
      var hashIdx = view.indexOf("#")
      if (hashIdx !== -1) {
        var parentView = view.substring(0, hashIdx)
        var scrollTarget = view.substring(hashIdx + 1)
        // Find the tab to get its label
        var tab = state.tabs.find((t) => t.view === view)
        openSubTab(parentView, scrollTarget, tab ? tab.label : "")
      } else {
        openTab(view)
      }
    })
  })
  container.querySelectorAll(".tab-close").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation()
      closeTab(btn.dataset.closeTab)
    })
  })
}

function setView(view, opts = {}) {
  openTab(view, opts)
}

function syncSubLinkActive(attr, value) {
  $$("#sidebarContent .side-link").forEach((btn) => {
    if (btn.dataset[attr] !== undefined)
      btn.classList.toggle("active", btn.dataset[attr] === value)
  })
}

function syncSidebarActive(view) {
  $$(".nav-main").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === view)
  })
  // Map sub-views to parent nav items for accordion expansion
  var navView = view
  if (
    view === "feishu" ||
    view === "dingtalk" ||
    view === customWebsiteNewView ||
    isCustomWebsiteView(view)
  ) {
    navView = "work-platform"
  }
  var navItem = document.querySelector('.nav-item[data-nav="' + navView + '"]')
  if (navItem && !navItem.classList.contains("expanded")) {
    $$(".nav-item").forEach((item) => {
      item.classList.remove("expanded")
    })
    navItem.classList.add("expanded")
    state.expandedNav = navView
  }
  // Highlight active sub-link with data-view-link
  $$("#sidebarContent .side-link").forEach((btn) => {
    if (btn.dataset.viewLink !== undefined)
      btn.classList.toggle("active", btn.dataset.viewLink === view)
  })
  $$("[data-custom-website-id]").forEach((btn) => {
    btn.classList.toggle(
      "active",
      getCustomWebsiteViewId(btn.dataset.customWebsiteId) === view,
    )
  })
  var customWebsiteAdd = $("#customWebsiteAdd")
  if (customWebsiteAdd) {
    customWebsiteAdd.classList.toggle("active", view === customWebsiteNewView)
  }
  syncSubLinkActive("kbSubLink", state.ai.subMenu)
  syncSubLinkActive("adminSub", _adminSubTab)
}

function scrollToModule(target, button) {
  const section = document.getElementById(target)
  if (!section) return
  $$("#sidebarContent .side-link").forEach((item) =>
    item.classList.remove("active"),
  )
  button.classList.add("active")
  section.scrollIntoView({ behavior: "smooth", block: "start" })
}

function bindSidebarHandlers() {
  // nav-main click → open tab
  $$(".nav-main").forEach((btn) => {
    btn.addEventListener("click", () => {
      openTab(btn.dataset.view)
    })
  })
  // nav-expand click → toggle accordion
  $$(".nav-expand").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation()
      var navItem = btn.closest(".nav-item")
      var wasExpanded = navItem.classList.contains("expanded")
      // collapse all
      $$(".nav-item").forEach((item) => {
        item.classList.remove("expanded")
      })
      if (!wasExpanded) {
        navItem.classList.add("expanded")
        state.expandedNav = navItem.dataset.nav
      } else {
        state.expandedNav = null
      }
    })
  })
  // submenu side-link clicks
  $$("#sidebarContent .side-link").forEach((button) => {
    button.addEventListener("click", () => {
      button.title = button.textContent.trim()
      if (button.dataset.kbSubLink) {
        if (state.activeView !== "knowledge") openTab("knowledge")
        switchAiSubMenu(button.dataset.kbSubLink)
        return
      }
      if (button.dataset.adminSub) {
        switchAdminSubTab(button.dataset.adminSub)
        return
      }
      if (button.dataset.viewLink) {
        setView(button.dataset.viewLink)
        return
      }
      if (button.dataset.openAssetCenter) {
        renderAssetCenter(button.dataset.openAssetCenter)
        return
      }
      if (button.dataset.scrollTarget) {
        var parentItem = button.closest(".nav-item")
        var parentView = parentItem ? parentItem.dataset.nav : null
        var target = button.dataset.scrollTarget
        var label = button.textContent.trim()
        // Create or activate a submenu tab for this section
        openSubTab(parentView, target, label)
      }
    })
  })
  $$("#sidebarContent .side-link").forEach((button) => {
    button.title = button.textContent.trim()
  })
}

function escapeHTML(value) {
  return String(value).replace(
    /[&<>"']/g,
    (char) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[char],
  )
}

function saveTasks() {
  var data = JSON.stringify(state.tasks)
  // Save to user-scoped key first, then unscoped as fallback
  _saveScoped(taskStorageKey, data)
  try {
    window.localStorage.setItem(taskStorageKey, data)
  } catch (e) {}
  scheduleNextTaskDeadlineRefresh()
}

async function createTaskRemote(title, tag, deadline) {
  var workItems = requireAppRuntimeService("workItems", "createWorkItem")
  return mapWorkItemToLegacyTask(
    await workItems.createWorkItem(
      mapLegacyTaskToWorkItemCreate(title, tag, deadline),
    ),
  )
}

async function updateTaskRemote(task) {
  var workItems = requireAppRuntimeService("workItems", "updateWorkItem")
  var updated = await workItems.updateWorkItem(
    Number(task.id),
    mapLegacyTaskToWorkItemUpdate(task),
  )
  if (workItems.updateWorkItemStatus) {
    updated = await workItems.updateWorkItemStatus(Number(task.id), {
      status: task.done ? "completed" : "pending",
    })
  }
  return mapWorkItemToLegacyTask(updated)
}

async function deleteTaskRemote(taskId) {
  var workItems = requireAppRuntimeService("workItems", "deleteWorkItem")
  return workItems.deleteWorkItem(Number(taskId))
}

async function clearDoneTasksRemote() {
  var workItems = requireAppRuntimeService("workItems", "deleteWorkItem")
  var doneIds = state.tasks
    .filter((task) => task.done)
    .map((task) => Number(task.id))
    .filter((id) => Number.isFinite(id))
  await Promise.all(doneIds.map((id) => workItems.deleteWorkItem(id)))
}

function saveEvents() {
  var data = JSON.stringify(state.events)
  _saveScoped(eventStorageKey, data)
  try {
    window.localStorage.setItem(eventStorageKey, data)
  } catch (e) {}
}

async function createEventRemote(event) {
  return calendarEventContractMissing({
    operation: "create",
    payload: event,
  })
}

async function updateEventRemote(event) {
  return calendarEventContractMissing({
    eventId: event.id,
    operation: "update",
    payload: {
      title: event.title,
      date: event.date,
      tone: event.tone,
    },
  })
}

async function deleteEventRemote(eventId) {
  return calendarEventContractMissing({
    eventId,
    operation: "delete",
  })
}

async function calendarEventContractMissing(context) {
  console.warn("Calendar event API contract missing.", context)
  throw new Error("日程接口契约缺失，已记录为后端依赖")
}

// ── 驾驶舱 cockpit ──────────────────────────────────────────────
var COCKPIT_KPI_CARDS = {
  business: {
    title: "经营数据",
    metrics: [
      {
        label: "年度营收目标完成率",
        value: "68%",
        trend: "up",
        trendText: "+12%",
      },
      {
        label: "本月合同金额",
        value: "¥1,280万",
        trend: "up",
        trendText: "+8%",
      },
      { label: "应收超期", value: "23笔", trend: "down", trendText: "−5%" },
      { label: "成本利润率", value: "21.4%", trend: "up", trendText: "+1.8pt" },
    ],
    detail: [
      { label: "Q1 营收", value: "¥3,420万" },
      { label: "Q2 营收", value: "¥4,180万" },
      { label: "年度目标", value: "¥1.5亿" },
      { label: "毛利率", value: "38.2%" },
      { label: "净利率", value: "12.7%" },
      { label: "应收账款周转天数", value: "47天" },
    ],
  },
  staff: {
    title: "人员统计",
    metrics: [
      { label: "在职员工", value: "1,286人", trend: "up", trendText: "+34" },
      { label: "本月入职", value: "34人", trend: "up", trendText: "+5" },
      { label: "离职率", value: "1.2%", trend: "down", trendText: "−0.3%" },
      { label: "培训覆盖率", value: "87%", trend: "up", trendText: "+4%" },
    ],
    detail: [
      { label: "正式员工", value: "1,128人" },
      { label: "实习生", value: "158人" },
      { label: "研发人员", value: "346人" },
      { label: "销售人员", value: "218人" },
      { label: "本月离职", value: "4人" },
      { label: "在招岗位", value: "23个" },
    ],
  },
  market: {
    title: "市场情况",
    metrics: [
      { label: "新增客户", value: "46家", trend: "up", trendText: "+12" },
      { label: "线索转化率", value: "9.6%", trend: "up", trendText: "+1.2%" },
      { label: "客户满意度", value: "92分", trend: "up", trendText: "+2" },
      { label: "市场份额", value: "14.2%", trend: "down", trendText: "−0.5%" },
    ],
    detail: [
      { label: "活跃客户数", value: "342家" },
      { label: "本月线索数", value: "480条" },
      { label: "本月成单数", value: "46单" },
      { label: "客单价", value: "¥27.8万" },
      { label: "客户留存率", value: "94.3%" },
      { label: "NPS 净推荐值", value: "68" },
    ],
  },
  production: {
    title: "生产情况",
    metrics: [
      { label: "计划完成率", value: "96.5%", trend: "up", trendText: "+1.2%" },
      { label: "订单准时交付率", value: "89%", trend: "up", trendText: "+3%" },
      { label: "设备稼动率", value: "78%", trend: "down", trendText: "−4%" },
      { label: "不良率", value: "0.8%", trend: "down", trendText: "−0.2%" },
    ],
    detail: [
      { label: "本月产量", value: "48,200件" },
      { label: "产能利用率", value: "82%" },
      { label: "设备总数", value: "156台" },
      { label: "维修停机时间", value: "127h" },
      { label: "质检合格率", value: "99.2%" },
      { label: "返工率", value: "1.4%" },
    ],
  },
  other: {
    title: "其他关键指标",
    metrics: [
      {
        label: "本月支出预算执行",
        value: "61%",
        trend: "up",
        trendText: "+3%",
      },
      { label: "能耗同比", value: "−4%", trend: "down", trendText: "↓" },
      { label: "安全事件", value: "0起", trend: "down", trendText: "—" },
      { label: "项目按期率", value: "83%", trend: "up", trendText: "+5%" },
    ],
    detail: [
      { label: "IT 工单处理数", value: "127单" },
      { label: "知识库文档数", value: "1,240篇" },
      { label: "平台月活用户", value: "892人" },
      { label: "日均访问量", value: "2,340次" },
      { label: "系统正常运行率", value: "99.97%" },
      { label: "环保达标率", value: "100%" },
    ],
  },
}
var COCKPIT_DECISION_PREVIEW_LIMIT = 5
var COCKPIT_SAMPLE_DECISIONS = [
  {
    id: "sample-1",
    title: "预算审批链路压缩",
    summary: "定时任务发现近期预算审批平均耗时偏高，建议先处理金额小且风险低的审批节点。",
    action: "将 5 万元以下低风险预算审批改为部门负责人单点确认。",
    confidence: 86,
    sourceTask: "预算审批效率巡检",
    generatedAt: "2026-08-14T08:30:00",
    status: "pending",
  },
  {
    id: "sample-2",
    title: "华东区仓储排班调整",
    summary: "仓储出库峰值集中在周三和周五，当前排班与峰值不匹配。",
    action: "将周三、周五晚班各增加 1 名复核人员。",
    confidence: 78,
    sourceTask: "仓储履约日报",
    generatedAt: "2026-08-14T07:50:00",
    status: "pending",
  },
  {
    id: "sample-3",
    title: "新员工培训材料更新",
    summary: "入职问答中关于考勤、报销和安全培训的问题重复出现。",
    action: "把高频问答沉淀到入职手册并同步到 AI 服务经验方法。",
    confidence: 82,
    sourceTask: "员工服务问答复盘",
    generatedAt: "2026-08-13T18:10:00",
    status: "approved",
    approvedAt: "2026-08-14T09:05:00",
  },
  {
    id: "sample-4",
    title: "CRM 客户跟进提醒",
    summary: "部分商机超过 7 天未记录跟进，预计影响下周转化。",
    action: "把 A 类商机未跟进客户推送给销售主管复核。",
    confidence: 74,
    sourceTask: "销售机会健康度检查",
    generatedAt: "2026-08-13T16:40:00",
    status: "pending",
  },
  {
    id: "sample-5",
    title: "安全整改验收排序",
    summary: "多个整改项同时到期，风险等级和现场影响范围不同。",
    action: "优先验收消防通道和电气线路相关整改项。",
    confidence: 91,
    sourceTask: "安全整改追踪",
    generatedAt: "2026-08-13T11:20:00",
    status: "regenerating",
  },
  {
    id: "sample-6",
    title: "服务台知识库补全",
    summary: "服务台重复工单集中在账号重置和 VPN 接入。",
    action: "暂不处理，本轮需求已归档。",
    confidence: 63,
    sourceTask: "IT 工单周报",
    generatedAt: "2026-08-12T15:20:00",
    status: "rejected",
    rejectionReason: "暂无需求",
    rejectedAt: "2026-08-13T09:30:00",
  },
]
var COCKPIT_STATUS_LABELS = {
  pending: "待决策",
  approved: "已同意",
  rejected: "已驳回",
  changes_requested: "需修改",
  regenerating: "重新生成中",
  superseded: "已替代",
}
var COCKPIT_PRESET_ENTRIES = [
  { title: "新员工入职手册", desc: "入职流程与制度", tone: "app-blue" },
  { title: "培训系统", desc: "在线学习平台", tone: "app-purple" },
  { title: "绩效考核", desc: "绩效评估与管理", tone: "app-orange" },
  { title: "外来人 FAQ", desc: "常见问题解答", tone: "app-green" },
  { title: "定时任务看板", desc: "查看自动任务", tone: "app-cyan" },
  { title: "考勤与请假", desc: "考勤打卡与请假申请", tone: "app-cyan" },
  { title: "劳保用品申领", desc: "安全防护用品管理", tone: "app-red" },
  { title: "员工档案", desc: "个人信息与档案查询", tone: "app-blue" },
  { title: "安全培训", desc: "安全生产教育课程", tone: "app-green" },
]

// Seed cockpit entries with presets on first load
if (state.cockpitEntries.length === 0) {
  state.cockpitEntries = COCKPIT_PRESET_ENTRIES.map((e) => Object.assign({}, e))
  _saveScoped(cockpitEntriesKey, JSON.stringify(state.cockpitEntries))
}

function ensureCockpitPresetEntries() {
  var changed = false
  COCKPIT_PRESET_ENTRIES.forEach((preset) => {
    var exists = state.cockpitEntries.some((entry) => entry.title === preset.title)
    if (!exists && preset.title === "定时任务看板") {
      state.cockpitEntries.push(Object.assign({}, preset))
      changed = true
    }
  })
  if (changed) _saveScoped(cockpitEntriesKey, JSON.stringify(state.cockpitEntries))
}

ensureCockpitPresetEntries()

function renderCockpitKPI() {
  var grid = $("#cockpitKpiGrid")
  if (!grid) return
  var allCards = grid.querySelectorAll("[data-kpi]")
  allCards.forEach((card) => {
    var kpiId = card.dataset.kpi
    var visible = state.cockpitKpiLayout.indexOf(kpiId) !== -1
    card.style.display = visible ? "" : "none"
    if (!visible) return
    var config = COCKPIT_KPI_CARDS[kpiId]
    if (!config) return
    var head = card.querySelector(".cockpit-kpi-head")
    if (head) {
      var titleSpan = head.querySelector(".cockpit-kpi-title")
      if (titleSpan) titleSpan.textContent = config.title
    }
    var metricsEl = card.querySelector("[data-kpi-metrics]")
    if (metricsEl) {
      metricsEl.innerHTML = config.metrics
        .map((m) => {
          var trendHtml = ""
          if (m.trend === "up")
            trendHtml =
              '<span class="trend-up">↑ ' + escapeHTML(m.trendText) + "</span>"
          else if (m.trend === "down")
            trendHtml =
              '<span class="trend-down">↓ ' +
              escapeHTML(m.trendText) +
              "</span>"
          return (
            '<div class="cockpit-kpi-metric"><strong>' +
            escapeHTML(m.value) +
            "</strong><span>" +
            escapeHTML(m.label) +
            trendHtml +
            "</span></div>"
          )
        })
        .join("")
    }
    // expanded class
    if (state.cockpitExpandedKpi === kpiId) {
      card.classList.add("expanded")
    } else {
      card.classList.remove("expanded")
    }
  })
  renderCockpitKpiDetail()
}

function renderCockpitKpiDetail() {
  var detail = $("#cockpitKpiDetail")
  if (!detail) return
  if (!state.cockpitExpandedKpi) {
    detail.hidden = true
    return
  }
  var config = COCKPIT_KPI_CARDS[state.cockpitExpandedKpi]
  if (!config) {
    detail.hidden = true
    return
  }
  detail.hidden = false
  detail.innerHTML =
    '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">' +
    "<strong>" +
    escapeHTML(config.title) +
    " · 详细数据</strong>" +
    '<button class="card-link" id="cockpitCloseDetail">收起</button></div>' +
    config.detail
      .map(
        (d) =>
          '<div class="cockpit-kpi-detail-item"><label>' +
          escapeHTML(d.label) +
          "</label><strong>" +
          escapeHTML(d.value) +
          "</strong></div>",
      )
      .join("")
  var closeBtn = $("#cockpitCloseDetail")
  if (closeBtn) {
    closeBtn.onclick = () => {
      state.cockpitExpandedKpi = null
      renderCockpitKPI()
    }
  }
}

function renderCockpitComponentPanel() {
  var panel = $("#cockpitComponentPanel")
  if (!panel) return
  if (panel.hidden) {
    panel.hidden = false
  } else {
    panel.hidden = true
    return
  }
  var allIds = ["business", "staff", "market", "production", "other"]
  panel.innerHTML =
    '<div style="font-weight:700;font-size:13px;margin-bottom:6px;padding:0 8px">选择显示组件</div>' +
    allIds
      .map((id, idx) => {
        var cfg = COCKPIT_KPI_CARDS[id]
        var checked = state.cockpitKpiLayout.indexOf(id) !== -1
        var orderIdx = state.cockpitKpiLayout.indexOf(id)
        return (
          '<div class="cockpit-component-item">' +
          '<input type="checkbox" ' +
          (checked ? "checked" : "") +
          ' data-cockpit-toggle="' +
          id +
          '" />' +
          "<label>" +
          escapeHTML(cfg.title) +
          "</label>" +
          (checked && orderIdx > 0
            ? '<button class="cockpit-comp-order-btn" data-cockpit-up="' +
              id +
              '" title="上移">↑</button>'
            : '<span style="width:24px"></span>') +
          (checked && orderIdx < state.cockpitKpiLayout.length - 1
            ? '<button class="cockpit-comp-order-btn" data-cockpit-down="' +
              id +
              '" title="下移">↓</button>'
            : '<span style="width:24px"></span>') +
          "</div>"
        )
      })
      .join("")
  // toggle checkboxes
  panel.querySelectorAll("[data-cockpit-toggle]").forEach((cb) => {
    cb.onchange = () => {
      var id = cb.dataset.cockpitToggle
      if (cb.checked) {
        if (state.cockpitKpiLayout.indexOf(id) === -1)
          state.cockpitKpiLayout.push(id)
      } else {
        state.cockpitKpiLayout = state.cockpitKpiLayout.filter((x) => x !== id)
      }
      renderCockpitKPI()
      renderCockpitComponentPanel()
    }
  })
  // up buttons
  panel.querySelectorAll("[data-cockpit-up]").forEach((btn) => {
    btn.onclick = () => {
      var id = btn.dataset.cockpitUp
      var idx = state.cockpitKpiLayout.indexOf(id)
      if (idx > 0) {
        var tmp = state.cockpitKpiLayout[idx - 1]
        state.cockpitKpiLayout[idx - 1] = id
        state.cockpitKpiLayout[idx] = tmp
      }
      renderCockpitKPI()
      renderCockpitComponentPanel()
    }
  })
  // down buttons
  panel.querySelectorAll("[data-cockpit-down]").forEach((btn) => {
    btn.onclick = () => {
      var id = btn.dataset.cockpitDown
      var idx = state.cockpitKpiLayout.indexOf(id)
      if (idx < state.cockpitKpiLayout.length - 1) {
        var tmp = state.cockpitKpiLayout[idx + 1]
        state.cockpitKpiLayout[idx + 1] = id
        state.cockpitKpiLayout[idx] = tmp
      }
      renderCockpitKPI()
      renderCockpitComponentPanel()
    }
  })
}

var _cockpitDecisionFetchPromise = null

function getDecisionItems(payload) {
  if (Array.isArray(payload)) return payload
  if (Array.isArray(payload?.items)) return payload.items
  if (Array.isArray(payload?.decisions)) return payload.decisions
  return []
}

function normalizeCockpitDecision(item) {
  var rawStatus = item.status || item.decision_status || "pending"
  var status =
    rawStatus === "done"
      ? "approved"
      : rawStatus === "processing"
        ? "regenerating"
        : rawStatus
  return {
    id: item.id,
    taskId: item.task_id || item.taskId || null,
    title: item.title || item.name || "未命名决策",
    summary: item.summary || item.description || item.content || "",
    action:
      item.action ||
      item.recommended_action ||
      item.recommendedAction ||
      item.suggestion ||
      "",
    confidence:
      typeof item.confidence === "number"
        ? Math.round(item.confidence > 1 ? item.confidence : item.confidence * 100)
        : null,
    sourceTask:
      item.sourceTask ||
      item.source_task ||
      item.source_task_name ||
      item.task_name ||
      "",
    generatedAt: item.generatedAt || item.generated_at || item.created_at || "",
    status: COCKPIT_STATUS_LABELS[status] ? status : "pending",
    approvedAt: item.approvedAt || item.approved_at || "",
    rejectedAt: item.rejectedAt || item.rejected_at || "",
    regenerationRunId:
      item.regenerationRunId || item.regeneration_run_id || null,
    rejectionReason:
      item.rejectionReason || item.rejection_reason || item.reject_reason || "",
    regenerationError:
      item.regenerationError || item.regeneration_error || "",
  }
}

function normalizeCockpitPipelineTask(item) {
  return {
    id: item.id,
    name: item.title || item.name || "未命名定时任务",
    schedule: item.schedule || "",
    timezone: item.timezone || "Asia/Shanghai",
    nextRunAt: item.next_run_at || item.nextRunAt || "",
    status: item.status || "ready",
  }
}

function getCockpitDecisionService(methodName) {
  var dashboardService = getAppRuntimeService("dashboard")
  if (!dashboardService || !dashboardService[methodName] || !isLoggedIn()) {
    return null
  }
  return dashboardService
}

function setCockpitDecisionDemoFallback(error) {
  state.cockpitDecisionContractsAvailable = false
  state.cockpitDecisionError = ""
  if (error) {
    console.warn("Cockpit decisions unavailable; using VITE_USE_MOCK demo data.", error)
  }
  state.cockpitDecisions = COCKPIT_SAMPLE_DECISIONS.map((item) =>
    normalizeCockpitDecision(item),
  )
  state.cockpitPipelineTasks = []
  renderCockpitScheduledTasks()
  renderCockpitDecisions()
}

function setCockpitDecisionUnavailable(error) {
  state.cockpitDecisionContractsAvailable = false
  state.cockpitDecisionError =
    error && error.message ? error.message : "后端决策接口不可用"
  state.cockpitDecisions = []
  state.cockpitPipelineTasks = []
  renderCockpitScheduledTasks()
  renderCockpitDecisions()
}

async function fetchCockpitDecisions() {
  var dashboardService = getCockpitDecisionService("listDecisions")
  if (!dashboardService) {
    if (isCockpitDecisionDemoMode()) {
      setCockpitDecisionDemoFallback()
    } else {
      setCockpitDecisionUnavailable()
    }
    return
  }
  if (_cockpitDecisionFetchPromise) return _cockpitDecisionFetchPromise
  var pipelineService = getAppRuntimeService("pipeline")
  var tasksPromise =
    pipelineService && pipelineService.listTasks && isLoggedIn()
      ? pipelineService
          .listTasks({ limit: 50 })
          .catch((error) => {
            console.warn("Cockpit scheduled tasks unavailable.", error)
            return { items: [] }
          })
      : Promise.resolve({ items: [] })
  _cockpitDecisionFetchPromise = dashboardService
    .listDecisions({ limit: 50 })
    .then((payload) => Promise.all([payload, tasksPromise]))
    .then(([payload, taskPayload]) => {
      state.cockpitDecisionContractsAvailable = true
      state.cockpitDecisionError = ""
      state.cockpitDecisions = getDecisionItems(payload).map(
        normalizeCockpitDecision,
      )
      state.cockpitPipelineTasks = getDecisionItems(taskPayload).map(
        normalizeCockpitPipelineTask,
      )
      renderCockpitScheduledTasks()
      renderCockpitDecisions()
    })
    .catch((error) => {
      if (isCockpitDecisionDemoMode()) {
        setCockpitDecisionDemoFallback(error)
      } else {
        console.warn("Cockpit decisions unavailable.", error)
        setCockpitDecisionUnavailable(error)
      }
    })
    .finally(() => {
      _cockpitDecisionFetchPromise = null
    })
  return _cockpitDecisionFetchPromise
}

function formatDecisionTime(value) {
  if (!value) return ""
  var date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value).replace("T", " ").slice(0, 16)
  return (
    date.getFullYear() +
    "-" +
    String(date.getMonth() + 1).padStart(2, "0") +
    "-" +
    String(date.getDate()).padStart(2, "0") +
    " " +
    String(date.getHours()).padStart(2, "0") +
    ":" +
    String(date.getMinutes()).padStart(2, "0")
  )
}

function renderDecisionStatusDetails(item) {
  if (item.status === "approved") {
    return "已写入经验方法" + (item.approvedAt ? " · " + formatDecisionTime(item.approvedAt) : "")
  }
  if (item.status === "rejected") {
    return (
      "驳回原因：" +
      (item.rejectionReason || "未记录") +
      (item.rejectedAt ? " · " + formatDecisionTime(item.rejectedAt) : "")
    )
  }
  if (item.status === "regenerating") {
    return item.rejectionReason || "后端正在根据驳回意见重新生成"
  }
  if (item.status === "changes_requested") {
    return item.regenerationError || ("驳回原因：" + (item.rejectionReason || "未记录"))
  }
  return ""
}

function getCockpitScheduledTasks() {
  var tasksByName = new Map()
  state.cockpitPipelineTasks.forEach((task) => {
    tasksByName.set("task:" + String(task.id), {
      taskId: task.id,
      name: task.name,
      schedule: task.schedule,
      timezone: task.timezone,
      nextRunAt: task.nextRunAt,
      taskStatus: task.status,
      total: 0,
      pending: 0,
      regenerating: 0,
      latestGeneratedAt: "",
    })
  })
  state.cockpitDecisions.forEach((decision) => {
    var taskName = decision.sourceTask || "未标注来源任务"
    var taskKey = decision.taskId
      ? "task:" + String(decision.taskId)
      : "name:" + taskName
    var existing =
      tasksByName.get(taskKey) ||
      {
        taskId: decision.taskId || null,
        name: taskName,
        schedule: "",
        timezone: "Asia/Shanghai",
        nextRunAt: "",
        taskStatus: "ready",
        total: 0,
        pending: 0,
        regenerating: 0,
        latestGeneratedAt: "",
      }
    existing.total += 1
    if (decision.status === "pending") existing.pending += 1
    if (decision.status === "regenerating") existing.regenerating += 1
    if (
      decision.generatedAt &&
      (!existing.latestGeneratedAt ||
        new Date(decision.generatedAt).getTime() >
          new Date(existing.latestGeneratedAt).getTime())
    ) {
      existing.latestGeneratedAt = decision.generatedAt
    }
    tasksByName.set(taskKey, existing)
  })
  return Array.from(tasksByName.values()).sort((left, right) => {
    return (
      new Date(right.latestGeneratedAt || 0).getTime() -
      new Date(left.latestGeneratedAt || 0).getTime()
    )
  })
}

function renderCockpitScheduledTasks() {
  var list = $("#cockpitScheduledTaskModalList")
  if (!list) return
  var tasks = getCockpitScheduledTasks()
  if (!tasks.length) {
    list.innerHTML =
      '<div class="cockpit-scheduled-task-empty">暂无定时任务</div>'
    return
  }
  list.innerHTML = tasks
    .map((task) => {
      var statusText = task.pending
        ? task.pending + " 条待决策"
        : task.regenerating
          ? task.regenerating + " 条重新生成中"
          : task.total
            ? "结果已同步"
            : "等待首次执行"
      var statusClass = task.pending
        ? "pending"
        : task.regenerating
          ? "regenerating"
          : "approved"
      return (
        '<article class="cockpit-scheduled-task-item">' +
        '<div class="cockpit-scheduled-task-title"><strong>' +
        escapeHTML(task.name) +
        '</strong><span class="cockpit-status-chip ' +
        statusClass +
        '">' +
        escapeHTML(statusText) +
        "</span></div>" +
        '<div class="cockpit-scheduled-task-meta"><span>产出结果 ' +
        task.total +
        " 条</span><span>计划 " +
        escapeHTML(task.schedule || "未设置") +
        "</span><span>最近生成 " +
        escapeHTML(formatDecisionTime(task.latestGeneratedAt) || "暂无记录") +
        "</span></div>" +
        "</article>"
      )
    })
    .join("")
}

function openCockpitScheduledTaskBoard() {
  var existing = document.querySelector(".cockpit-scheduled-task-modal-overlay")
  if (existing) existing.remove()
  var overlay = document.createElement("div")
  overlay.className = "modal-backdrop show cockpit-scheduled-task-modal-overlay"
  overlay.innerHTML =
    '<div class="modal cockpit-scheduled-task-modal" role="dialog" aria-modal="true" aria-labelledby="cockpitScheduledTaskModalTitle">' +
    '<div class="modal-header"><h2 id="cockpitScheduledTaskModalTitle">定时任务看板</h2>' +
    '<button class="btn icon-only" data-close-scheduled-task-modal aria-label="关闭定时任务看板"><svg class="icon"><use href="#i-close"/></svg></button></div>' +
    '<div class="cockpit-scheduled-task-list" id="cockpitScheduledTaskModalList"></div>' +
    '<div class="modal-actions"><button type="button" class="btn" data-close-scheduled-task-modal>关闭</button></div>' +
    "</div>"
  document.body.appendChild(overlay)
  renderCockpitScheduledTasks()
  var close = () => overlay.remove()
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) close()
  })
  overlay
    .querySelectorAll("[data-close-scheduled-task-modal]")
    .forEach((button) => {
      button.addEventListener("click", close)
    })
}

function getCockpitDecisionReasonType(reason) {
  // Every rejection is a correction request: rerun the same task with the
  // user's reason appended to its execution prompt.
  return "regenerate"
}

function buildCockpitDecisionRejectPayload(reason) {
  return { reason: String(reason || "").trim(), reason_type: "regenerate" }
}

function renderCockpitDecisionItem(item, options) {
  options = options || {}
  var disabled = !state.cockpitDecisionContractsAvailable
  var meta = []
  if (item.confidence !== null && item.confidence !== undefined)
    meta.push("置信度 " + item.confidence + "%")
  if (item.sourceTask) meta.push("来源：" + item.sourceTask)
  if (item.generatedAt) meta.push("生成：" + formatDecisionTime(item.generatedAt))
  var statusDetails = renderDecisionStatusDetails(item)
  var isRejecting = state.cockpitDecisionRejectingId === String(item.id)
  var actions = ""
  if (item.status === "pending") {
    actions =
      '<textarea class="cockpit-decision-approval-comment" data-decision-approval-comment="' +
      escapeHTML(item.id) +
      '" placeholder="同意意见（选填）"></textarea>' +
      '<div class="cockpit-decision-actions">' +
      '<button class="btn primary" type="button" data-decision-approve="' +
      escapeHTML(item.id) +
      '"' +
      (disabled ? " disabled" : "") +
      ">同意</button>" +
      '<button class="btn" type="button" data-decision-reject-open="' +
      escapeHTML(item.id) +
      '"' +
      (disabled ? " disabled" : "") +
      ">驳回</button>" +
      "</div>"
    if (disabled) {
      actions +=
        '<div class="cockpit-decision-meta">后端决策接口接入后可处理</div>'
    }
    if (isRejecting && !disabled) {
      actions +=
        '<div class="cockpit-decision-reject-panel" data-decision-reject-panel="' +
        escapeHTML(item.id) +
        '">' +
        '<div class="cockpit-decision-reason-buttons">' +
        '<button class="btn" type="button" data-decision-reason="暂无需求">暂无需求</button>' +
        '<button class="btn" type="button" data-decision-reason="其他情况">其他情况</button>' +
        "</div>" +
        '<textarea data-decision-reason-input="' +
        escapeHTML(item.id) +
        '" placeholder="填写驳回理由；填写具体原因将触发重新生成"></textarea>' +
        '<div class="cockpit-decision-actions">' +
        '<button class="btn primary" type="button" data-decision-reject-submit="' +
        escapeHTML(item.id) +
        '">提交驳回</button>' +
        '<button class="btn" type="button" data-decision-reject-cancel>取消</button>' +
        "</div></div>"
    }
  } else if (item.status === "changes_requested" && item.regenerationError) {
    actions =
      '<div class="cockpit-decision-meta">' +
      escapeHTML(statusDetails) +
      '</div><div class="cockpit-decision-actions"><button class="btn primary" type="button" data-decision-regenerate="' +
      escapeHTML(item.id) +
      '"' +
      (disabled ? " disabled" : "") +
      '>重新生成</button></div>'
  } else {
    actions = statusDetails
      ? '<div class="cockpit-decision-meta">' + escapeHTML(statusDetails) + "</div>"
      : ""
  }
  return (
    '<article class="cockpit-decision-item" data-decision-id="' +
    escapeHTML(item.id) +
    '">' +
    '<div class="cockpit-decision-title"><span>' +
    escapeHTML(item.title) +
    '</span><span class="cockpit-status-chip ' +
    escapeHTML(item.status) +
    '">' +
    escapeHTML(COCKPIT_STATUS_LABELS[item.status]) +
    "</span></div>" +
    '<div class="cockpit-decision-summary">' +
    escapeHTML(item.summary || "暂无摘要") +
    "</div>" +
    '<div class="cockpit-decision-action"><small>建议动作</small><span>' +
    escapeHTML(item.action || "等待后端返回建议动作") +
    "</span></div>" +
    '<div class="cockpit-decision-meta">' +
    meta.map(escapeHTML).join("<span>·</span>") +
    "</div>" +
    actions +
    "</article>"
  )
}

function getFilteredCockpitDecisions() {
  if (state.cockpitDecisionFilter === "all") return state.cockpitDecisions
  return state.cockpitDecisions.filter(
    (item) => item.status === state.cockpitDecisionFilter,
  )
}

function bindCockpitDecisionActions(root) {
  if (!root) return
  root.querySelectorAll("[data-decision-approve]").forEach((button) => {
    button.onclick = () =>
      approveCockpitDecision(
        button.dataset.decisionApprove,
        button.closest(".cockpit-decision-item"),
      )
  })
  root.querySelectorAll("[data-decision-reject-open]").forEach((button) => {
    button.onclick = () => {
      state.cockpitDecisionRejectingId = button.dataset.decisionRejectOpen
      renderCockpitDecisions()
    }
  })
  root.querySelectorAll("[data-decision-reason]").forEach((button) => {
    button.onclick = () => {
      var panel = button.closest("[data-decision-reject-panel]")
      var input = panel?.querySelector("[data-decision-reason-input]")
      if (input) input.value = button.dataset.decisionReason
    }
  })
  root.querySelectorAll("[data-decision-reject-submit]").forEach((button) => {
    button.onclick = () =>
      rejectCockpitDecision(
        button.dataset.decisionRejectSubmit,
        button.closest(".cockpit-decision-item"),
      )
  })
  root.querySelectorAll("[data-decision-reject-cancel]").forEach((button) => {
    button.onclick = () => {
      state.cockpitDecisionRejectingId = null
      renderCockpitDecisions()
    }
  })
  root.querySelectorAll("[data-decision-regenerate]").forEach((button) => {
    button.onclick = () =>
      retryCockpitDecisionRegeneration(button.dataset.decisionRegenerate)
  })
}

function closeCockpitDecisionDrawer() {
  var drawer = $("#cockpitDecisionDrawer")
  if (!drawer) return
  if (drawer._onKeyDown) {
    document.removeEventListener("keydown", drawer._onKeyDown)
  }
  var lastFocus = drawer._lastFocus
  drawer.remove()
  document.body.classList.remove("drawer-open")
  if (lastFocus && typeof lastFocus.focus === "function") {
    try {
      lastFocus.focus()
    } catch (_) {
      // The trigger may have been removed during a dashboard refresh.
    }
  }
}

function renderCockpitDecisionDrawer() {
  var drawer = $("#cockpitDecisionDrawer")
  if (!drawer) return
  var list = drawer.querySelector("[data-cockpit-decision-drawer-list]")
  if (!list) return
  var filteredItems = getFilteredCockpitDecisions()
  var emptyText =
    state.cockpitDecisionError ||
    (state.cockpitDecisionFilter === "all"
      ? "暂无智能决策"
      : "当前筛选下暂无决策")
  list.innerHTML = filteredItems.length
    ? '<div class="cockpit-decision-full-list">' +
      filteredItems.map((item) => renderCockpitDecisionItem(item)).join("") +
      "</div>"
    : '<div class="cockpit-decision-empty">' + escapeHTML(emptyText) + "</div>"
  bindCockpitDecisionActions(list)
}

function openCockpitDecisionDrawer() {
  if ($("#cockpitDecisionDrawer")) {
    renderCockpitDecisionDrawer()
    return
  }
  var drawer = document.createElement("div")
  drawer.id = "cockpitDecisionDrawer"
  drawer.className = "drawer-overlay cockpit-decision-drawer show"
  drawer.innerHTML =
    '<div class="drawer-panel" role="dialog" aria-modal="true" aria-labelledby="cockpitDecisionDrawerTitle">' +
    '<div class="drawer-header"><h2 class="drawer-title" id="cockpitDecisionDrawerTitle">全部智能决策</h2>' +
    '<button class="drawer-close" type="button" data-cockpit-decision-drawer-close aria-label="关闭">关闭</button>' +
    "</div>" +
    '<div class="drawer-body" data-cockpit-decision-drawer-list></div>' +
    "</div>"
  drawer._lastFocus = document.activeElement
  drawer._onKeyDown = (event) => {
    if (event.key === "Escape") {
      event.preventDefault()
      closeCockpitDecisionDrawer()
    }
  }
  drawer.addEventListener("click", (event) => {
    if (event.target === drawer) closeCockpitDecisionDrawer()
  })
  drawer
    .querySelector("[data-cockpit-decision-drawer-close]")
    .addEventListener("click", closeCockpitDecisionDrawer)
  document.body.appendChild(drawer)
  document.body.classList.add("drawer-open")
  document.addEventListener("keydown", drawer._onKeyDown)
  renderCockpitDecisionDrawer()
  window.setTimeout(() => {
    drawer.querySelector("[data-cockpit-decision-drawer-close]")?.focus()
  }, 0)
}

function renderCockpitDecisions() {
  var list = $("#cockpitDecisionList")
  if (!list) return
  var filteredItems = getFilteredCockpitDecisions()
  var previewItems = filteredItems.slice(0, COCKPIT_DECISION_PREVIEW_LIMIT)
  var emptyText =
    state.cockpitDecisionError ||
    (state.cockpitDecisionFilter === "all"
      ? "暂无智能决策"
      : "当前筛选下暂无决策")
  list.innerHTML = previewItems.length
    ? '<div class="cockpit-decision-preview-grid">' +
      previewItems.map((item) => renderCockpitDecisionItem(item)).join("") +
      "</div>"
    : '<div class="cockpit-decision-empty">' + escapeHTML(emptyText) + "</div>"
  var headerActions = $("#cockpitDecisionHeaderActions")
  if (headerActions) {
    headerActions.innerHTML =
      filteredItems.length > COCKPIT_DECISION_PREVIEW_LIMIT
        ? '<button class="card-link" id="cockpitDecisionViewAll" type="button">查看全部</button>'
        : ""
    var viewAllButton = $("#cockpitDecisionViewAll")
    if (viewAllButton) viewAllButton.onclick = openCockpitDecisionDrawer
  }
  $$(".cockpit-decision-filters [data-decision-filter]").forEach((button) =>
    button.classList.toggle(
      "active",
      button.dataset.decisionFilter === state.cockpitDecisionFilter,
    ),
  )
  bindCockpitDecisionActions(list)
  renderCockpitDecisionDrawer()
}

function getCockpitDecisionUpdateOrFallback(updated, fallbackPatch) {
  if (
    updated &&
    updated.id !== undefined &&
    updated.id !== null &&
    (updated.status || updated.decision_status)
  ) {
    return updated
  }
  if (isCockpitDecisionDemoMode()) return fallbackPatch
  throw new Error("后端未返回有效决策结果")
}

async function approveCockpitDecision(decisionId, decisionElement) {
  var dashboardService = getCockpitDecisionService("approveDecision")
  if (!dashboardService) {
    showToast("后端决策接口接入后可处理")
    return
  }
  try {
    var commentInput = decisionElement?.querySelector(
      '[data-decision-approval-comment="' + CSS.escape(String(decisionId)) + '"]',
    ) || document.querySelector(
      '[data-decision-approval-comment="' + CSS.escape(String(decisionId)) + '"]',
    )
    var comment = (commentInput?.value || "").trim()
    var payload = comment ? { comment } : {}
    var updated = await dashboardService.approveDecision(decisionId, payload)
    replaceCockpitDecision(
      getCockpitDecisionUpdateOrFallback(updated, {
        id: decisionId,
        status: "approved",
        approvedAt: new Date().toISOString(),
      }),
    )
    showToast("已同意，经验方法由后端写入")
  } catch (error) {
    console.warn("Cockpit decision approval failed.", error)
    showToast(error.message || "同意决策失败")
  }
}

async function rejectCockpitDecision(decisionId, decisionElement, reasonOverride) {
  var input = decisionElement?.querySelector(
    '[data-decision-reason-input="' + CSS.escape(String(decisionId)) + '"]',
  ) || document.querySelector(
    '[data-decision-reason-input="' + CSS.escape(String(decisionId)) + '"]',
  )
  var reason = String(reasonOverride || input?.value || "").trim()
  if (!reason) {
    showToast("请填写驳回理由")
    return
  }
  var dashboardService = getCockpitDecisionService("rejectDecision")
  if (!dashboardService) {
    showToast("后端决策接口接入后可处理")
    return
  }
  var payload = buildCockpitDecisionRejectPayload(reason)
  try {
    var updated = await dashboardService.rejectDecision(decisionId, payload)
    const decision = getCockpitDecisionUpdateOrFallback(updated, {
        id: decisionId,
        status: "regenerating",
        rejectionReason: reason,
        rejectedAt: new Date().toISOString(),
      })
    replaceCockpitDecision({ ...decision, status: "regenerating", regenerationError: "" })
    state.cockpitDecisionRejectingId = null
    if (decision.regenerationRunId || decision.regeneration_run_id) {
      showToast("已提交驳回，重新生成中")
      void waitForPipelineRegeneration(
        decisionId,
        decision.regenerationRunId || decision.regeneration_run_id,
      )
    } else {
      showToast("已驳回并归档")
    }
  } catch (error) {
    console.warn("Cockpit decision rejection failed.", error)
    showToast(error.message || "驳回决策失败")
  }
}

async function retryCockpitDecisionRegeneration(decisionId) {
  var decision = state.cockpitDecisions.find(
    (item) => String(item.id) === String(decisionId),
  )
  if (!decision || !decision.rejectionReason) {
    showToast("缺少原驳回理由，无法重新生成")
    return
  }
  var dashboardService = getCockpitDecisionService("rejectDecision")
  if (!dashboardService) {
    showToast("后端决策接口接入后可处理")
    return
  }
  if (dashboardService.releaseDecisionIntent) {
    dashboardService.releaseDecisionIntent(decisionId, "reject")
  }
  await rejectCockpitDecision(decisionId, null, decision.rejectionReason)
}

function replaceCockpitDecision(updated) {
  var originalId = updated?.id
  state.cockpitDecisions = state.cockpitDecisions.map((item) =>
    String(item.id) === String(originalId)
      ? normalizeCockpitDecision({
          ...item,
          ...updated,
          id: item.id,
        })
      : item,
  )
  renderCockpitScheduledTasks()
  renderCockpitDecisions()
}

function renderCockpitDocs() {
  var pendingList = $("#pendingDocList")
  var favList = $("#favDocList")
  if (pendingList) {
    var pendingDocs = state.documents.slice(0, 6)
    if (!pendingDocs.length) {
      pendingList.innerHTML =
        '<div class="cockpit-doc-empty">暂无待办文件</div>'
    } else {
      pendingList.innerHTML = pendingDocs
        .map((doc) => {
          var docId = String(doc.id)
          var isFav = state.cockpitFavorites.indexOf(docId) !== -1
          return (
            '<div class="cockpit-doc-item" style="display:flex;align-items:center;gap:8px">' +
            '<button class="card-link" style="flex:1;text-align:left;min-width:0" data-open-asset="documents:' +
            doc.id +
            '"><span class="doc-name"><span class="file-type">' +
            escapeHTML(doc.file_type || "D") +
            "</span>" +
            escapeHTML(doc.name || "未命名文档") +
            "</span></button>" +
            '<span class="cockpit-doc-pending-chip">待处理</span>' +
            '<button class="cockpit-doc-fav-btn ' +
            (isFav ? "active" : "") +
            '" data-cockpit-fav="' +
            docId +
            '" title="收藏"><svg class="icon" style="width:14px;height:14px"><use href="#i-star"/></svg></button>' +
            "</div>"
          )
        })
        .join("")
    }
  }
  if (favList) {
    var favDocs = state.documents.filter(
      (doc) => state.cockpitFavorites.indexOf(String(doc.id)) !== -1,
    )
    if (!favDocs.length) {
      favList.innerHTML =
        '<div class="cockpit-doc-empty">暂无收藏文件<br><small>点击文件右侧星标即可收藏</small></div>'
    } else {
      favList.innerHTML = favDocs
        .map(
          (doc) =>
            '<div class="cockpit-doc-item" style="display:flex;align-items:center;gap:8px">' +
            '<button class="card-link" style="flex:1;text-align:left;min-width:0" data-open-asset="documents:' +
            doc.id +
            '"><span class="doc-name"><span class="file-type">' +
            escapeHTML(doc.file_type || "D") +
            "</span>" +
            escapeHTML(doc.name || "未命名文档") +
            "</span></button>" +
            '<button class="cockpit-doc-fav-btn active" data-cockpit-fav="' +
            String(doc.id) +
            '" title="取消收藏"><svg class="icon" style="width:14px;height:14px"><use href="#i-star"/></svg></button>' +
            "</div>",
        )
        .join("")
    }
  }
  bindAssetOpeners()
  // bind fav buttons
  document.querySelectorAll("[data-cockpit-fav]").forEach((btn) => {
    btn.onclick = () => {
      var docId = btn.dataset.cockpitFav
      var idx = state.cockpitFavorites.indexOf(docId)
      if (idx === -1) {
        state.cockpitFavorites.push(docId)
      } else {
        state.cockpitFavorites.splice(idx, 1)
      }
      _saveScoped(cockpitFavoritesKey, JSON.stringify(state.cockpitFavorites))
      renderCockpitDocs()
    }
  })
}

// ── Read current cockpit shortcut grid order ─────────────────────
function _readCockpitShortcutOrder() {
  if (!_cockpitShortcutGrid) return null
  var nodes = _cockpitShortcutGrid.engine.nodes.slice().sort((a, b) => {
    if (a.y !== b.y) return a.y - b.y
    return a.x - b.x
  })
  var order = []
  nodes.forEach((n) => {
    var card =
      n.el && n.el.querySelector && n.el.querySelector("[data-entry-index]")
    if (card) order.push(parseInt(card.dataset.entryIndex))
  })
  return order.length > 0 ? order : null
}

// ── Save cockpit shortcut order (debounced) ─────────────────────
function _scheduleCockpitShortcutOrderSave() {
  clearTimeout(_cockpitSaveShortcutOrderTimer)
  _cockpitSaveShortcutOrderTimer = setTimeout(
    _commitCockpitShortcutOrderSave,
    100,
  )
}

function _finishCockpitShortcutDrag() {
  clearTimeout(_cockpitSaveShortcutOrderTimer)
  _commitCockpitShortcutOrderSave()
  renderCockpitShortcuts()
}

function _commitCockpitShortcutOrderSave() {
  if (!_cockpitShortcutGrid) return
  var order = _readCockpitShortcutOrder()
  if (!order) return
  // Rebuild entries array in new order
  var reordered = order.map((i) => state.cockpitEntries[i]).filter(Boolean)
  // Check if order actually changed
  if (
    reordered.length === state.cockpitEntries.length &&
    reordered.every((e, i) => e.title === state.cockpitEntries[i].title)
  )
    return
  state.cockpitEntries = reordered
  _saveScoped(cockpitEntriesKey, JSON.stringify(state.cockpitEntries))
}

function getCockpitShortcutPosition(index, h) {
  var cardsPerRow = 6
  return {
    x: (index % cardsPerRow) * 2,
    y: Math.floor(index / cardsPerRow) * h,
    w: 2,
    h: h,
  }
}

function getCockpitAddEntryPosition(entriesLength, h) {
  return getCockpitShortcutPosition(entriesLength, h)
}

function renderCockpitShortcuts() {
  var grid = $("#cockpitShortcutGrid")
  if (!grid) return

  // Show/hide restore button
  var resetBtn = $("#cockpitResetEntries")
  if (resetBtn)
    resetBtn.style.display =
      state.cockpitEntries.length !== COCKPIT_PRESET_ENTRIES.length
        ? ""
        : "none"

  var entries = state.cockpitEntries
  if (entries.length === 0) {
    grid.innerHTML =
      '<div class="empty-state"><div class="empty-illustration"></div><strong>暂无常用功能</strong><p>点击「编辑」按钮开始管理入口</p></div>'
    if (_cockpitShortcutGrid) {
      try {
        _cockpitShortcutGrid.destroy(false)
      } catch (e) {}
      _cockpitShortcutGrid = null
    }
    return
  }

  grid.innerHTML = '<div class="grid-stack"></div>'
  var gsEl = grid.querySelector(".grid-stack")
  if (_cockpitShortcutGrid) {
    try {
      _cockpitShortcutGrid.destroy(false)
    } catch (e) {}
  }

  var MARGIN = 8

  // Measure column width for card width (w:2 => ~150-180px)
  var gsW = gsEl.clientWidth
  var colW = Math.floor((gsW - 11 * MARGIN) / 12)
  if (colW < 60) colW = 60
  var cardW = colW * 2 + MARGIN

  var isEditing = state.cockpitEditMode
  // Update edit toggle button text
  var editToggle = $("#cockpitEditToggle")
  if (editToggle) {
    editToggle.textContent = isEditing ? "完成" : "编辑"
    if (isEditing) editToggle.classList.add("active")
    else editToggle.classList.remove("active")
  }
  // Toggle edit-mode class on grid for visual feedback
  if (isEditing) grid.classList.add("cockpit-edit-mode")
  else grid.classList.remove("cockpit-edit-mode")

  // ── Measure card heights first ──
  var measureWrap = document.createElement("div")
  measureWrap.style.cssText =
    "position:absolute;visibility:hidden;top:-9999px;left:0;"
  measureWrap.style.width = cardW + "px"
  document.body.appendChild(measureWrap)

  var cardSpecs = entries.map((entry, idx) => {
    var removeBtn = isEditing
      ? '<span class="cockpit-entry-remove" data-entry-remove="' +
        idx +
        '">&times;</span>'
      : ""
    var cardHTML =
      '<div class="cockpit-shortcut-item" data-entry-index="' +
      idx +
      '" role="button" tabindex="0">' +
      '<span class="app-icon ' +
      (entry.tone || "app-blue") +
      '">' +
      escapeHTML(entry.title.slice(0, 1)) +
      "</span>" +
      "<span><strong>" +
      escapeHTML(entry.title) +
      "</strong><small>" +
      escapeHTML(entry.desc || "") +
      "</small></span>" +
      removeBtn +
      "</div>"
    measureWrap.innerHTML = cardHTML
    var naturalH = measureWrap.firstElementChild.offsetHeight
    return { cardHTML: cardHTML, h: Math.max(58, naturalH + 8) }
  })
  document.body.removeChild(measureWrap)

  var maxH = cardSpecs.reduce((m, s) => Math.max(m, s.h), 58)

  // maxRow prevents dragging cards beyond occupied rows
  // 12 cols, w:2 → 6 cards/row; +1 placeholder; rows are maxH units tall
  var totalWidgets = entries.length + 1
  var maxRow = Math.ceil(totalWidgets / 6) * maxH

  // ── Init GridStack ──
  _cockpitShortcutGrid = window.GridStack.init(
    {
      column: 12,
      cellHeight: 1,
      margin: MARGIN,
      float: false,
      animate: true,
      disableResize: true,
      swap: true,
      maxRow: maxRow,
    },
    gsEl,
  )

  _cockpitShortcutGrid.on("change", _scheduleCockpitShortcutOrderSave)
  _cockpitShortcutGrid.on("dragstop", _finishCockpitShortcutDrag)

  // Use max height so GridStack swap works
  var maxH = cardSpecs.reduce((m, s) => Math.max(m, s.h), 58)

  // Batch add widgets
  _cockpitShortcutGrid.batchUpdate()
  cardSpecs.forEach((spec, index) => {
    var gsItem = document.createElement("div")
    gsItem.className = "grid-stack-item"
    var gsContent = document.createElement("div")
    gsContent.className = "grid-stack-item-content"
    gsContent.innerHTML = spec.cardHTML
    gsItem.appendChild(gsContent)
    _cockpitShortcutGrid.makeWidget(gsItem, {
      ...getCockpitShortcutPosition(index, maxH),
    })
  })

  // Placeholder add card. It stays in the GridStack layout for alignment, then
  // dragstop redraws the grid so this slot is always the final card.
  var phItem = document.createElement("div")
  phItem.className = "grid-stack-item"
  var phContent = document.createElement("div")
  phContent.className = "grid-stack-item-content"
  phContent.innerHTML =
    '<div class="cockpit-placeholder-card" id="cockpitAddPlaceholder"><span class="app-icon">+</span>添加入口</div>'
  phItem.appendChild(phContent)
  _cockpitShortcutGrid.makeWidget(phItem, {
    ...getCockpitAddEntryPosition(entries.length, maxH),
    locked: true,
    noMove: true,
    noResize: true,
  })
  _cockpitShortcutGrid.batchUpdate(false)

  // Click: depends on edit mode
  $$("#cockpitShortcutGrid .cockpit-shortcut-item").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      if (e.target.closest(".cockpit-entry-remove")) return
      var idx = parseInt(btn.dataset.entryIndex)
      var entry = state.cockpitEntries[idx]
      if (!entry) return
      if (isEditing) {
        showCockpitEntryModal(entry, idx)
      } else {
        openCockpitEntry(entry)
      }
    })
  })

  // Click: placeholder card → open add modal (always works)
  var ph = $("#cockpitAddPlaceholder")
  if (ph) ph.onclick = () => showCockpitEntryModal()

  // Click: remove button (only present in edit mode)
  $$("#cockpitShortcutGrid [data-entry-remove]").forEach((rmBtn) => {
    rmBtn.addEventListener("click", (e) => {
      e.stopPropagation()
      e.preventDefault()
      var idx = parseInt(rmBtn.dataset.entryRemove)
      var entry = state.cockpitEntries[idx]
      if (!entry) return
      state.cockpitEntries.splice(idx, 1)
      _saveScoped(cockpitEntriesKey, JSON.stringify(state.cockpitEntries))
      renderCockpitShortcuts()
      showToast("已移除「" + entry.title + "」")
    })
  })
}

// ── Modal for adding/editing an entry ─────────────────────────────
function showCockpitEntryModal(editEntry, editIdx) {
  var existing = document.querySelector(".cockpit-entry-modal-overlay")
  if (existing) existing.remove()

  var isEdit = editEntry !== undefined && editEntry !== null
  var overlay = document.createElement("div")
  overlay.className = "cockpit-entry-modal-overlay"
  overlay.innerHTML =
    '<div class="cockpit-entry-modal">' +
    "<h3>" +
    (isEdit ? "编辑入口" : "添加入口") +
    "</h3>" +
    '<div class="form-row"><label>入口名称</label><input id="modalEntryTitle" placeholder="必填" autofocus /></div>' +
    '<div class="form-row"><label>链接地址</label><input id="modalEntryUrl" placeholder="可选" /></div>' +
    '<div class="form-row"><label>简短描述</label><input id="modalEntryDesc" placeholder="可选" /></div>' +
    '<div class="form-actions">' +
    '<button class="btn" id="modalEntryCancel">取消</button>' +
    '<button class="btn primary" id="modalEntrySubmit">保存</button>' +
    "</div></div>"
  document.body.appendChild(overlay)

  var titleEl = $("#modalEntryTitle")
  var urlEl = $("#modalEntryUrl")
  var descEl = $("#modalEntryDesc")

  // Pre-fill for edit
  if (isEdit) {
    if (titleEl) titleEl.value = editEntry.title || ""
    if (urlEl) urlEl.value = editEntry.url || ""
    if (descEl) descEl.value = editEntry.desc || ""
  }

  if (titleEl)
    setTimeout(() => {
      titleEl.focus()
    }, 50)

  var close = () => {
    overlay.remove()
  }
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) close()
  })
  var cancelBtn = $("#modalEntryCancel")
  if (cancelBtn) cancelBtn.onclick = close

  var submitBtn = $("#modalEntrySubmit")
  if (submitBtn)
    submitBtn.onclick = () => {
      var title = titleEl ? titleEl.value.trim() : ""
      if (!title) {
        showToast("请输入入口名称")
        return
      }
      var tones = [
        "app-blue",
        "app-purple",
        "app-orange",
        "app-green",
        "app-cyan",
        "app-red",
      ]
      var entryData = {
        title: title,
        desc: descEl ? descEl.value.trim() : "",
        tone: isEdit
          ? editEntry.tone || tones[Math.floor(Math.random() * tones.length)]
          : tones[Math.floor(Math.random() * tones.length)],
        url: urlEl ? urlEl.value.trim() : "",
      }
      if (isEdit) {
        state.cockpitEntries[editIdx] = entryData
      } else {
        state.cockpitEntries.push(entryData)
      }
      _saveScoped(cockpitEntriesKey, JSON.stringify(state.cockpitEntries))
      close()
      renderCockpitShortcuts()
      showToast(
        isEdit ? "入口「" + title + "」已更新" : "入口「" + title + "」已添加",
      )
    }
}

function openCockpitEntry(entry) {
  if (entry.url) {
    window.open(entry.url, "_blank", "noopener")
    return
  }
  var title = entry.title || ""
  var routes = {
    公告: "notices",
    公告中心: "notices",
    日历: "calendar",
    待办中心: "workspace",
    智能问答: "knowledge",
    知识库: "knowledge",
    定时任务看板: "scheduled-task-board",
    服务台: "services",
    文档: "documents",
    文档中心: "documents",
    融合门户: "portal",
    会议: "calendar",
    人事系统: "",
  }
  var routeKey = Object.keys(routes).find((k) => title.indexOf(k) !== -1)
  if (routeKey && routes[routeKey] === "scheduled-task-board") {
    return openCockpitScheduledTaskBoard()
  }
  if (routeKey && routes[routeKey]) {
    if (assetViews[routes[routeKey]]) return renderAssetCenter(routes[routeKey])
    return setView(routes[routeKey])
  }
  if (routes[title]) {
    if (assetViews[routes[title]]) return renderAssetCenter(routes[title])
    return setView(routes[title])
  }
  // try matching a subsystem by title
  var match = state.systems.find(
    (s) => s.name === title || s.code === title || title.indexOf(s.name) !== -1,
  )
  if (match) {
    return openSubsystem(match)
  }
  showToast("入口「" + title + "」暂未配置链接")
}

function renderCockpit() {
  renderCockpitKPI()
  renderCockpitScheduledTasks()
  renderCockpitDecisions()
  fetchCockpitDecisions().catch((error) =>
    console.warn("Cockpit decision refresh failed.", error),
  )
  renderCockpitDocs()
  renderCockpitShortcuts()
}

function bindCockpitEvents() {
  $$(".cockpit-decision-filters [data-decision-filter]").forEach((button) => {
    button.onclick = () => {
      state.cockpitDecisionFilter = button.dataset.decisionFilter
      renderCockpitDecisions()
    }
  })
  var addCompBtn = $("#cockpitAddComponent")
  if (addCompBtn) {
    addCompBtn.onclick = () => {
      renderCockpitComponentPanel()
      // close panel on outside click
      setTimeout(() => {
        var panel = $("#cockpitComponentPanel")
        if (!panel || panel.hidden) return
        var closePanel = (e) => {
          if (!panel.contains(e.target) && e.target !== addCompBtn) {
            panel.hidden = true
            document.removeEventListener("click", closePanel)
          }
        }
        document.addEventListener("click", closePanel)
      }, 10)
    }
  }
  var saveBtn = $("#cockpitSaveLayout")
  if (saveBtn) {
    saveBtn.onclick = async () => {
      _saveScoped(cockpitLayoutKey, JSON.stringify(state.cockpitKpiLayout))
      var dashboardService = getAppRuntimeService("dashboard")
      var expectedRevision = getDashboardLayoutRevision()
      if (!dashboardService || !dashboardService.saveLayout || !isLoggedIn()) {
        showToast("布局已保存")
        return
      }
      if (expectedRevision === null) {
        try {
          applyDashboardLayoutResponse(await dashboardService.getLayout())
          expectedRevision = getDashboardLayoutRevision()
        } catch (error) {
          showToast(error.message || "布局已保存到本地，服务端版本获取失败")
          return
        }
      }
      if (typeof expectedRevision !== "number") {
        showToast("布局已保存到本地，缺少服务端版本号")
        return
      }
      try {
        var savedLayout = await dashboardService.saveLayout({
          layouts: cockpitOrderToDashboardLayouts(state.cockpitKpiLayout),
          expectedRevision,
        })
        applyDashboardLayoutResponse(savedLayout)
        showToast("布局已保存")
      } catch (error) {
        if (error && error.status === 409) {
          showToast("服务端布局已更新，请刷新后再保存")
          return
        }
        showToast(error.message || "布局已保存到本地，后端同步失败")
      }
    }
  }
  var resetBtn = $("#cockpitResetLayout")
  if (resetBtn) {
    resetBtn.onclick = async () => {
      state.cockpitKpiLayout = [
        "business",
        "staff",
        "market",
        "production",
        "other",
      ]
      state.cockpitExpandedKpi = null
      _saveScoped(cockpitLayoutKey, JSON.stringify(state.cockpitKpiLayout))
      renderCockpitKPI()
      var dashboardService = getAppRuntimeService("dashboard")
      if (!dashboardService || !dashboardService.resetLayout || !isLoggedIn()) {
        showToast("已恢复默认布局")
        return
      }
      try {
        applyDashboardLayoutResponse(await dashboardService.resetLayout())
        renderCockpitKPI()
        showToast("已恢复默认布局")
      } catch (error) {
        showToast(error.message || "已恢复本地默认布局，后端同步失败")
      }
    }
  }
  var addEventBtn = $("#cockpitAddEvent")
  if (addEventBtn) {
    addEventBtn.onclick = () => {
      openEventModal()
    }
  }
  // KPI card click delegation
  var kpiGrid = $("#cockpitKpiGrid")
  if (kpiGrid) {
    kpiGrid.addEventListener("click", (e) => {
      var card = e.target.closest("[data-kpi]")
      if (!card) return
      var kpiId = card.dataset.kpi
      if (state.cockpitExpandedKpi === kpiId) {
        state.cockpitExpandedKpi = null
      } else {
        state.cockpitExpandedKpi = kpiId
      }
      renderCockpitKPI()
    })
  }
  // task range tabs
  document.querySelectorAll("[data-task-range]").forEach((tab) => {
    tab.addEventListener("click", () => {
      state.cockpitTaskRange = tab.dataset.taskRange
      _saveScoped(cockpitTaskRangeKey, state.cockpitTaskRange)
      document.querySelectorAll("[data-task-range]").forEach((t) => {
        t.classList.remove("active")
      })
      tab.classList.add("active")
      renderTasks()
    })
  })
  // edit toggle button
  var editToggleBtn = $("#cockpitEditToggle")
  if (editToggleBtn) {
    editToggleBtn.onclick = () => {
      state.cockpitEditMode = !state.cockpitEditMode
      renderCockpitShortcuts()
    }
  }
  // restore defaults button
  var resetEntriesBtn = $("#cockpitResetEntries")
  if (resetEntriesBtn) {
    resetEntriesBtn.onclick = () => {
      state.cockpitEntries = COCKPIT_PRESET_ENTRIES.map((e) =>
        Object.assign({}, e),
      )
      _saveScoped(cockpitEntriesKey, JSON.stringify(state.cockpitEntries))
      renderCockpitShortcuts()
      showToast("已恢复默认入口")
    }
  }
}

function renderWorkbenchOverview() {
  const todoCount = state.tasks.filter((task) => !task.done).length
  const doneCount = state.tasks.filter((task) => task.done).length
  const todayScheduleCount = state.events.filter(
    (event) => event.date === todayKey,
  ).length
  const todoTarget = $("#overviewTodoCount")
  const doneTarget = $("#overviewDoneCount")
  const totalTarget = $("#overviewTaskCount")
  const scheduleTarget = $("#overviewTodaySchedule")
  const dashboardTodoTarget = $("#dashboardTodoCount")
  if (todoTarget) todoTarget.textContent = todoCount
  if (doneTarget) doneTarget.textContent = doneCount
  if (totalTarget) totalTarget.textContent = state.tasks.length
  if (scheduleTarget) scheduleTarget.textContent = todayScheduleCount
  if (dashboardTodoTarget) dashboardTodoTarget.textContent = `${todoCount} 项`
}

function getTaskDeadlineTime(task) {
  if (!task || !task.deadline) return null
  var time = new Date(task.deadline).getTime()
  return Number.isNaN(time) ? null : time
}

function _isTaskOverdue(task) {
  if (task.done) return false
  if (task.status === "overdue") return true
  var deadlineTime = getTaskDeadlineTime(task)
  if (deadlineTime !== null) return deadlineTime <= Date.now()
  return false
}

function _formatDeadline(deadline) {
  if (!deadline) return ""
  // deadline is ISO string like "2026-08-06T14:30:00"
  var dt = deadline.replace("T", " ").substring(0, 16)
  var now = new Date()
  var today =
    now.getFullYear() +
    "-" +
    String(now.getMonth() + 1).padStart(2, "0") +
    "-" +
    String(now.getDate()).padStart(2, "0")
  if (deadline.substring(0, 10) === today) {
    // Today: show only time
    return deadline.substring(11, 16)
  }
  // Other days: show MM-DD HH:mm
  return deadline.substring(5, 10) + " " + deadline.substring(11, 16)
}

function _taskInRange(
  task,
  isDay,
  todayStr,
  isWeek,
  weekMondayStr,
  weekSundayStr,
  isMonth,
  monthStartStr,
  monthEndStr,
) {
  // tasks without deadline always pass range filter
  if (!task.deadline) return true
  var dateStr = task.deadline.substring(0, 10)
  if (isDay) return dateStr === todayStr
  if (isWeek) return dateStr >= weekMondayStr && dateStr <= weekSundayStr
  if (isMonth) return dateStr >= monthStartStr && dateStr <= monthEndStr
  return true
}

function renderTasks() {
  var list = $("#taskList")
  if (!list) return // not on workspace view — nothing to render
  var overdueTasks = []
  var todoTasks = []
  state.tasks.forEach((task) => {
    if (task.done) {
      // done tasks are handled separately via the "done" filter
    } else if (_isTaskOverdue(task)) {
      overdueTasks.push(task)
    } else {
      todoTasks.push(task)
    }
  })

  // ── cockpit range filter (day/week/month) ──
  if (state.cockpitTaskRange && state.cockpitTaskRange !== "all") {
    var _nowDate = new Date()
    var _todayStr =
      _nowDate.getFullYear() +
      "-" +
      String(_nowDate.getMonth() + 1).padStart(2, "0") +
      "-" +
      String(_nowDate.getDate()).padStart(2, "0")
    var _isDay = state.cockpitTaskRange === "day"
    var _isWeek = state.cockpitTaskRange === "week"
    var _isMonth = state.cockpitTaskRange === "month"
    var _weekMondayStr = ""
    var _weekSundayStr = ""
    var _monthStartStr = ""
    var _monthEndStr = ""
    if (_isWeek) {
      var _dayOfWeek = _nowDate.getDay()
      var _mondayOffset = _dayOfWeek === 0 ? -6 : 1 - _dayOfWeek
      var _monday = new Date(_nowDate)
      _monday.setDate(_nowDate.getDate() + _mondayOffset)
      var _sunday = new Date(_monday)
      _sunday.setDate(_monday.getDate() + 6)
      _weekMondayStr =
        _monday.getFullYear() +
        "-" +
        String(_monday.getMonth() + 1).padStart(2, "0") +
        "-" +
        String(_monday.getDate()).padStart(2, "0")
      _weekSundayStr =
        _sunday.getFullYear() +
        "-" +
        String(_sunday.getMonth() + 1).padStart(2, "0") +
        "-" +
        String(_sunday.getDate()).padStart(2, "0")
    }
    if (_isMonth) {
      _monthStartStr =
        _nowDate.getFullYear() +
        "-" +
        String(_nowDate.getMonth() + 1).padStart(2, "0") +
        "-01"
      var _lastDay = new Date(
        _nowDate.getFullYear(),
        _nowDate.getMonth() + 1,
        0,
      ).getDate()
      _monthEndStr =
        _nowDate.getFullYear() +
        "-" +
        String(_nowDate.getMonth() + 1).padStart(2, "0") +
        "-" +
        String(_lastDay).padStart(2, "0")
    }
    overdueTasks = overdueTasks.filter((t) =>
      _taskInRange(
        t,
        _isDay,
        _todayStr,
        _isWeek,
        _weekMondayStr,
        _weekSundayStr,
        _isMonth,
        _monthStartStr,
        _monthEndStr,
      ),
    )
    todoTasks = todoTasks.filter((t) =>
      _taskInRange(
        t,
        _isDay,
        _todayStr,
        _isWeek,
        _weekMondayStr,
        _weekSundayStr,
        _isMonth,
        _monthStartStr,
        _monthEndStr,
      ),
    )
  }

  var filtered
  switch (state.taskFilter) {
    case "overdue":
      filtered = overdueTasks
      break
    case "done":
      filtered = state.tasks.filter((t) => t.done)
      break
    case "todo":
      filtered = todoTasks
      break
    default:
      filtered = state.tasks
      break // "all"
  }

  // Update filter tab counts
  var todoEl = document.querySelector("[data-task-filter=todo]")
  var overdueEl = document.querySelector("[data-task-filter=overdue]")
  var doneEl = document.querySelector("[data-task-filter=done]")
  if (todoEl) todoEl.textContent = "未完成 " + todoTasks.length
  if (overdueEl) overdueEl.textContent = "已过期 " + overdueTasks.length
  if (doneEl) {
    var doneCount = state.tasks.filter((t) => t.done).length
    doneEl.textContent = "已完成 " + doneCount
  }

  // Sidebar badge
  var sidebarBadge = document.querySelector(
    ".side-link[data-view-link='workspace'] small",
  )
  if (!sidebarBadge) {
    var workspaceBtn = document.querySelector(
      ".side-link[data-view-link='workspace']",
    )
    if (!workspaceBtn) {
      // Find by text content
      var sideLinks = document.querySelectorAll(".side-link")
      for (var s = 0; s < sideLinks.length; s++) {
        if (sideLinks[s].textContent.indexOf("待办中心") !== -1) {
          sidebarBadge = sideLinks[s].querySelector("small")
          break
        }
      }
    } else {
      sidebarBadge = workspaceBtn.querySelector("small")
    }
  }
  if (sidebarBadge) {
    var undoneCount = state.tasks.filter((t) => !t.done).length
    sidebarBadge.textContent = undoneCount
    sidebarBadge.style.display = undoneCount > 0 ? "" : "none"
    // Red background when any overdue task exists
    if (overdueTasks.length > 0) {
      sidebarBadge.classList.add("badge-danger")
    } else {
      sidebarBadge.classList.remove("badge-danger")
    }
  }

  var emptyTexts = {
    todo: {
      strong: "暂无待办任务",
      desc: "当前没有需要处理的任务。",
      btn: "刷新待办",
      toast: "待办任务已刷新",
    },
    overdue: {
      strong: "没有过期任务",
      desc: "所有任务都在截止时间之内。",
      btn: "查看未完成",
      toast: "已切换到未完成视图",
    },
    done: {
      strong: "还没有已完成任务",
      desc: "完成任务后会显示在这里。",
      btn: "查看任务中心",
      toast: "暂无已完成任务可查看",
    },
    all: {
      strong: "暂无任务",
      desc: "添加一个新任务开始吧。",
      btn: "添加任务",
      toast: "请输入任务内容",
    },
  }

  if (!filtered.length) {
    var e = emptyTexts[state.taskFilter] || emptyTexts.todo
    list.innerHTML =
      '<div class="empty-state"><div><div class="empty-illustration"></div><strong>' +
      e.strong +
      "</strong><div>" +
      e.desc +
      '</div><button class="empty-action" data-toast="' +
      e.toast +
      '">' +
      e.btn +
      "</button></div></div>"
  } else {
    list.innerHTML = filtered
      .map((task) => {
        var isOverdue = _isTaskOverdue(task)
        var rowClass = task.done ? "done" : isOverdue ? "overdue-row" : ""
        var deadlineHtml = task.deadline
          ? '<span class="task-time' +
            (isOverdue ? " overdue" : "") +
            '">' +
            escapeHTML(_formatDeadline(task.deadline)) +
            "</span>"
          : ""
        var overdueBadge = isOverdue
          ? '<span class="task-overdue-badge">⏰已过期</span>'
          : ""
        return (
          '<div class="task-row ' +
          rowClass +
          '">' +
          '<input type="checkbox" data-task-id="' +
          task.id +
          '" ' +
          (task.done ? "checked" : "") +
          "/>" +
          '<span class="task-title">' +
          escapeHTML(task.title) +
          "</span>" +
          '<span class="task-tag">' +
          escapeHTML(task.tag) +
          deadlineHtml +
          overdueBadge +
          "</span>" +
          '<button class="task-delete" type="button" data-delete-task="' +
          task.id +
          '" aria-label="删除任务 ' +
          escapeHTML(task.title) +
          '"><svg class="icon" style="width:14px;height:14px"><use href="#i-close"/></svg></button>' +
          "</div>"
        )
      })
      .join("")
  }

  $$("[data-task-id]").forEach((input) => {
    input.addEventListener("change", (event) => {
      var task = state.tasks.find(
        (item) => item.id === Number(event.target.dataset.taskId),
      )
      task.done = event.target.checked
      saveTasks()
      updateTaskRemote(task).catch((error) => {
        console.warn("Task update stayed local.", error)
      })
      renderTasks()
      updateSidebarBadge()
      showToast(task.done ? "任务已完成" : "任务已恢复为未完成")
    })
  })
  $$("[data-delete-task]").forEach((button) => {
    button.addEventListener("click", async () => {
      var taskId = Number(button.dataset.deleteTask)
      state.tasks = state.tasks.filter((task) => task.id !== taskId)
      state.pendingDeletes.add(taskId)
      savePendingDeletes()
      saveTasks()
      try {
        await deleteTaskRemote(taskId)
        state.pendingDeletes.delete(taskId)
        savePendingDeletes()
      } catch (error) {
        console.warn("Task delete stayed local.", error)
      }
      renderTasks()
      updateSidebarBadge()
      showToast("任务已删除")
    })
  })
  renderWorkbenchOverview()
  bindToasts()
}

function updateSidebarBadge() {
  var undoneCount = state.tasks.filter((t) => !t.done).length
  var hasOverdue = state.tasks.some((t) => _isTaskOverdue(t))
  var badgeLink = document.querySelector('.side-link[data-badge="tasks"]')
  if (!badgeLink) return
  var badge = badgeLink.querySelector("small")
  if (!badge) {
    badge = document.createElement("small")
    badgeLink.appendChild(badge)
  }
  badge.textContent = undoneCount
  badge.style.display = undoneCount > 0 ? "" : "none"
  if (hasOverdue) {
    badge.classList.add("badge-danger")
  } else {
    badge.classList.remove("badge-danger")
  }
  fetchUnreadCount()
}

// ── Notification bell: local overdue task alerts, backend contract-ready ──
var _sseConnection = null
var _localNotificationTimer = null
var _taskDeadlineRefreshTimer = null
var _maxTaskDeadlineRefreshDelay = 2147483647

function notificationsContractMissing(context) {
  console.warn("Notifications API contract missing.", context)
  return []
}

function getLocalOverdueTaskNotifications() {
  return state.tasks
    .filter((task) => _isTaskOverdue(task))
    .map((task) => {
      var deadline = task.deadline ? _formatDeadline(task.deadline) : ""
      return {
        id: "task-overdue-" + task.id,
        is_read: false,
        title: "待办已过期",
        content:
          task.title + (deadline ? " · 截止 " + deadline : ""),
        created_at: task.deadline || new Date().toISOString(),
        taskId: task.id,
        type: "task-overdue",
        action_label: "查看过期待办",
      }
    })
}

function renderLocalOverdueTaskNotifications() {
  if (
    !window.App ||
    !window.App.components ||
    !window.App.components.notificationBell
  )
    return
  App.components.notificationBell.renderList(getLocalOverdueTaskNotifications())
  fetchUnreadCount()
}

function scheduleNextTaskDeadlineRefresh() {
  if (_taskDeadlineRefreshTimer) {
    clearTimeout(_taskDeadlineRefreshTimer)
    _taskDeadlineRefreshTimer = null
  }
  var now = Date.now()
  var nextDeadlineTime = null
  state.tasks.forEach((task) => {
    var deadlineTime = getTaskDeadlineTime(task)
    if (task.done || deadlineTime === null || deadlineTime <= now) return
    if (nextDeadlineTime === null || deadlineTime < nextDeadlineTime) {
      nextDeadlineTime = deadlineTime
    }
  })
  if (nextDeadlineTime === null) return
  var delay = Math.min(nextDeadlineTime - now, _maxTaskDeadlineRefreshDelay)
  _taskDeadlineRefreshTimer = setTimeout(refreshTaskDeadlineState, delay)
}

function refreshTaskDeadlineState() {
  renderLocalOverdueTaskNotifications()
  renderTasks()
  updateSidebarBadge()
  scheduleNextTaskDeadlineRefresh()
}

function openOverdueTaskNotification(notificationId) {
  if (!String(notificationId || "").startsWith("task-overdue-")) return
  state.taskFilter = "overdue"
  $$(".tab[data-task-filter]").forEach((item) =>
    item.classList.toggle("active", item.dataset.taskFilter === "overdue"),
  )
  openSubTab("workspace", "cockpit-tasks", "待办事务")
  renderTasks()
}

function startNotificationStream() {
  if (_sseConnection) {
    _sseConnection.close()
  }
  notificationsContractMissing({ operation: "stream" })
  if (_localNotificationTimer) clearInterval(_localNotificationTimer)
  fetchUnreadCount()
  scheduleNextTaskDeadlineRefresh()
  _localNotificationTimer = setInterval(fetchUnreadCount, 60000)
}

function stopNotificationStream() {
  if (_sseConnection) {
    _sseConnection.close()
    _sseConnection = null
  }
  if (_localNotificationTimer) {
    clearInterval(_localNotificationTimer)
    _localNotificationTimer = null
  }
  if (_taskDeadlineRefreshTimer) {
    clearTimeout(_taskDeadlineRefreshTimer)
    _taskDeadlineRefreshTimer = null
  }
}

const assetViews = {
  notices: {
    view: "notice-center",
    target: "noticeCenterContent",
    title: "公告中心",
    detailKey: "id",
    nameKey: "title",
  },
  documents: {
    view: "document-center",
    target: "documentCenterContent",
    title: "文档中心",
    detailKey: "id",
    nameKey: "name",
  },
  resources: {
    view: "resource-center",
    target: "resourceCenterContent",
    title: "资源库",
    detailKey: "code",
    nameKey: "title",
  },
  services: {
    view: "service-center",
    target: "serviceCenterContent",
    title: "服务中心",
    detailKey: "code",
    nameKey: "title",
  },

  news: {
    view: "news-center",
    target: "newsCenterContent",
    title: "资讯中心",
    detailKey: "id",
    nameKey: "title",
  },
}

function getPortalAssetCollectionItems(collection) {
  if (!assetViews[collection]) return []
  return Array.isArray(state[collection]) ? state[collection] : []
}

const subsystemWorkbenches = {
  default: {
    title: "业务事项",
    columns: ["事项", "状态", "负责人", "更新时间"],
    records: [],
    related: ["关联公告", "关联文档", "关联资源", "关联服务"],
  },
  supervision: {
    title: "督办事项",
    columns: ["事项", "状态", "责任人", "截止时间"],
    records: [],
    related: ["办理规范", "督办公告", "责任清单"],
  },
  "teaching-cloud": {
    title: "教学运行",
    columns: ["事项", "状态", "负责单位", "更新时间"],
    records: [],
    related: ["教学通知", "课程文档", "教学服务"],
  },
  oa: {
    title: "待办流程",
    columns: ["流程", "状态", "处理人", "更新时间"],
    records: [],
    related: ["办公通知", "流程制度", "常用表单"],
  },
  website: {
    title: "站点发布",
    columns: ["站点事项", "状态", "负责人", "更新时间"],
    records: [],
    related: ["发布规范", "网站公告", "素材资源"],
  },
  party: {
    title: "党建台账",
    columns: ["事项", "状态", "责任组织", "更新时间"],
    records: [],
    related: ["学习资料", "活动公告", "工作手册"],
  },
  alumni: {
    title: "校友关系",
    columns: ["事项", "状态", "负责人", "更新时间"],
    records: [],
    related: ["活动公告", "联络模板", "服务资源"],
  },
  hr: {
    title: "人员服务",
    columns: ["服务事项", "状态", "经办人", "更新时间"],
    records: [],
    related: ["人事制度", "证明模板", "考勤说明"],
  },
  student: {
    title: "学生事务",
    columns: ["事务", "状态", "负责单位", "更新时间"],
    records: [],
    related: ["学生公告", "办事指南", "心理服务"],
  },
  employment: {
    title: "就业服务",
    columns: ["事项", "状态", "负责人", "更新时间"],
    records: [],
    related: ["招聘公告", "就业指导", "数据看板"],
  },
  "mental-health": {
    title: "心理服务",
    columns: ["事项", "状态", "负责单位", "更新时间"],
    records: [],
    related: ["心理资源", "预约说明", "关怀制度"],
  },
  finance: {
    title: "报销单",
    columns: ["财务事项", "状态", "经办人", "更新时间"],
    records: [],
    related: ["财务制度", "报销指南", "预算说明"],
  },
  estate: {
    title: "房间台账",
    columns: ["空间事项", "状态", "管理单位", "更新时间"],
    records: [],
    related: ["用房制度", "报修服务", "空间资料"],
  },
  assets: {
    title: "资产台账",
    columns: ["资产事项", "状态", "负责人", "更新时间"],
    records: [],
    related: ["资产制度", "报修工单", "盘点资料"],
  },
  "data-portal": {
    title: "指标看板",
    columns: ["数据主题", "状态", "归属部门", "更新时间"],
    records: [],
    related: ["经营看板", "数据资源", "指标口径"],
  },
  repair: {
    title: "报修工单",
    columns: ["工单", "状态", "处理人", "更新时间"],
    records: [],
    related: ["报修指南", "资产目录", "服务评价"],
  },
}

function normalizeSubsystem(item, index = 0) {
  if (typeof item === "string") {
    return {
      code: `system-${index + 1}`,
      name: item,
      category: "信息系统",
      description: `${item}的平台内部子系统入口。`,
      status: "active",
      entry_type: "internal",
      owner_department: "综合服务台",
      owner_name: "综合服务台",
      support_contact: "综合服务台",
      icon_tone: [
        "app-orange",
        "app-purple",
        "app-red",
        "app-blue",
        "app-green",
      ][index % 5],
      common_actions: [{ label: "查看概览" }],
      related_resources: [],
    }
  }
  return {
    common_actions: [],
    related_resources: [],
    icon_tone: "app-blue",
    status: "active",
    entry_type: "internal",
    ...item,
  }
}

function normalizeService(item, index = 0) {
  if (typeof item === "string")
    return {
      code: `service-${index + 1}`,
      title: item,
      category: "服务分类",
      description: `${item}的办理说明和材料要求。`,
      status: "active",
      contact: "综合服务台",
    }
  return item
}

function normalizeNotice(item, index = 0) {
  if (typeof item === "string")
    return {
      id: index + 1,
      title: item,
      source: "门户公告",
      category: "公告",
      body: item,
    }
  return item
}

function normalizeNews(item, index = 0) {
  if (!item)
    return {
      id: index + 1,
      title: "",
      source: "资讯中心",
      category: "资讯",
      body: "",
    }
  if (item.id) return item
  return {
    id: index + 1,
    body: item.title || "",
    published_at: item.date || "",
    category: (item.tags || [])[0] || "资讯",
    ...item,
  }
}

function renderShortcuts() {
  if (!$("#shortcutList")) return
  $("#shortcutList").innerHTML = state.shortcuts
    .map(
      ([title, desc, tone], index) =>
        `<button class="shortcut" data-shortcut-index="${index}"><span class="app-icon ${tone}">${title.slice(0, 1)}</span><span><strong>${escapeHTML(title)}</strong><small>${escapeHTML(desc)}</small></span></button>`,
    )
    .join("")
  $$("[data-shortcut-index]").forEach((button) =>
    button.addEventListener("click", () =>
      openShortcut(Number(button.dataset.shortcutIndex)),
    ),
  )
}

function openShortcut(index) {
  const item = state.shortcuts[index]
  if (!item) return
  const title = item[0]
  const routes = {
    公告: "notices",
    日历: "calendar",
    待办中心: "workspace",
    融合门户: "portal",
    智能问答: "knowledge",
    服务: "services",
    表单: "services",
    会议: "calendar",
  }
  if (routes[title] && assetViews[routes[title]])
    return renderAssetCenter(routes[title])
  if (routes[title]) return setView(routes[title])
  const subsystem = state.systems
    .map(normalizeSubsystem)
    .find(
      (system) =>
        system.name.includes(title) || title.includes(system.name.slice(0, 2)),
    )
  if (subsystem) return openSubsystem(subsystem.code)
  renderAssetCenter("resources")
}

function renderWorkspaceAssets() {
  renderSidebarDocuments()
  bindAssetOpeners()
  bindAssetCenterOpeners()
  renderCockpit()
}

function renderSidebarDocuments() {
  var list = $("#sidebarDocsList")
  if (!list) return
  var recent = state.documents.slice(0, 5)
  if (!recent.length) {
    list.innerHTML = '<div class="sidebar-docs-empty">暂无最近文档</div>'
    return
  }
  list.innerHTML = recent
    .map((item) => {
      var ft = escapeHTML(item.file_type || "D")
      var name = escapeHTML(item.name || "未命名文档")
      var time = formatShortDate(item.updated_at)
      return (
        '<button class="sidebar-doc-item" data-open-asset="documents:' +
        item.id +
        '">' +
        '<span class="sidebar-doc-icon">' +
        ft +
        "</span>" +
        '<span class="sidebar-doc-info">' +
        '<span class="sidebar-doc-name">' +
        name +
        "</span>" +
        '<span class="sidebar-doc-time">' +
        time +
        "</span>" +
        "</span>" +
        "</button>"
      )
    })
    .join("")
  bindAssetOpeners()
}

function renderWorkspaceAssistant() {
  var stream = $("#assistantStream")
  if (stream) {
    stream.innerHTML = ASSISTANT_MOCK_MESSAGES.map(
      (msg) =>
        '<div class="assistant-msg"><span class="assistant-avatar">' +
        escapeHTML(msg.actor[0]) +
        "</span>" +
        "<div><p><strong>" +
        escapeHTML(msg.actor) +
        "</strong> " +
        escapeHTML(msg.action) +
        "</p>" +
        "<time>" +
        escapeHTML(msg.time) +
        "</time></div></div>",
    ).join("")
  }
}

function formatShortDate(value) {
  if (!value) return ""
  const text = String(value)
  if (/^\d{4}-\d{2}-\d{2}/.test(text))
    return text.slice(5, 10).replace("-", "/")
  return text
}

async function fetchPortalPreferences() {
  const payload =
    loadPortalPreferencesFromLocalCache() || state.portalPreferences || {}
  state.portalPreferences = payload
  return payload
}

async function savePortalPreferences(
  nextPreferences = state.portalPreferences,
) {
  if (!isLoggedIn()) return
  state.portalPreferences = nextPreferences || {}
  savePortalPreferencesToLocalCache(state.portalPreferences)
}

async function fetchPortalDashboard() {
  const dashboardService = requireAppRuntimeService("dashboard", "getDashboard")
  const payload = await dashboardService.getDashboard()
  state.portalDashboard = payload
  renderPortalDashboard()
  return payload
}

function renderPortalDashboard() {
  const dashboard = state.portalDashboard || {}
  const workspaceTarget = $("#dashboard-overview")
  if (workspaceTarget) {
    workspaceTarget.innerHTML = `<div class="workspace-metric"><strong>${dashboard.subsystems_total ?? state.systems.length}</strong><span>内部子系统</span></div><div class="workspace-metric"><strong>${dashboard.subsystems_active ?? 0}</strong><span>启用系统</span></div><div class="workspace-metric"><strong id="dashboardTodoCount">${state.tasks.filter((task) => !task.done).length} 项</strong><span>今日待办</span></div><div class="workspace-metric"><strong>${dashboard.visits_7d ?? 0}</strong><span>近 7 日访问</span></div>`
  }
  const target = $("#portalDashboardContent")
  if (target) {
    target.innerHTML = `<article class="internal-card"><div class="card-header"><div class="card-title">平台经营统计</div><button class="card-link" id="refreshPortalDashboard">刷新</button></div><div class="card-body"><div class="workspace-metrics"><div class="workspace-metric"><strong>${dashboard.subsystems_total ?? 0}</strong><span>内部子系统</span></div><div class="workspace-metric"><strong>${dashboard.notices_total ?? 0}</strong><span>公告</span></div><div class="workspace-metric"><strong>${dashboard.services_total ?? 0}</strong><span>服务</span></div><div class="workspace-metric"><strong>${dashboard.documents_total ?? 0}</strong><span>文档</span></div></div></div></article>`
    $("#refreshPortalDashboard")?.addEventListener("click", () =>
      fetchPortalDashboard().catch((error) =>
        showToast(error.message || "看板刷新失败"),
      ),
    )
  }
}

// ── 信息系统: category tabs + GridStack draggable cards ───────────
const SYSTEM_CATEGORIES = [
  "办公行政类",
  "人力组织类",
  "经营业务类",
  "财资后勤 & 支撑类",
]
const CATEGORY_COLORS = {
  办公行政类: "#2563eb",
  人力组织类: "#16a34a",
  经营业务类: "#ea580c",
  "财资后勤 & 支撑类": "#7c3aed",
}
var _systemGrid = null
var _cockpitShortcutGrid = null
var _cockpitSaveShortcutOrderTimer = null
var _activeSystemCategory =
  (state.portalPreferences && state.portalPreferences.system_active_category) ||
  "办公行政类"
var _saveOrderTimer = null

// ── Read current grid node order as code array ──────────────────────
function _readGridOrder() {
  if (!_systemGrid) return null
  var nodes = _systemGrid.engine.nodes.slice().sort((a, b) => {
    if (a.y !== b.y) return a.y - b.y
    return a.x - b.x
  })
  var order = []
  nodes.forEach((n) => {
    var card = n.el && n.el.querySelector && n.el.querySelector(".system-card")
    if (card) order.push(card.dataset.subsystemCode)
  })
  return order.length > 0 ? order : null
}

// ── Persist the current grid order (debounced wrapper) ─────────────
function _scheduleOrderSave() {
  clearTimeout(_saveOrderTimer)
  _saveOrderTimer = setTimeout(_commitOrderSave, 100)
}

async function _commitOrderSave() {
  if (!_systemGrid) return
  var order = _readGridOrder()
  if (!order) return
  if (!state.portalPreferences) state.portalPreferences = {}
  if (!state.portalPreferences.system_order)
    state.portalPreferences.system_order = {}
  // Only save if the order actually changed
  var prev = state.portalPreferences.system_order[_activeSystemCategory]
  if (
    prev &&
    prev.length === order.length &&
    prev.every((code, i) => code === order[i])
  )
    return
  state.portalPreferences.system_order[_activeSystemCategory] = order
  await savePortalPreferences(state.portalPreferences)
}

// ── Flush any pending save NOW (call before destroying grid) ───────
function _flushOrderSave() {
  clearTimeout(_saveOrderTimer)
  if (!_systemGrid) return
  var order = _readGridOrder()
  if (!order) return
  if (!state.portalPreferences) state.portalPreferences = {}
  if (!state.portalPreferences.system_order)
    state.portalPreferences.system_order = {}
  state.portalPreferences.system_order[_activeSystemCategory] = order
  // Fire-and-forget — no await needed, we're about to destroy the grid
  savePortalPreferences(state.portalPreferences)
}

function renderSubsystems() {
  var grid = $("#systemGrid")
  var tabs = $("#systemCategories")
  if (!grid || !tabs) return

  tabs.innerHTML = SYSTEM_CATEGORIES.map((cat) => {
    var active = cat === _activeSystemCategory ? " active" : ""
    return (
      '<button class="category-tab' +
      active +
      '" data-category="' +
      escapeHTML(cat) +
      '">' +
      escapeHTML(cat) +
      "</button>"
    )
  }).join("")

  var systems = state.systems
    .map(normalizeSubsystem)
    .filter((s) => s.category === _activeSystemCategory)
  var color = CATEGORY_COLORS[_activeSystemCategory] || "#2563eb"

  // ── Saved order (migrate old GridStack layouts on first load) ──
  if (!state.portalPreferences) state.portalPreferences = {}
  if (!state.portalPreferences.system_order) {
    state.portalPreferences.system_order = {}
    var oldLayouts = state.portalPreferences.system_layouts || {}
    var hadLayouts = false
    Object.keys(oldLayouts).forEach((cat) => {
      var items = oldLayouts[cat] || []
      if (items.length === 0) return
      hadLayouts = true
      // Sort by y then x to recover visual order from old coordinate layouts
      items.sort((a, b) => (a.y !== b.y ? a.y - b.y : a.x - b.x))
      state.portalPreferences.system_order[cat] = items
        .map((item) => item.code)
        .filter(Boolean)
    })
    if (hadLayouts) {
      delete state.portalPreferences.system_layouts
      savePortalPreferences(state.portalPreferences)
    }
  }
  var savedOrder =
    state.portalPreferences.system_order[_activeSystemCategory] || []

  // Sort systems: saved-order first, new/unknown items append by name
  var codeIndex = {}
  savedOrder.forEach((code, i) => {
    codeIndex[code] = i
  })
  systems.sort((a, b) => {
    var ai = codeIndex[a.code] !== undefined ? codeIndex[a.code] : 9999
    var bi = codeIndex[b.code] !== undefined ? codeIndex[b.code] : 9999
    if (ai !== bi) return ai - bi
    return a.name.localeCompare(b.name, "zh-Hans-CN")
  })

  // ── Build grid ──
  grid.innerHTML = '<div class="grid-stack"></div>'
  var gsEl = grid.querySelector(".grid-stack")
  if (_systemGrid) {
    try {
      _systemGrid.destroy(false)
    } catch (e) {}
  }

  var MARGIN = 8
  _systemGrid = window.GridStack.init(
    {
      column: 12,
      cellHeight: 1,
      margin: MARGIN,
      float: false,
      animate: true,
      disableResize: true,
      swap: true,
    },
    gsEl,
  )

  // ── On manual swap: schedule a debounced save ──
  _systemGrid.on("change", _scheduleOrderSave)

  // Measure column width for predicting card text-wrap
  var gsW = gsEl.clientWidth
  var colW = Math.floor((gsW - 11 * MARGIN) / 12)
  if (colW < 60) colW = 60
  var cardW = colW * 4 + MARGIN * 3

  var measureWrap = document.createElement("div")
  measureWrap.style.cssText =
    "position:absolute;visibility:hidden;top:-9999px;left:0;"
  measureWrap.style.width = cardW + "px"
  document.body.appendChild(measureWrap)

  // ── First pass: measure all card heights, find the max ──
  var cardSpecs = systems.map((system) => {
    var statusLabel =
      system.entry_type === "internal"
        ? "已上线"
        : system.entry_type === "iframe"
          ? "外部接入"
          : "未开通"
    var cardHTML =
      '<div class="system-card" data-subsystem-code="' +
      escapeHTML(system.code) +
      '" style="border-top:3px solid ' +
      color +
      '">' +
      '<span class="system-card-icon" style="background:' +
      color +
      '">' +
      escapeHTML(system.name).slice(0, 1) +
      "</span>" +
      '<span class="system-card-body"><strong>' +
      escapeHTML(system.name) +
      "</strong>" +
      "<em>" +
      escapeHTML(system.description || "") +
      "</em>" +
      '<small class="status-pill ' +
      escapeHTML(system.entry_type) +
      '">' +
      statusLabel +
      "</small></span>" +
      "</div>"
    measureWrap.innerHTML = cardHTML
    var naturalH = measureWrap.firstElementChild.offsetHeight
    return { cardHTML: cardHTML, h: Math.max(80, naturalH + 10) }
  })
  document.body.removeChild(measureWrap)

  // Use max height so GridStack swap works (requires same-sized items)
  var maxH = cardSpecs.reduce((m, s) => Math.max(m, s.h), 80)

  // ── Second pass: create widgets (batchUpdate suppresses change events) ──
  _systemGrid.batchUpdate()
  cardSpecs.forEach((spec, i) => {
    var gsItem = document.createElement("div")
    gsItem.className = "grid-stack-item"
    var gsContent = document.createElement("div")
    gsContent.className = "grid-stack-item-content"
    gsContent.innerHTML = spec.cardHTML
    gsItem.appendChild(gsContent)

    _systemGrid.makeWidget(gsItem, { w: 4, h: maxH, autoPosition: true })
  })
  _systemGrid.batchUpdate(false)

  // Save initial order only if this category has no saved order yet.
  // Otherwise the saved order (possibly from a user swap) is authoritative.
  if (
    !state.portalPreferences.system_order[_activeSystemCategory] ||
    state.portalPreferences.system_order[_activeSystemCategory].length === 0
  ) {
    clearTimeout(_saveOrderTimer)
    _commitOrderSave()
  }

  // Click to open subsystem
  $$("#systemGrid .system-card").forEach((card) => {
    card.addEventListener("click", () => {
      openSubsystem(card.dataset.subsystemCode)
    })
  })
}

function bindCategoryTabs() {
  $$("#systemCategories .category-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      // Flush pending save for current tab BEFORE switching
      _flushOrderSave()
      _activeSystemCategory = btn.dataset.category
      if (!state.portalPreferences) state.portalPreferences = {}
      state.portalPreferences.system_active_category = _activeSystemCategory
      savePortalPreferences(state.portalPreferences)
      renderSubsystems()
      bindCategoryTabs()
    })
  })
  var csb = $("#customSystemBtn")
  if (csb) {
    csb.onclick = () => {
      showToast("自定义系统功能即将上线")
    }
  }
}

function renderSubsystemAction(action, index = 0) {
  const normalized =
    typeof action === "string"
      ? { label: action, kind: "overview" }
      : action || {}
  const kind = normalized.kind || (index === 0 ? "overview" : "resources")
  const label = normalized.label || "查看概览"
  const iconId =
    kind === "services"
      ? "i-folder"
      : kind === "resources"
        ? "i-file"
        : kind === "dashboard"
          ? "i-chart"
          : "i-grid"
  return `<button class="subsystem-action" type="button" data-subsystem-action="${escapeHTML(kind)}">${icon(iconId)}${escapeHTML(label)}</button>`
}

const _enterpriseSubsystemCodes = new Set(["repair", "fixed-assets", "oa"])

async function getSubsystemWorkbench(code) {
  // Phase 2: fetch real enterprise data for repair/assets/oa
  if (_enterpriseSubsystemCodes.has(code)) {
    try {
      var resp = await apiJson(
        "/__frontend_missing_contract__/enterprise/subsystems/" + code + "/records",
      )
      if (resp.ok) {
        var data = await resp.json()
        return {
          title: data.title || subsystemWorkbenches[code]?.title || "业务记录",
          columns: data.columns || [],
          records: (data.records || []).map((r) => ({
            id: r.id,
            title: r.title || r.name || "",
            status: r.status || "",
            owner: r.assignee || r.custodian || r.current_handler || "",
            updated: (r.updated_at || "").slice(0, 10),
            detail: _formatEnterpriseRecordDetail(code, r),
            _raw: r,
          })),
          metrics: data.metrics || {},
          related: [],
          _enterprise: true,
          _code: code,
        }
      }
    } catch (e) {
      // fall through to local fallback
    }
  }
  return subsystemWorkbenches[code] || subsystemWorkbenches.default
}

function _formatEnterpriseRecordDetail(code, record) {
  if (code === "repair") {
    return (
      "位置: " +
      (record.location || "-") +
      " | 优先级: " +
      (record.priority || "-") +
      " | 报修人: " +
      (record.requester_id || "-")
    )
  }
  if (code === "assets") {
    return (
      "编号: " +
      (record.asset_code || "-") +
      " | 分类: " +
      (record.category || "-") +
      " | 位置: " +
      (record.location || "-")
    )
  }
  if (code === "oa") {
    return (
      "类型: " +
      (record.flow_type || "-") +
      " | 发起人: " +
      (record.initiator_id || "-")
    )
  }
  return ""
}

function subsystemStatusText(status) {
  return status === "active"
    ? "正常运行"
    : status === "maintenance"
      ? "维护中"
      : "已停用"
}

function renderSubsystemMetrics(workbench, system) {
  const records = workbench.records || []
  const pending = records.filter((record) =>
    /(待|进行|处理|审核|确认|分派|筹备|submitted|processing|pending)/.test(
      record.status || "",
    ),
  ).length
  const completed = records.filter((record) =>
    /(已|正常|可访问|可办理|可提交|completed|approved|available|rated)/.test(
      record.status || "",
    ),
  ).length
  var createBtn = ""
  if (workbench._enterprise) {
    var code = workbench._code
    var label =
      code === "repair"
        ? "新建工单"
        : code === "assets"
          ? "新建资产"
          : "新建流程"
    createBtn =
      '<div class="subsystem-metric"><button class="btn btn-primary btn-sm" id="enterpriseCreateBtn" data-enterprise-code="' +
      code +
      '">' +
      label +
      "</button></div>"
  }
  return (
    '<div class="subsystem-metrics"><div class="subsystem-metric"><strong>' +
    records.length +
    '</strong><span>业务记录</span></div><div class="subsystem-metric"><strong>' +
    pending +
    '</strong><span>待处理</span></div><div class="subsystem-metric"><strong>' +
    completed +
    '</strong><span>已就绪</span></div><div class="subsystem-metric"><strong>' +
    subsystemStatusText(system.status) +
    "</strong><span>运行状态</span></div>" +
    createBtn +
    "</div>"
  )
}

function renderSubsystemRecordList(workbench) {
  var columns = workbench.columns || subsystemWorkbenches.default.columns
  var rows = workbench.records || []
  // Phase 2: use column-based rendering for enterprise subsystems
  if (workbench._enterprise && rows.length > 0) {
    var colKeys = columns.slice(0, 5) // show first 5 columns
    return (
      '<div id="subsystemRecords"><table class="subsystem-record-table"><thead><tr>' +
      colKeys.map((c) => "<th>" + escapeHTML(c) + "</th>").join("") +
      "</tr></thead><tbody>" +
      rows
        .map((record, index) => {
          var cells = colKeys
            .map((col) => {
              var val = record._raw ? record._raw[col] : record[col]
              if (val === null || val === undefined) val = "-"
              return "<td>" + escapeHTML(String(val)) + "</td>"
            })
            .join("")
          return (
            '<tr><td><button type="button" data-subsystem-record="' +
            index +
            '">' +
            escapeHTML(record.title) +
            "</button></td>" +
            cells +
            "</tr>"
          )
        })
        .join("") +
      "</tbody></table></div>"
    )
  }
  return (
    '<div id="subsystemRecords"><table class="subsystem-record-table"><thead><tr>' +
    columns.map((column) => "<th>" + escapeHTML(column) + "</th>").join("") +
    "</tr></thead><tbody>" +
    rows
      .map(
        (record, index) =>
          '<tr><td><button type="button" data-subsystem-record="' +
          index +
          '">' +
          escapeHTML(record.title) +
          "</button></td><td>" +
          escapeHTML(record.status) +
          "</td><td>" +
          escapeHTML(record.owner) +
          "</td><td>" +
          escapeHTML(record.updated) +
          "</td></tr>",
      )
      .join("") +
    "</tbody></table></div>"
  )
}

function renderSubsystemRecordDetail(workbench, index = 0) {
  const record =
    (workbench.records || [])[index] || (workbench.records || [])[0]
  if (!record)
    return `<div class="subsystem-record-detail" id="subsystemRecordDetail">暂无业务记录。</div>`
  return `<div class="subsystem-record-detail" id="subsystemRecordDetail"><strong>${escapeHTML(record.title)}</strong>${escapeHTML(record.detail || "当前业务记录可在本子系统内继续查看。")}</div>`
}

function bindSubsystemRecordOpeners(workbench) {
  $$("[data-subsystem-record]").forEach((button) => {
    button.onclick = () => {
      const target = $("#subsystemRecordDetail")
      if (target)
        target.outerHTML = renderSubsystemRecordDetail(
          workbench,
          Number(button.dataset.subsystemRecord || 0),
        )
    }
  })
  // Phase 2: enterprise create button
  var createBtn = document.getElementById("enterpriseCreateBtn")
  if (createBtn) {
    createBtn.onclick = () => {
      _showEnterpriseCreateForm(createBtn.dataset.enterpriseCode)
    }
  }
}

function _showEnterpriseCreateForm(code) {
  var titles = { repair: "新建报修工单", assets: "新建资产", oa: "新建OA流程" }
  var title = titles[code] || "新建"
  var fieldsHtml = ""
  if (code === "repair") {
    fieldsHtml =
      '<div class="field"><label>标题</label><input name="title" required maxlength="255"></div><div class="field"><label>位置</label><input name="location" required maxlength="255"></div><div class="field"><label>描述</label><textarea name="description" required rows="3"></textarea></div><div class="field"><label>优先级</label><select name="priority"><option value="normal">普通</option><option value="low">低</option><option value="high">高</option><option value="urgent">紧急</option></select></div>'
  } else if (code === "assets") {
    fieldsHtml =
      '<div class="field"><label>资产编号</label><input name="asset_code" required maxlength="128"></div><div class="field"><label>名称</label><input name="name" required maxlength="255"></div><div class="field"><label>分类</label><input name="category" required maxlength="128"></div><div class="field"><label>位置</label><input name="location" required maxlength="255"></div><div class="field"><label>保管人</label><input name="custodian" maxlength="128"></div>'
  } else if (code === "oa") {
    fieldsHtml =
      '<div class="field"><label>标题</label><input name="title" required maxlength="255"></div><div class="field"><label>流程类型</label><input name="flow_type" required maxlength="128"></div>'
  }
  var container = document.createElement("div")
  container.className = "modal-overlay"
  container.innerHTML =
    '<div class="modal-content"><div class="modal-header"><h2>' +
    title +
    '</h2><button class="modal-close-btn" id="enterpriseCreateClose">&times;</button></div><form id="enterpriseCreateForm"><div class="form-grid">' +
    fieldsHtml +
    '</div><div class="modal-actions"><button type="button" class="btn" id="enterpriseCreateCancel">取消</button><button type="submit" class="btn primary">提交</button></div></form></div>'
  document.body.appendChild(container)
  function close() {
    container.remove()
    document.removeEventListener("keydown", onKey)
  }
  function onKey(e) {
    if (e.key === "Escape") close()
  }
  document.addEventListener("keydown", onKey)
  container.addEventListener("click", (e) => {
    if (e.target === container) close()
  })
  document
    .getElementById("enterpriseCreateClose")
    .addEventListener("click", close)
  document
    .getElementById("enterpriseCreateCancel")
    .addEventListener("click", close)
  document
    .getElementById("enterpriseCreateForm")
    .addEventListener("submit", async (e) => {
      e.preventDefault()
      var formData = new FormData(e.target)
      var payload = {}
      formData.forEach((v, k) => {
        payload[k] = v
      })
      var endpoint = ""
      if (code === "repair") endpoint = "/__frontend_missing_contract__/enterprise/repair/tickets"
      else if (code === "assets") endpoint = "/__frontend_missing_contract__/enterprise/assets/items"
      else if (code === "oa") endpoint = "/__frontend_missing_contract__/enterprise/oa/flows"
      try {
        var resp = await apiJson(endpoint, {
          method: "POST",
          body: JSON.stringify(payload),
        })
        if (resp.ok) {
          close()
          showToast("创建成功")
          navigateTo("subsystem", state.selectedSubsystem?.code || code)
        } else {
          var err = await resp.json()
          showToast(err.detail || "创建失败")
        }
      } catch (err) {
        showToast("网络错误")
      }
    })
}

function renderSubsystemRelatedPanel(system, workbench) {
  const related = workbench.related?.length
    ? workbench.related
    : system.related_resources || []
  return `<article class="internal-card subsystem-card"><div class="card-header"><div class="card-title">关联内容</div></div><div class="card-body"><ul class="subsystem-related-list">${related.map((item, index) => `<li><span>${escapeHTML(item)}</span><strong>${index + 1}</strong></li>`).join("")}</ul></div></article>`
}

function handleSubsystemAction(kind) {
  const routes = {
    services: "services",
    resources: "resources",
    documents: "documents",
    notices: "notices",
    news: "news",
  }
  if (routes[kind]) {
    renderAssetCenter(routes[kind])
    return
  }
  if (kind === "dashboard") {
    setView("portal-dashboard")
    return
  }
  const targetId = kind === "records" ? "subsystemRecords" : "subsystemContent"
  document
    .getElementById(targetId)
    ?.scrollIntoView({ behavior: "smooth", block: "start" })
}

async function openSubsystem(code) {
  try {
    const subsystem = await apiJson(
      `/__frontend_missing_contract__/subsystems/${encodeURIComponent(code)}`,
    )
    state.selectedSubsystem = normalizeSubsystem(subsystem)
    apiJson(`/__frontend_missing_contract__/subsystems/${encodeURIComponent(code)}/visit`, {
      method: "POST",
    })
      .then((data) => {
        state.portalDashboard = {
          ...state.portalDashboard,
          visits_7d: data.visits_7d,
        }
        renderPortalDashboard()
      })
      .catch(() => {})
    setView("subsystem") // set view first (updates sidebar generically)
    await renderSubsystemView() // then override sidebar with menu_items
  } catch (error) {
    showToast(error.message || "子系统暂不可用")
  }
}

async function renderSubsystemView() {
  const system = state.selectedSubsystem
  if (!system) return
  $("#subsystemTitle").textContent = system.name
  $("#subsystemSummary").textContent =
    system.description || "平台内部子系统工作台"
  const menuItems = system.menu_items || []

  // ── Disabled shell subsystem ─────────────────────────────────────
  if (system.entry_type === "disabled") {
    $("#subsystemContent").innerHTML =
      `<div style="display:flex;align-items:center;justify-content:center;min-height:320px">
            <div style="text-align:center">
              <div style="font-size:48px;margin-bottom:16px">🚧</div>
              <h2 style="margin:0 0 8px">${escapeHTML(system.name)}</h2>
              <p style="color:var(--gray)">该子系统尚未开放，敬请期待。</p>
              <p style="color:var(--gray);font-size:13px">归属：${escapeHTML(system.owner_department || "")}　·　支持：${escapeHTML(system.support_contact || "")}</p>
            </div>
          </div>`
    renderSubsystemSidebar(system, [])
    return
  }

  // ── Iframe shell subsystem ───────────────────────────────────────
  if (system.entry_type === "iframe") {
    var embedUrl = system.entry_url || ""
    if (embedUrl) {
      $("#subsystemContent").innerHTML = `<iframe src="${escapeHTML(embedUrl)}"
              style="width:100%;height:calc(100vh - 180px);border:none;border-radius:8px"
              sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
              title="${escapeHTML(system.name)}"></iframe>`
    } else {
      $("#subsystemContent").innerHTML =
        `<div style="display:flex;align-items:center;justify-content:center;min-height:320px">
              <div style="text-align:center">
                <div style="font-size:48px;margin-bottom:16px">🔗</div>
                <h2 style="margin:0 0 8px">${escapeHTML(system.name)}</h2>
                <p style="color:var(--gray)">该子系统通过外部入口访问。</p>
                <p style="color:var(--gray);font-size:13px">请在管理后台配置入口地址。</p>
              </div>
            </div>`
    }
    renderSubsystemSidebar(system, [])
    return
  }

  // ── Dedicated view module ──────────────────────────────────────
  var viewModuleCode = system.code === "assets" ? "asset" : system.code
  if (
    window.App &&
    window.App.views &&
    typeof window.App.views[viewModuleCode] === "object" &&
    typeof window.App.views[viewModuleCode].render === "function"
  ) {
    window.App.views[viewModuleCode].render($("#subsystemContent"), {
      system: system,
    })
    renderSubsystemSidebar(system, menuItems)
    return
  }

  // ── Deep internal subsystem with workbench ───────────────────────
  const workbench = await getSubsystemWorkbench(system.code)
  const actions = system.common_actions?.length
    ? system.common_actions
    : [
        { label: "查看概览", kind: "overview" },
        { label: "关联资源", kind: "resources" },
        { label: "关联服务", kind: "services" },
      ]
  $("#subsystemContent").innerHTML =
    `<div class="subsystem-workbench-layout"><main class="subsystem-main-stack"><article class="internal-card subsystem-card"><div class="card-header"><div class="card-title">${escapeHTML(workbench.title)}</div><span class="status-pill ${escapeHTML(system.status)}">${subsystemStatusText(system.status)}</span></div><div class="card-body"><p class="subsystem-summary-line">${escapeHTML(system.description || "")}</p>${renderSubsystemMetrics(workbench, system)}<div class="subsystem-action-toolbar">${actions.map(renderSubsystemAction).join("")}</div>${renderSubsystemRecordList(workbench)}${renderSubsystemRecordDetail(workbench)}</div></article></main><aside class="subsystem-side-stack"><article class="internal-card subsystem-card"><div class="card-header"><div class="card-title">系统信息</div></div><div class="card-body"><ul class="detail-list"><li><span>权限状态</span><strong>${system.entry_type === "internal" ? "平台内可访问" : "外部入口"}</strong></li><li><span>最近访问</span><strong>${formatShortDate(system.last_visited_at) || "暂无记录"}</strong></li><li><span>分类</span><strong>${escapeHTML(system.category || "")}</strong></li><li><span>归属部门</span><strong>${escapeHTML(system.owner_department || "")}</strong></li><li><span>负责人</span><strong>${escapeHTML(system.owner_name || "")}</strong></li><li><span>支持入口</span><strong>${escapeHTML(system.support_contact || "")}</strong></li></ul></div></article>${renderSubsystemRelatedPanel(system, workbench)}</aside></div>`

  renderSubsystemSidebar(system, menuItems)

  $$("[data-subsystem-action]").forEach((button) => {
    button.onclick = () => handleSubsystemAction(button.dataset.subsystemAction)
  })
  bindSubsystemRecordOpeners(workbench)
}

function renderSubsystemSidebar(system, menuItems) {
  var title = $("#sidebarTitle")
  if (title) {
    title.hidden = false
    title.textContent = system.name || "子系统"
  }
  var html = ""
  if (menuItems && menuItems.length > 0) {
    for (var s = 0; s < menuItems.length; s++) {
      var section = menuItems[s]
      html +=
        '<div class="side-section">' +
        escapeHTML(section.section || "") +
        "</div>"
      var items = section.items || []
      for (var i = 0; i < items.length; i++) {
        var item = items[i]
        var iconName = item.icon || "i-file"
        html +=
          '<button class="side-link" data-submenu-href="' +
          escapeHTML(item.href || "") +
          '"><svg class="icon"><use href="#' +
          iconName +
          '"/></svg><span>' +
          escapeHTML(item.label || item.code || "") +
          "</span></button>"
      }
    }
    html += '<div class="side-section"></div>'
  }
  html +=
    '<button class="side-link" data-view-link="portal"><svg class="icon"><use href="#i-chevron-left"/></svg><span>返回门户</span></button>'
  $("#sidebarContent").innerHTML = html

  $$("#sidebarContent .side-link").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.dataset.viewLink) {
        setView(btn.dataset.viewLink)
        return
      }
      if (btn.dataset.submenuHref) {
        $$("#sidebarContent .side-link").forEach((el) => {
          el.classList.remove("active")
        })
        btn.classList.add("active")
        window.location.hash = btn.dataset.submenuHref
      }
    })
  })
}

async function renderAssetCenter(collection) {
  const config = assetViews[collection]
  if (!config) return
  const target = document.getElementById(config.target)
  const sourceItems = getPortalAssetCollectionItems(collection)
  const categories =
    collection === "services" ? getServiceCategories(sourceItems) : []
  if (
    collection === "services" &&
    _serviceCategory &&
    !categories.includes(_serviceCategory)
  ) {
    _serviceCategory = null
  }
  const items =
    collection === "services"
      ? sourceItems
          .map(normalizeService)
          .filter(
            (service) =>
              !_serviceCategory || service.category === _serviceCategory,
          )
      : sourceItems
  if (target) {
    const serviceMenu =
      collection === "services" ? renderServiceMenu(categories) : ""
    target.innerHTML = `<article class="internal-card"><div class="card-header"><div class="card-title">${config.title}</div><button class="card-link" data-refresh-asset-center="${collection}">刷新</button></div><div class="card-body">${serviceMenu}<div class="asset-grid">${items.map((item, index) => renderAssetItem(collection, item, index)).join("")}</div></div></article><article class="internal-card" id="${collection}Detail"><div class="card-body"><p>选择一项查看详情。</p></div></article>`
  }
  setView(config.view)
  bindAssetOpeners()
  if (collection === "services") bindServiceMenu()
  $$("[data-refresh-asset-center]").forEach((button) =>
    button.addEventListener("click", () =>
      renderAssetCenter(button.dataset.refreshAssetCenter),
    ),
  )
}

function getServiceCategories(items) {
  return items
    .map(normalizeService)
    .map((service) => service.category || "服务分类")
    .filter((category, index, list) => list.indexOf(category) === index)
}

function renderServiceMenu(categories) {
  const allActive = !_serviceCategory ? " active" : ""
  const buttons = [
    `<button class="category-tab${allActive}" data-service-category="">全部</button>`,
  ]
  categories.forEach((category) => {
    const active = category === _serviceCategory ? " active" : ""
    buttons.push(
      '<button class="category-tab' +
        active +
        '" data-service-category="' +
        escapeHTML(category) +
        '">' +
        escapeHTML(category) +
        "</button>",
    )
  })
  return '<div class="system-categories" id="serviceCategories">' +
    buttons.join("") +
    "</div>"
}

function bindServiceMenu() {
  $$("#serviceCategories [data-service-category]").forEach((button) => {
    button.addEventListener("click", () => {
      _serviceCategory = button.dataset.serviceCategory || null
      renderAssetCenter("services")
    })
  })
}

function renderAssetItem(collection, item, index) {
  const config = assetViews[collection]
  const asset = collection === "services" ? normalizeService(item, index) : item
  const key = asset[config.detailKey] ?? index + 1
  const title = asset[config.nameKey] || asset.title || asset.name || ""
  const desc =
    asset.description ||
    asset.summary ||
    asset.body ||
    asset.source ||
    asset.location ||
    ""
  return `<button class="asset-item" data-open-asset="${collection}:${key}"><strong>${escapeHTML(title)}</strong><p>${escapeHTML(desc).slice(0, 90)}</p><span class="asset-meta"><span>${escapeHTML(asset.category || asset.location || asset.source || "")}</span><span>${formatShortDate(asset.updated_at || asset.published_at)}</span></span></button>`
}

async function openPortalAsset(collection, key) {
  const config = assetViews[collection]
  if (!config) return
  let target = document.getElementById(`${collection}Detail`)
  if (!target || state.activeView !== config.view) {
    await renderAssetCenter(collection)
    target = document.getElementById(`${collection}Detail`)
  }
  const sourceItems = getPortalAssetCollectionItems(collection)
  state.selectedAsset =
    sourceItems.find((item, index) => {
      const asset = collection === "services" ? normalizeService(item, index) : item
      const itemKey = asset[config.detailKey] ?? index + 1
      return String(itemKey) === String(key)
    }) || null
  if (!state.selectedAsset) {
    showToast("内容暂不可用")
    return
  }
  const item = state.selectedAsset
  if (target) {
    const title = item[config.nameKey] || item.title || item.name || ""
    const desc = item.body || item.summary || item.description || ""
    target.innerHTML = `<div class="card-header"><div class="card-title">${escapeHTML(title)}</div></div><div class="card-body"><p>${escapeHTML(desc)}</p><ul class="detail-list"><li><span>分类</span><strong>${escapeHTML(item.category || item.location || "")}</strong></li><li><span>负责人</span><strong>${escapeHTML(item.owner || item.contact || item.source || "")}</strong></li><li><span>更新时间</span><strong>${formatShortDate(item.updated_at || item.published_at)}</strong></li></ul></div>`
  }
}

function bindAssetOpeners() {
  $$("[data-open-asset]").forEach((button) => {
    button.onclick = () => {
      const [collection, key] = button.dataset.openAsset.split(":")
      openPortalAsset(collection, key)
    }
  })
}

function bindAssetCenterOpeners() {
  $$("[data-open-asset-center]").forEach((button) => {
    button.onclick = () => renderAssetCenter(button.dataset.openAssetCenter)
  })
}

function getMonthCells(year, month) {
  const first = new Date(year, month, 1)
  const start = (first.getDay() + 6) % 7
  const days = new Date(year, month + 1, 0).getDate()
  const prevDays = new Date(year, month, 0).getDate()
  return Array.from({ length: 42 }, (_, index) => {
    const dayIndex = index - start + 1
    if (dayIndex < 1)
      return {
        day: prevDays + dayIndex,
        muted: true,
        date: new Date(year, month - 1, prevDays + dayIndex),
      }
    if (dayIndex > days)
      return {
        day: dayIndex - days,
        muted: true,
        date: new Date(year, month + 1, dayIndex - days),
      }
    return {
      day: dayIndex,
      muted: false,
      date: new Date(year, month, dayIndex),
    }
  })
}

function renderMiniCalendar(id) {
  const target = document.getElementById(id)
  if (!target) return
  const interactive = id === "miniMonth" || id === "portalMonth"
  target.innerHTML = getMonthCells(state.year, state.month)
    .map((cell) => {
      const key = dateKey(cell.date)
      const current = key === todayKey
      const hasEvent = state.events.some((event) => event.date === key)
      const selected = key === state.selectedScheduleDate
      const classes = `day ${cell.muted ? "muted" : ""} ${current ? "today" : ""} ${selected ? "selected" : ""} ${hasEvent ? "dot" : ""}`
      if (!interactive) return `<span class="${classes}">${cell.day}</span>`
      return `<button class="${classes}" type="button" data-schedule-date="${key}" aria-label="查看 ${key} 日程">${cell.day}</button>`
    })
    .join("")
  if (interactive) {
    $$("[data-schedule-date]").forEach((button) =>
      button.addEventListener("click", () => {
        state.selectedScheduleDate = button.dataset.scheduleDate
        typeof renderPortalSchedule === "function" && renderPortalSchedule()
        renderWorkbenchSchedule()
      }),
    )
    $$("[data-schedule-date]").forEach((button) =>
      button.addEventListener("dblclick", (event) => {
        event.preventDefault()
        openEventModalForDate(button.dataset.scheduleDate)
      }),
    )
  }
}

function formatScheduleDate(key) {
  const date = new Date(`${key}T00:00:00`)
  const weekdays = [
    "星期日",
    "星期一",
    "星期二",
    "星期三",
    "星期四",
    "星期五",
    "星期六",
  ]
  return `${date.getMonth() + 1} 月 ${date.getDate()} 日 · ${weekdays[date.getDay()]}`
}

function openEventModal(index = null) {
  state.editingEventIndex = index
  const eventItem = index === null ? null : state.events[index]
  $("#eventModalTitle").textContent = index === null ? "添加日程" : "编辑日程"
  const deleteButton = $("#eventDeleteButton")
  if (deleteButton) deleteButton.hidden = index === null
  $("#eventName").value = eventItem ? eventItem.title : ""
  $("#eventDate").value = eventItem
    ? eventItem.date
    : state.selectedScheduleDate
  $("#eventNote").value = ""
  const tone = eventItem ? eventItem.tone : "blue"
  const toneInput =
    $(`[name="eventTone"][value="${tone}"]`) || $('[name="eventTone"]')
  if (toneInput) toneInput.checked = true
  $("#eventModal").classList.add("show")
}

function openEventModalForDate(dateKeyValue) {
  if (dateKeyValue) state.selectedScheduleDate = dateKeyValue
  openEventModal()
}

function renderWorkbenchSchedule() {
  renderMiniCalendar("miniMonth")
  const panel = $("#workspaceSchedulePanel")
  if (!panel) return
  panel.innerHTML = renderSchedulePanel(false, "暂无日程安排")
  bindScheduleActions(panel)
}

function renderSchedulePanel(includeActions, emptyLabel) {
  const events = state.events
    .map((event, index) => ({ ...event, index }))
    .filter((event) => event.date === state.selectedScheduleDate)
  const actions = includeActions
    ? `<div class="quick-actions"><button class="quick-action" data-open-modal><svg class="icon"><use href="#i-calendar"/></svg>添加日程</button><button class="quick-action" data-toast="快速会议已准备"><svg class="icon"><use href="#i-video"/></svg>快速会议</button><button class="quick-action" data-toast="进入会议列表"><svg class="icon"><use href="#i-message"/></svg>加入会议</button></div>`
    : ""
  return `<div class="schedule-date">${formatScheduleDate(state.selectedScheduleDate)}</div>${events.length ? `<div class="schedule-list">${events.map((event) => `<button class="schedule-item ${event.tone}" data-edit-event="${event.index}"><span><strong>${event.title}</strong><span class="schedule-item-meta">${formatScheduleDate(event.date)}</span></span></button>`).join("")}</div>${actions}` : `<div class="schedule-empty"><strong>${emptyLabel}</strong>${actions}${includeActions ? "" : `<div>当前日期没有安排。</div>`}</div>`}`
}

function bindScheduleActions(scope) {
  $$("[data-open-modal]", scope).forEach((element) => {
    element.onclick = () => openEventModal()
  })
  bindEventEditors(scope)
  $$("[data-toast]", scope).forEach((element) => {
    element.onclick = () => showToast(element.dataset.toast)
  })
}

function bindEventEditors(scope = document) {
  $$("[data-edit-event]", scope).forEach((element) => {
    element.addEventListener("click", (event) => {
      event.stopPropagation()
    })
    element.addEventListener("dblclick", (event) => {
      event.stopPropagation()
      openEventModal(Number(element.dataset.editEvent))
    })
  })
}

function renderPortal() {
  // Restore saved active category (portalPreferences loaded async after module init)
  if (
    state.portalPreferences &&
    state.portalPreferences.system_active_category
  ) {
    _activeSystemCategory = state.portalPreferences.system_active_category
  }
  renderPortalProfile()
  renderPortalNews()
  renderSubsystems()
  bindCategoryTabs()
  renderPortalDashboard()
  renderWorkspaceAssets()
  bindToasts()
  bindAssetCenterOpeners()
  bindPortalEditTriggers()
}

function getTimeGreeting() {
  var h = new Date().getHours()
  if (h < 6) return "夜深了"
  if (h < 12) return "上午好"
  if (h < 14) return "中午好"
  if (h < 18) return "下午好"
  return "晚上好"
}

function renderPortalProfile() {
  const container = document.querySelector(
    "#portal-personal .card:first-child .card-body",
  )
  if (!container) return
  const p = state.portalProfile
  // Only show personal data when logged in; use auth as source of truth
  const loggedIn = isLoggedIn()
  const authName =
    (_authUser && (_authUser.display_name || _authUser.username)) || ""
  const displayName = loggedIn ? authName || p.name || "" : ""
  const email = loggedIn ? (_authUser && _authUser.email) || p.email || "" : ""
  const nameTrimmed = (displayName || "").trim()
  const initial = nameTrimmed ? nameTrimmed.charAt(0) : "?"
  const greeting = getTimeGreeting()
  const nameLine = displayName ? `${escapeHTML(displayName)}，${greeting}` : ""
  const deptText =
    loggedIn && p.department ? `组织机构：${escapeHTML(p.department)}` : ""
  const emailText = email ? "已绑定" : ""
  container.innerHTML = `<div class="profile-box"><div class="profile-photo">${escapeHTML(initial)}</div><div><strong>${nameLine || "请登录查看个人信息"}</strong>${deptText ? `<p>${deptText}</p>` : ""}</div></div><div class="stat-stack"><div class="stat-tile"><small>我管理的资产</small><strong>&mdash;</strong></div><div class="stat-tile"><small>待处理任务</small><strong>&mdash;</strong></div><div class="stat-tile"><small>我的邮箱</small><strong>${emailText || "&mdash;"}</strong></div></div>`
}

function renderPortalNews() {
  const container = document.querySelector(
    "#portal-personal .card:nth-child(2) .news-list",
  )
  if (!container) return
  const subscribed = new Set(state.newsSubscriptions)
  const sourceLabelById = allNewsSourcesById
  const news = (state.news.length ? state.news : portalNewsItems).map(
    normalizeNews,
  )
  const items = news.filter(
    (item) =>
      !subscribed.size ||
      subscribed.has(item.source) ||
      subscribed.has(item.category) ||
      subscribed.has(sourceLabelById[item.source]),
  )
  container.innerHTML = (items.length ? items : news.slice(0, 4))
    .map(
      (item) =>
        `<button class="feed-item news-item" data-open-asset="news:${item.id}"><span class="feed-mark alt"><svg class="icon"><use href="#i-message"/></svg></span><span><span class="feed-title">${escapeHTML(item.title)}</span><span class="feed-meta"><span>${escapeHTML(sourceLabelById[item.source] || item.source || "")}</span><span>${escapeHTML(item.category || "")}</span></span></span><span class="feed-time">${formatShortDate(item.published_at || item.date)}</span></button>`,
    )
    .join("")
  bindAssetOpeners()
}

function renderNewsSubModal() {
  const grid = $("#newsSubGrid")
  if (!grid) return
  const subs = new Set(state.newsSubscriptions)
  const dynamicSources = (state.news || [])
    .map(normalizeNews)
    .map((item) => item.source)
    .filter(Boolean)
  const sources = [
    ...allNewsSources,
    ...dynamicSources.map((source) => ({ id: source, label: source })),
  ]
  const uniqueSources = sources.filter(
    (source, index, list) =>
      list.findIndex((item) => item.id === source.id) === index,
  )
  grid.innerHTML = uniqueSources
    .map(
      (s) =>
        `<label class="sub-line"><input type="checkbox" value="${escapeHTML(s.id)}" ${subs.has(s.id) || subs.has(s.label) ? "checked" : ""} />${escapeHTML(s.label)}</label>`,
    )
    .join("")
}

function renderServiceSubModal() {
  const grid = $("#serviceSubGrid")
  if (!grid) return
  const subs = new Set(state.serviceSubscriptions)
  grid.innerHTML = state.services
    .map(normalizeService)
    .map(
      (service) =>
        `<label class="sub-line"><input type="checkbox" value="${escapeHTML(service.code)}" ${subs.has(service.code) || subs.has(service.title) ? "checked" : ""} />${escapeHTML(service.title)}</label>`,
    )
    .join("")
}

function updateMonthTitles() {
  const title = `${state.year} 年 ${state.month + 1} 月`
  const miniTitle = $("#miniMonthTitle")
  const sideTitle = $("#sideMonthTitle")
  if (miniTitle) miniTitle.textContent = title
  if (sideTitle) sideTitle.textContent = title
  const calendarTitle = $("#calendarMonthTitle")
  if (calendarTitle) calendarTitle.textContent = title
}

function renderCalendar() {
  updateMonthTitles()
  const cells = getMonthCells(state.year, state.month)
  const weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
  $("#calendarCanvas").innerHTML =
    `<div class="calendar-grid">${weekdays.map((day) => `<div class="calendar-weekday">${day}</div>`).join("")}${cells
      .map((cell) => {
        const key = dateKey(cell.date)
        const current = key === todayKey
        const events = state.events
          .map((event, index) => ({ ...event, index }))
          .filter((event) => event.date === key)
        return `<div class="calendar-cell ${cell.muted ? "muted" : ""}" data-calendar-date="${key}"><span class="date-number ${current ? "current" : ""}">${cell.day}</span>${events.map((event) => `<button class="event ${event.tone}" data-edit-event="${event.index}">${event.title}</button>`).join("")}</div>`
      })
      .join("")}</div>`
  renderMiniCalendar("sideMonth")
  $$("[data-calendar-date]", $("#calendarCanvas")).forEach((cell) => {
    cell.addEventListener("dblclick", () =>
      openEventModalForDate(cell.dataset.calendarDate),
    )
  })
  bindEventEditors($("#calendarCanvas"))
  bindToasts()
}

async function fetchKnowledgeMappings(filter = state.kbFilter, query = "") {
  var knowledgeService = getAppRuntimeService("knowledge")
  if (!isLoggedIn()) {
    renderAiWorkbench()
    return
  }
  if (!knowledgeService || !knowledgeService.listEntries) {
    showToast("知识库契约服务未初始化")
    renderAiWorkbench()
    return
  }
  try {
    const contractPayload = await knowledgeService.listEntries({
      q: query || undefined,
    })
    state.knowledge = mapKnowledgeEntriesToLegacyCards(contractPayload)
    repairStoredAiLinkContext()
    await fetchKnowledgeCollections()
  } catch (error) {
    console.warn("Knowledge list contract request failed.", error)
    showToast(error.message || "知识库加载失败，请稍后重试")
  }
  renderAiWorkbench()
}

async function fetchKnowledgeCollections() {
  const service = getAppRuntimeService("knowledge")
  if (!service?.listCollections || !isLoggedIn()) return
  try {
    const payload = await service.listCollections()
    state.ai.knowledgeCollections = listItems(payload, [])
    renderKnowledgeCollectionOptions()
  } catch (error) {
    state.ai.knowledgeCollections = []
    console.warn("Knowledge folders unavailable.", error)
  }
}

function renderKnowledgeCollectionOptions() {
  const select = $("#aiUploadCollection")
  if (!select) return
  const collections = state.ai.knowledgeCollections || []
  select.innerHTML = '<option value="">请选择文件夹</option>' + collections
    .map((collection) => `<option value="${escapeHTML(collection.id)}">${escapeHTML(collection.name || "未命名文件夹")}</option>`)
    .join("")
}

function openAiUploadModal() {
  const form = $("#aiUploadForm")
  const input = $("#aiKbFileInput")
  if (form) form.reset()
  if (input) input.value = ""
  renderKnowledgeCollectionOptions()
  window.App.components.modal.open("aiUploadModal")
}

async function createKnowledgeCollectionFromUpload() {
  const name = window.prompt("文件夹名称")?.trim()
  if (!name) return
  const service = requireAppRuntimeService("knowledge", "createCollection")
  try {
    const created = await service.createCollection({ name })
    state.ai.knowledgeCollections = [...(state.ai.knowledgeCollections || []), created]
    renderKnowledgeCollectionOptions()
    const select = $("#aiUploadCollection")
    if (select) select.value = String(created.id)
    showToast("文件夹已创建")
  } catch (error) {
    showToast(error.message || "文件夹创建失败")
  }
}

async function updateKnowledgeMapping(id, patch) {
  const knowledgeService = requireAppRuntimeService("knowledge", "updateEntry")
  const payload = {}
  if (patch.display_name) payload.title = patch.display_name
  if (patch.title) payload.title = patch.title
  if (patch.enabled !== undefined) {
    payload.enabled = !!patch.enabled
  }
  if (patch.is_default_import_target !== undefined) {
    payload.metadata = {
      is_default_import_target: !!patch.is_default_import_target,
    }
  }
  return knowledgeService.updateEntry(Number(id), payload)
}

async function deleteKnowledgeMapping(id) {
  const knowledgeService = requireAppRuntimeService("knowledge", "archiveEntry")
  return knowledgeService.archiveEntry(Number(id))
}

async function fetchKnowledgeImports() {
  let knowledgeService
  try {
    knowledgeService = requireAppRuntimeService("knowledge", "listOperationJobs")
    const payload = await knowledgeService.listOperationJobs()
    state.knowledgeImports = listItems(payload, [])
  } catch (error) {
    state.knowledgeImports = []
    console.warn("Knowledge uploads unavailable.", error)
  }
  renderKnowledgeImports()
}

function renderKnowledgeImports() {
  const list = $("#knowledgeImportRecordList")
  if (!list) return
  list.innerHTML = state.knowledgeImports.length
    ? state.knowledgeImports
        .slice(0, 8)
        .map(
          (item) =>
            (() => {
              const status = item.status || "unknown"
              const jobId = item.id || item.job_id || item.operation_id || ""
              const retry = status === "failed" && jobId
                ? `<button class="btn" type="button" data-knowledge-job-retry="${escapeHTML(jobId)}">重试</button>`
                : ""
              return `<div class="import-record"><div><strong>${escapeHTML(item.file_name || item.filename || item.name || "未命名文件")}</strong><span>${escapeHTML(item.knowledge_entry_id || item.entry_id || item.resource_id || "未返回资源")}</span></div><span>${escapeHTML(status)}</span>${retry}</div>`
            })(),
        )
        .join("")
    : `<div class="import-record"><div><strong>暂无上传记录</strong><span>文件提交到知识库后会显示在这里。</span></div><span></span></div>`
  $$(`[data-knowledge-job-retry]`).forEach((button) => {
    button.addEventListener("click", async () => {
      const service = getAppRuntimeService("knowledge")
      if (!service?.retryOperationJob) return
      button.disabled = true
      try {
        await service.retryOperationJob(button.dataset.knowledgeJobRetry)
        showToast("导入任务已重新排队")
        await fetchKnowledgeImports()
      } catch (error) {
        showToast(`重试失败：${error?.message || "服务不可用"}`)
        button.disabled = false
      }
    })
  })
}

function switchAiSubMenu(sub) {
  var valid = ["all", "kb", "methods", "skills", "trash", "sessions"]
  if (valid.indexOf(sub) === -1) sub = "all"
  state.ai.subMenu = sub
  state.ai.leftSearch = ""
  saveAiPanelPrefs()
  var searchInput = $("#aiLeftSearchInput")
  if (searchInput) searchInput.value = ""
  syncSubLinkActive("kbSubLink", sub)
  renderAiLeftBrowser()
}

function renderChatSessions(query) {
  const container = $("#chatSessionsList")
  if (!container) return
  var sessions = [...state.chatSessions.sessions].sort((left, right) => {
    const leftTime = Date.parse(left.updatedAt || left.createdAt || "") || 0
    const rightTime = Date.parse(right.updatedAt || right.createdAt || "") || 0
    return rightTime - leftTime
  })
  if (query) {
    var q = query.trim().toLowerCase()
    sessions = sessions.filter((s) => {
      return (s.title || "").toLowerCase().indexOf(q) !== -1
    })
  }
  const activeId = state.chatSessions.activeSessionId
  if (!sessions.length) {
    container.innerHTML =
      `<div class="chat-sessions-empty">` +
      (query ? "未找到匹配的会话" : '暂无会话，<br />点击"新建"开始对话') +
      `</div>`
    return
  }
  container.innerHTML = sessions
    .map((s) => {
      const title = escapeHTML(s.title || "新会话")
      const time = (s.updatedAt || s.createdAt || "")
        .slice(-11)
        .replace(/^0/, "")
      const active = s.id === activeId ? " active" : ""
      return `<button class="session-item${active}" data-session-id="${escapeHTML(s.id)}">
          <span class="session-title">${title}</span>
          <span class="session-time">${escapeHTML(time)}</span>
          <span class="session-delete" data-session-delete="${escapeHTML(s.id)}" title="删除会话">&times;</span>
        </button>`
    })
    .join("")
  bindSessionActions()
}

function bindSessionActions() {
  $$("[data-session-id]").forEach((btn) => {
    btn.onclick = (e) => {
      if (e.target.closest("[data-session-delete]")) return
      switchChatSession(btn.dataset.sessionId)
    }
  })
  $$("[data-session-delete]").forEach((btn) => {
    btn.onclick = (e) => {
      e.stopPropagation()
      void deleteChatSession(btn.dataset.sessionDelete)
    }
  })
}

async function fetchChatSessionsFromBackend() {
  try {
    if (!isLoggedIn()) return
    var chatService = getAppRuntimeService("chat")
    if (!chatService || !chatService.listSessions || !chatService.getMessages) {
      showToast("聊天契约服务未初始化")
      return
    }
    const response = await chatService.listSessions()
    const backendItems = Array.isArray(response)
      ? response
      : response && Array.isArray(response.items)
        ? response.items
        : []
    // The general AI workbench uses the agent gateway. Keep knowledge-only
    // sessions out so an older active session cannot silently disable web tools.
    const agentItems = backendItems.filter(
      (session) => session && session.surface === "agent",
    )
    const contractSessions = mapChatSessionsToLegacySessions({
      items: agentItems,
    })
    // Backend history is authoritative. Rebuild the logged-in list so a
    // browser-local transcript from an older session cannot be reused.
    state.chatSessions.sessions = []
    if (!contractSessions.length) {
      state.chatSessions.activeSessionId = null
      saveChatSessions()
      renderChatSessions()
      return
    }
    for (const session of contractSessions) {
      try {
        session.messages = mapChatMessagesToLegacyMessages(
          await chatService.getMessages(session.id),
        )
      } catch (error) {
        console.warn(
          "Chat message history contract request failed for session.",
          session.id,
          error,
        )
        session.messages = []
      }
      session.requestGeneration = 0
      session.activeAbortController = null
      session.activeChatRunId = null
      state.chatSessions.sessions.push(session)
    }
    if (
      !state.chatSessions.sessions.some(
        (session) => session.id === state.chatSessions.activeSessionId,
      )
    ) {
      state.chatSessions.activeSessionId = contractSessions[0].id
    }
    saveChatSessions()
    renderChatSessions()
  } catch (error) {
    console.warn("Chat sessions contract request failed.", error)
    showToast(error.message || "聊天会话加载失败，请稍后重试")
    renderChatSessions()
  }
}

function createLocalChatSession(title = "") {
  const now = new Date()
  const session = {
    id: "s_" + Date.now(),
    title,
    messages: [],
    surface: "agent",
    createdAt: `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")} ${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`,
    updatedAt: "",
    requestGeneration: 0,
    activeAbortController: null,
    activeChatRunId: null,
    activeStopPromise: null,
  }
  state.chatSessions.sessions.push(session)
  state.chatSessions.activeSessionId = session.id
  state.aiContext[session.id] = []
  saveChatSessions()
  saveAiContext()
  renderAiWorkbench()
  $("#chatInput")?.focus()
  return session
}

async function createChatSessionInternal(options = {}) {
  const title =
    typeof options === "string"
      ? options
      : options.title || "新会话"
  const surface = options.surface === "knowledge" ? "knowledge" : "agent"
  const chatService = getAppRuntimeService("chat")

  if (chatService && chatService.createSession && isLoggedIn()) {
    try {
      const payload = await chatService.createSession({
        surface,
        title,
      })
      const session = mapChatSessionsToLegacySessions({ items: [payload] })[0]
      if (!session || !session.id) {
        throw new Error("新建会话响应缺少会话 ID")
      }
      session.title = title || session.title
      session.messages = Array.isArray(session.messages) ? session.messages : []
      session.requestGeneration = 0
      session.activeAbortController = null
      session.activeChatRunId = null
      session.activeStopPromise = null
      state.chatSessions.sessions = state.chatSessions.sessions.filter(
        (existing) => existing.id !== session.id,
      )
      state.chatSessions.sessions.push(session)
      state.chatSessions.activeSessionId = session.id
      state.aiContext[session.id] = []
      saveChatSessions()
      saveAiContext()
      renderAiWorkbench()
      $("#chatInput")?.focus()
      return session
    } catch (error) {
      console.warn("Chat session creation contract request failed.", error)
      showToast(error.message || "新建会话失败")
      return null
    }
  }

  if (isLoggedIn()) {
    showToast("聊天契约服务未初始化")
    return null
  }

  return createLocalChatSession(title)
}

function setChatSessionCreateBusy(busy) {
  $$("#newChatSession").forEach((button) => {
    button.disabled = busy
    button.setAttribute("aria-busy", busy ? "true" : "false")
    button.classList.toggle("loading", busy)
  })
}

async function createChatSession(options = {}) {
  if (state.chatSessionCreationPromise) return state.chatSessionCreationPromise
  setChatSessionCreateBusy(true)
  state.chatSessionCreationPromise = createChatSessionInternal(options).finally(() => {
    state.chatSessionCreationPromise = null
    setChatSessionCreateBusy(false)
  })
  return state.chatSessionCreationPromise
}

function switchChatSession(id) {
  const previous = getActiveSession()
  if (previous && previous.id !== id) {
    previous.requestGeneration = (previous.requestGeneration || 0) + 1
    if (previous.activeAbortController) previous.activeAbortController.abort()
    previous.activeAbortController = null
    previous.activeChatRunId = null
  }
  state.chatSessions.activeSessionId = id
  state.isStreaming = Boolean(getActiveSession()?.activeAbortController)
  state.activeAbortController = getActiveSession()?.activeAbortController || null
  state.activeChatRunId = getActiveSession()?.activeChatRunId || null
  saveChatSessions()
  renderChatSessions()
  renderChatTranscript()
  renderContextChips()
  updateSessionContextCount()
  updateChatSendButton()
  // Update empty state
  var session = getActiveSession()
  var isEmpty = !session || !session.messages || session.messages.length === 0
  $("#aiChat")?.classList.toggle("empty-mode", isEmpty)
  scrollChatToBottom()
}

async function deleteChatSession(id) {
  const session = state.chatSessions.sessions.find((s) => s.id === id)
  if (
    !session ||
    !window.confirm(
      `删除会话"${session.title || "新会话"}"？可在回收站恢复（30天内）。`,
    )
  )
    return
  const chatService = getAppRuntimeService("chat")
  if (chatService?.deleteSession && isLoggedIn()) {
    try {
      await chatService.deleteSession(id)
    } catch (error) {
      console.warn("Chat session delete contract request failed.", error)
      showToast(error.message || "删除会话失败")
      return
    }
  }
  // Soft-delete: move to trash with 30-day retention
  state.ai.trash.push({
    id: "trash_" + Date.now(),
    kind: "chat-session",
    name: session.title || "会话 " + id.slice(0, 8),
    deletedAt: Date.now(),
    payload: session,
  })
  saveAiTrash()
  state.chatSessions.sessions = state.chatSessions.sessions.filter(
    (s) => s.id !== id,
  )
  if (state.chatSessions.activeSessionId === id) {
    state.chatSessions.activeSessionId =
      state.chatSessions.sessions.length > 0
        ? state.chatSessions.sessions[state.chatSessions.sessions.length - 1].id
        : null
  }
  // Clean up AI context for deleted session
  delete state.aiContext[id]
  saveChatSessions()
  saveAiContext()
  renderAiWorkbench()
  showToast("会话已移至回收站（30天内可恢复）")
}

function getActiveSession() {
  const { activeSessionId, sessions } = state.chatSessions
  return sessions.find((s) => s.id === activeSessionId) || null
}

function renderPlatformDraftEditor(draft, messageId, disabled) {
  const value = (field, fallback = "") => escapeHTML(String(draft[field] ?? fallback))
  const fieldAttrs = (field) =>
    `data-platform-draft-message="${escapeHTML(String(messageId || ""))}" data-platform-draft-field="${field}"${disabled ? " disabled" : ""}`
  const approvalRequired = draft.approval_required !== false
  const assigneeType = String(draft.approval_assignee_type || "creator")
  const selected = (candidate) => assigneeType === candidate ? " selected" : ""
  const approvalFields = approvalRequired
    ? `<div class="chat-platform-draft-approval">
        <label><span>审批人</span><select ${fieldAttrs("approval_assignee_type")}><option value="creator"${selected("creator")}>创建者</option><option value="member"${selected("member")}>指定成员</option><option value="role"${selected("role")}>指定角色</option></select></label>
        ${assigneeType === "member" ? `<label><span>成员 ID</span><input ${fieldAttrs("approval_assignee_id")} min="1" type="number" value="${value("approval_assignee_id")}"></label>` : ""}
        ${assigneeType === "role" ? `<label><span>审批角色</span><input ${fieldAttrs("approval_role_name")} value="${value("approval_role_name")}"></label>` : ""}
        <label><span>提醒分钟</span><input ${fieldAttrs("approval_reminder_after_minutes")} min="1" type="number" value="${value("approval_reminder_after_minutes")}"></label>
        <label><span>升级分钟</span><input ${fieldAttrs("approval_escalation_after_minutes")} min="1" type="number" value="${value("approval_escalation_after_minutes")}"></label>
        <label><span>升级角色</span><input ${fieldAttrs("approval_escalation_role_name")} value="${value("approval_escalation_role_name")}"></label>
      </div>`
    : ""
  return `<div class="chat-platform-draft-fields">
    <label><span>任务标题</span><input ${fieldAttrs("title")} value="${value("title")}"></label>
    <label><span>任务内容</span><textarea ${fieldAttrs("prompt")}>${value("prompt")}</textarea></label>
    <label><span>执行周期</span><input ${fieldAttrs("schedule")} placeholder="例如：0 9 * * 1-5" value="${value("schedule")}"></label>
    <label><span>时区</span><input ${fieldAttrs("timezone")} disabled value="Asia/Shanghai"></label>
    <label><span>输出格式</span><select disabled><option>Markdown</option></select></label>
    <label><span>输入来源</span><input disabled value="${escapeHTML(Array.isArray(draft.input_sources) ? draft.input_sources.join(", ") : "")}"></label>
    <label class="chat-platform-draft-toggle"><input ${fieldAttrs("approval_required")} type="checkbox"${approvalRequired ? " checked" : ""}>需要审批</label>
    ${approvalFields}
  </div>`
}

function updatePlatformActionDraft(element, renderDynamicFields) {
  const message = findPlatformActionMessage(element.dataset.platformDraftMessage)
  const action = message && message.platformAction
  const field = element.dataset.platformDraftField
  if (!action?.draft || !field || action.pending) return
  const numericFields = [
    "approval_assignee_id",
    "approval_reminder_after_minutes",
    "approval_escalation_after_minutes",
  ]
  let nextValue = element.type === "checkbox" ? element.checked : element.value
  if (numericFields.includes(field)) nextValue = nextValue ? Number(nextValue) : null
  if (["schedule", "approval_role_name", "approval_escalation_role_name"].includes(field)) {
    nextValue = nextValue || null
  }
  action.draft[field] = nextValue
  if (renderDynamicFields) renderChatTranscript()
}

function renderPlatformActionHTML(action, messageId) {
  if (!action) return ""
  const message = action.message || action.status || "平台操作已处理"
  const identifiers = [
    action.task_id ? `任务 #${action.task_id}` : "",
    action.run_id ? `运行 #${action.run_id}` : "",
  ].filter(Boolean)
  const metadata = identifiers.length ? `（${identifiers.join("，")}）` : ""
  const draft = action.draft && typeof action.draft === "object" ? action.draft : null
  const canConfirm = draft && action.status === "draft" && !action.pending
  const draftSummary = draft
    ? canConfirm
      ? renderPlatformDraftEditor(draft, messageId, false)
      : `<div class="chat-approval-detail">${[
          draft.title ? `任务：${draft.title}` : "",
          draft.schedule ? `计划：${draft.schedule}` : "",
          draft.timezone ? `时区：${draft.timezone}` : "",
          draft.output_format ? `输出：${draft.output_format}` : "",
        ].filter(Boolean).map((item) => escapeHTML(item)).join("<br>")}</div>`
    : ""
  const controls = canConfirm
    ? `<div class="chat-approval-actions"><button type="button" class="chat-approval-btn once" data-platform-action-message="${escapeHTML(String(messageId || ""))}" data-platform-action-choice="confirm">确认创建</button><button type="button" class="chat-approval-btn deny" data-platform-action-message="${escapeHTML(String(messageId || ""))}" data-platform-action-choice="cancel">取消</button></div>`
    : ""
  return `<div class="chat-tool-status chat-platform-action" data-testid="chat-platform-action" role="status">平台操作：${escapeHTML(message)}${escapeHTML(metadata)}${draftSummary}${controls}</div>`
}

async function waitForPipelineRegeneration(decisionId, regenerationRunId) {
  const pipelineService = getAppRuntimeService("pipeline")
  if (!pipelineService || !pipelineService.getRun || !regenerationRunId) return
  const maxAttempts = 180
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    try {
      const run = await pipelineService.getRun(regenerationRunId)
      const status = String(run?.status || "").toLowerCase()
      if (status === "completed") {
        await fetchCockpitDecisions()
        showToast("已根据驳回理由生成新的待决策结果")
        return
      }
      if (status === "failed" || status === "cancelled") {
        replaceCockpitDecision({
          id: decisionId,
          status: "changes_requested",
          regenerationError:
            "重新生成失败：" + (run?.error_code || run?.errorCode || "请重试"),
          regenerationRunId,
        })
        showToast("重新生成失败，请稍后重试")
        return
      }
    } catch (error) {
      console.warn("Pipeline regeneration status request failed.", error)
    }
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }
  replaceCockpitDecision({
    id: decisionId,
    status: "regenerating",
    rejectionReason: "重新生成仍在处理中，请稍后刷新",
    regenerationRunId,
  })
}

function findPlatformActionMessage(messageId) {
  var session = getActiveSession()
  if (!session || !Array.isArray(session.messages)) return null
  return session.messages.find((item) => String(item.id || "") === String(messageId)) || null
}

async function refreshCockpitAfterPipelineAction(runId) {
  await fetchCockpitDecisions()
  if (!runId) return
  var pipelineService = getAppRuntimeService("pipeline")
  if (!pipelineService || !pipelineService.getRun) return
  for (var attempt = 0; attempt < 180; attempt += 1) {
    try {
      var run = await pipelineService.getRun(runId)
      var status = String(run?.status || "").toLowerCase()
      if (["completed", "failed", "cancelled", "missed"].includes(status)) {
        await fetchCockpitDecisions()
        return
      }
    } catch (error) {
      console.warn("Cockpit pipeline refresh failed.", error)
      return
    }
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }
}

async function resolvePlatformAction(messageId, choice) {
  var message = findPlatformActionMessage(messageId)
  var action = message && message.platformAction
  if (!action || !action.draft || action.status !== "draft" || action.pending) return
  if (choice === "cancel") {
    message.platformAction = { status: "cancelled", message: "已取消创建定时任务。" }
    renderChatTranscript()
    return
  }
  var pipelineService = getAppRuntimeService("pipeline")
  if (!pipelineService || !pipelineService.createTask || !pipelineService.runTask) {
    showToast("定时任务服务不可用")
    return
  }
  action.pending = true
  action.message = "正在创建定时任务…"
  renderChatTranscript()
  var task
  try {
    task = await pipelineService.createTask({ ...action.draft, confirmed: true })
  } catch (error) {
    action.pending = false
    action.message = error?.message || "创建定时任务失败"
    renderChatTranscript()
    return
  }
  // Creation is a visible milestone: sync the cockpit before the optional
  // immediate run starts so the task board never appears empty.
  message.platformAction = {
    status: "created",
    message: "已创建定时任务，正在同步定时任务看板。",
    task_id: task.id,
  }
  renderChatTranscript()
  await refreshCockpitAfterPipelineAction()
  if (!action.run_now) {
    message.platformAction = {
      status: "created",
      message: "已创建定时任务。",
      task_id: task.id,
    }
    renderChatTranscript()
    void refreshCockpitAfterPipelineAction()
    return
  }
  try {
    var run = await pipelineService.runTask(task.id)
    message.platformAction = {
      status: run.status || "queued",
      message: "已创建定时任务，本次立即执行已入队。",
      task_id: task.id,
      run_id: run.id,
    }
    void refreshCockpitAfterPipelineAction(run.id)
  } catch (error) {
    message.platformAction = {
      status: "failed",
      message: error?.message || "任务已创建，但立即执行失败。",
      task_id: task.id,
    }
    void refreshCockpitAfterPipelineAction()
  } finally {
    pipelineService.releaseRunIntent?.(String(task.id))
    renderChatTranscript()
  }
}

function renderChatTranscript() {
  const container = $("#chatTranscript")
  if (!container) return
  const session = getActiveSession()
  if (!session || !session.messages.length) {
    container.innerHTML = `<div class="chat-empty-state">
          <h3>AI 分析台</h3>
          <p>选择左侧知识源或拖入文件开始分析</p>
          <div class="example-cards">
            <button class="example-card" data-example="帮我创建一个任务：整理本周会议纪要">创建任务</button>
            <button class="example-card" data-example="帮我添加一个日程：明天下午3点项目评审">添加日程</button>
            <button class="example-card" data-example="请总结当前知识库中的文档核心观点">总结文档</button>
            <button class="example-card" data-example="根据上下文数据，分析这个月的趋势">数据分析</button>
          </div>
        </div>`
    // Bind example cards
    setTimeout(() => {
      $$(".example-card", container).forEach((card) => {
        card.addEventListener("click", () => {
          var input = $("#chatInput")
          if (input) {
            input.value = card.dataset.example
            input.focus()
            autoResizeChatInput()
            updateChatSendButton()
          }
        })
      })
    }, 0)
    return
  }
  container.innerHTML = session.messages
    .map((m, index) => {
      const avatarChar = m.role === "user" ? "U" : "AI"
      const time = (m.createdAt || "").slice(-5) || ""
      const contentHTML = renderAssistantMessageContent(m.content || "")
      const renderedContentHTML =
        m.role === "assistant"
          ? contentHTML
          : escapeHTML(m.content || "").replace(/\n/g, "<br>")
      const statusHTML =
        m.role === "assistant" && m.status
          ? `<span class="chat-bubble-status ${m.status}">${m.status === "streaming" ? "生成中" : m.status === "completed" ? "已完成" : m.status === "interrupted" ? "已中断" : "失败"}</span>`
          : ""
      const cursorHTML =
        m.role === "assistant" && m.status === "streaming"
          ? `<span class="chat-streaming-cursor"></span>`
          : ""
      // References block (assistant messages)
      const refs =
        m.role === "assistant" && m.references && m.references.length
          ? `<div class="chat-references"><span class="ref-label">引用来源：</span>` +
            m.references
              .map((r) => {
                var refTitle = r.title || r.name || r.id || "来源"
                var ordinal = Number(r.ordinal ?? r.index ?? 0)
                var turnId = m.turnId || r.turn_id || r.turnId || ""
                return (
                  '<a data-ref-id="' +
                  escapeHTML(r.id || "") +
                  '" data-ref-turn-id="' +
                  escapeHTML(turnId) +
                  '" data-ref-ordinal="' +
                  escapeHTML(String(ordinal)) +
                  '" href="#citation-' +
                  escapeHTML(String(r.id || ordinal)) +
                  '">' +
                  escapeHTML(refTitle) +
                  "</a>"
                )
              })
                .join("") +
              "</div>"
            : ""
      const retryHTML =
        m.role === "assistant" &&
        (m.status === "failed" || m.status === "interrupted")
          ? `<button class="btn chat-retry" type="button" data-chat-retry="${escapeHTML(m.id)}">重试</button>`
          : ""
      const platformActionHTML =
        m.role === "assistant" && m.platformAction
          ? renderPlatformActionHTML(m.platformAction, m.id)
          : ""
      const toolStatusHTML =
        m.role === "assistant" && m.toolStatus && !m.platformAction
          ? `<div class="chat-tool-status">工具执行中：${escapeHTML(m.toolStatus)}</div>`
          : ""
      const approvalHTML =
        m.role === "assistant" && m.approval ? renderChatApprovalCard(m.approval) : ""
      const webEvidenceHTML = renderWebEvidenceHTML(m)
      const previousMessage = session.messages[index - 1]
      const freshnessNotice =
        m.role === "assistant" && previousMessage?.role === "user"
          ? getFreshnessNotice({
              userContent: previousMessage.content,
              answer: m,
              webSearchUsed: Boolean(m.webSearchUsed),
              webSearchFailed: Boolean(m.webSearchFailed),
            })
          : ""
      const freshnessHTML = freshnessNotice
        ? `<div class="chat-evidence-notice" data-testid="freshness-evidence-notice" role="status">${escapeHTML(freshnessNotice)}</div>`
        : ""
      const saveExperienceHTML = m.role === "assistant" && m.status === "completed" && m.content
        ? `<button class="btn chat-save-experience" type="button" data-save-experience-method="${escapeHTML(String(m.id || index))}">沉淀到经验方法</button>`
        : ""
      return `<div class="chat-bubble ${m.role}" data-message-id="${escapeHTML(String(m.id || ""))}">
          <div class="chat-bubble-avatar">${avatarChar}</div>
          <div class="chat-bubble-body">
            <div class="chat-bubble-content">${renderedContentHTML}${cursorHTML}${platformActionHTML}${toolStatusHTML}${refs}${webEvidenceHTML}${approvalHTML}${freshnessHTML}</div>
            <div class="chat-bubble-meta"><span>${escapeHTML(time)}</span>${statusHTML}${retryHTML}${saveExperienceHTML}</div>
          </div>
        </div>`
    })
    .join("")
  // Add copy buttons to code blocks
  enhanceAssistantHtml(container)
  scrollChatToBottom()
}

function webSourceDateLabel(value) {
  const text = String(value || "")
  const match = text.match(/(\d{4}-\d{2}-\d{2})/)
  return match ? match[1] : ""
}

/**
 * Platform-validated web evidence block. Only sources delivered by the
 * backend web.search events / history web_sources render here; model-written
 * URLs never enter this path. Links use the real href with safe rel.
 */
function renderWebEvidenceHTML(message) {
  if (!message || message.role !== "assistant") return ""
  const sources = Array.isArray(message.webEvidence) ? message.webEvidence : []
  if (sources.length) {
    return (
      `<div class="chat-references chat-web-sources" data-testid="chat-web-sources"><span class="ref-label">联网来源：</span>` +
      sources
        .map((source, index) => {
          const url = String(source.url || "")
          if (!/^https?:\/\//i.test(url)) return ""
          const title = source.title || url
          const published = webSourceDateLabel(source.published_at)
          const searched = webSourceDateLabel(source.searched_at)
          const meta = [published ? `发布 ${published}` : "", searched ? `检索 ${searched}` : ""]
            .filter(Boolean)
            .join(" · ")
          return (
            `<a href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer nofollow" data-web-source-ordinal="${escapeHTML(String(source.ordinal ?? index))}">` +
            escapeHTML(title) +
            (meta ? `<span class="web-source-meta">${escapeHTML(meta)}</span>` : "") +
            "</a>"
          )
        })
        .join("") +
      `</div>`
    )
  }
  if (message.webSearchState === "failed") {
    return `<div class="chat-evidence-notice" data-testid="web-search-failed-notice">联网搜索已执行，但未能取得可验证来源。</div>`
  }
  if (message.webSearchState === "empty") {
    return `<div class="chat-evidence-notice" data-testid="web-search-empty-notice">联网搜索已完成，但没有可验证来源。</div>`
  }
  return ""
}

function renderChatApprovalCard(approval) {
  var status = approval.status || "pending"
  if (status === "once") {
    return '<div class="chat-approval-card resolved">已批准本次执行</div>'
  }
  if (status === "deny") {
    return '<div class="chat-approval-card denied">已拒绝本次执行</div>'
  }
  var runId = escapeHTML(String(approval.runId || ""))
  return (
    '<div class="chat-approval-card pending">' +
    '<div class="chat-approval-title">' +
    escapeHTML(approval.title || "助手请求确认") +
    "</div>" +
    (approval.detail
      ? '<div class="chat-approval-detail">' + escapeHTML(approval.detail) + "</div>"
      : "") +
    '<div class="chat-approval-actions">' +
    '<button type="button" class="chat-approval-btn once" data-approval-run="' +
    runId +
    '" data-approval-choice="once">批准一次</button>' +
    '<button type="button" class="chat-approval-btn deny" data-approval-run="' +
    runId +
    '" data-approval-choice="deny">拒绝</button>' +
    "</div></div>"
  )
}

function findChatApprovalMessage(runId) {
  var session = getActiveSession()
  if (!session || !Array.isArray(session.messages)) return null
  return (
    session.messages.find(
      (item) =>
        item &&
        item.approval &&
        String(item.approval.runId) === String(runId),
    ) || null
  )
}

async function resolveChatApproval(runId, choice) {
  var sessionId = state.chatSessions.activeSessionId
  var chatService = getAppRuntimeService("chat")
  if (!sessionId || !chatService || !chatService.approveRun) {
    showToast("审批服务不可用")
    return
  }
  var message = findChatApprovalMessage(runId)
  if (message) {
    message.approval.status = choice
    renderChatTranscript()
  }
  try {
    await chatService.approveRun(sessionId, String(runId), { choice })
  } catch (error) {
    console.warn("Chat approval contract request failed.", error)
    var failed = findChatApprovalMessage(runId)
    if (failed) {
      failed.approval.status = "pending"
      renderChatTranscript()
    }
    showToast("审批请求失败，请重试")
  }
}

function updateStreamingAssistantMessage(message) {
  const container = $("#chatTranscript")
  if (!container) return
  const bubble = Array.from(
    container.querySelectorAll(".chat-bubble.assistant[data-message-id]"),
  ).find((item) => item.dataset.messageId === String(message.id || ""))
  const content = bubble?.querySelector(".chat-bubble-content")
  if (!content) {
    renderChatTranscript()
    return
  }
  const references =
    Array.isArray(message.references) && message.references.length
      ? `<div class="chat-references"><span class="ref-label">引用来源：</span>${message.references
          .map((reference) => {
            const title = reference.title || reference.name || reference.id || "来源"
            const ordinal = Number(reference.ordinal ?? reference.index ?? 0)
            const turnId = message.turnId || reference.turn_id || reference.turnId || ""
            return `<a data-ref-id="${escapeHTML(reference.id || "")}" data-ref-turn-id="${escapeHTML(turnId)}" data-ref-ordinal="${escapeHTML(String(ordinal))}" href="#citation-${escapeHTML(String(reference.id || ordinal))}">${escapeHTML(title)}</a>`
          })
          .join("")}</div>`
      : ""
  // Keep partial Markdown as stable plain text. Rendering the whole transcript
  // for every token causes visible flashing and repeatedly rebuilds focus state.
  const platformActionHTML = renderPlatformActionHTML(message.platformAction, message.id)
  const toolStatusHTML = message.toolStatus && !message.platformAction
    ? `<div class="chat-tool-status">工具执行中：${escapeHTML(message.toolStatus)}</div>`
    : ""
  content.innerHTML = `${escapeHTML(message.content || "").replace(/\n/g, "<br>")}<span class="chat-streaming-cursor"></span>${platformActionHTML}${toolStatusHTML}${references}${renderWebEvidenceHTML(message)}`
  scrollChatToBottom()
}

function scrollChatToBottom() {
  const container = $("#chatTranscript")
  if (!container) return
  requestAnimationFrame(() => {
    container.scrollTop = container.scrollHeight
  })
}

function updateChatSendButton() {
  const btn = $("#chatSendBtn")
  const input = $("#chatInput")
  if (!btn || !input) return
  const hasText = input.value.trim().length > 0
  btn.disabled = !state.isStreaming && !hasText
  btn.classList.toggle("stop", state.isStreaming)
  btn.classList.remove("loading")
  btn.setAttribute("aria-label", state.isStreaming ? "暂停生成" : "发送")
  btn.setAttribute("title", state.isStreaming ? "暂停生成" : "发送")
}

async function sendChatMessage(options = {}) {
  if (state.isStreaming) {
    stopChatStream()
    return
  }
  const input = $("#chatInput")
  const question = input.value.trim()
  if (!question) return
  if (!isLoggedIn()) {
    document.getElementById("loginOverlay")?.classList.add("show")
    showToast("会话已过期，请重新登录")
    return
  }

  // Ensure active session exists
  var session = getActiveSession()
  if (
    session &&
    (!isBackendChatSessionId(session.id) || session.surface !== "agent")
  ) {
    state.chatSessions.sessions = state.chatSessions.sessions.filter(
      (candidate) => candidate.id !== session.id,
    )
    state.chatSessions.activeSessionId = null
    session = null
  }
  if (
    !session ||
    !state.chatSessions.activeSessionId ||
    !state.chatSessions.sessions.find(
      (s) => s.id === state.chatSessions.activeSessionId,
    )
  ) {
    session = await createChatSession()
  }
  if (!session) return

  // Auto-title: use first user message
  if (
    !session.title ||
    ["新会话", "新对话", "new session", "new chat"].includes(
      session.title.trim().toLowerCase(),
    )
  ) {
    session.title = question.slice(0, 30) + (question.length > 30 ? "…" : "")
    const chatService = getAppRuntimeService("chat")
    if (
      chatService &&
      chatService.updateSession &&
      isBackendChatSessionId(session.id) &&
      isLoggedIn()
    ) {
      try {
        await chatService.updateSession(session.id, { title: session.title })
      } catch (error) {
        // Keep the local title and continue sending when metadata persistence fails.
        console.warn("Chat session title update failed.", error)
      }
    }
  }

  // Add user message
  const now = new Date()
  const timeStr = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`
  const userMsg = {
    id: options.clientMessageId || "m_" + Date.now(),
    role: "user",
    content: question,
    createdAt: timeStr,
  }
  session.messages.push(userMsg)
  session.updatedAt = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")} ${timeStr}`
  saveChatSessions()

  // Add streaming assistant placeholder
  const assistantMsg = {
    id: "m_" + (Date.now() + 1),
    role: "assistant",
    content: "",
    status: "streaming",
    createdAt: "",
  }
  session.messages.push(assistantMsg)

  const requestGeneration = (session.requestGeneration || 0) + 1
  session.requestGeneration = requestGeneration

  input.value = ""
  autoResizeChatInput()
  state.isStreaming = true
  updateChatSendButton()
  renderChatSessions()
  renderChatTranscript()

  // Read mode from dropdown
  const modeEl = $("#chatModeSelect")
  const mode = modeEl ? modeEl.value : "auto"

  // Build transient attachments from uploaded file chips. Knowledge source scope
  // is managed on knowledge sessions; ordinary agent sessions must omit source_ids.
  const chips = getSessionContext(session.id)
  const messageAttachments = chips
    .filter(
      (c) =>
        c.status === "ok" &&
        c.kind === "file" &&
        (c.attachmentContent || c.content),
    )
    .map((c) => ({
      title: c.attachmentTitle || c.name || "附件",
      content: c.attachmentContent || c.content,
    }))
  const messageLinks = chips
    .filter((c) => c.status === "ok" && c.kind === "link" && c.ref)
    .map((c) => normalizeChatLink(c.ref))
    .filter(Boolean)

  // Create AbortController for this request
  session.activeAbortController = new AbortController()
  session.activeChatRunId = null
  session.activeStopPromise = null
  state.activeAbortController = session.activeAbortController
  state.activeChatRunId = null

  // Clear empty state
  $("#aiChat")?.classList.remove("empty-mode")

  try {
    var chatStream = getAppRuntimeService("chatStream")
    if (!chatStream || !chatStream.sendMessageStream || !isLoggedIn()) {
      throw new Error("聊天契约流服务未初始化")
    }
    const response = await chatStream.sendMessageStream(
      session.id,
      {
        attachments: messageAttachments,
        content: question,
        client_message_id: userMsg.id,
        links: messageLinks,
        metadata: { mode, command_mode: true },
      },
      { signal: session.activeAbortController.signal },
    )
    await readChatSseResponse(response, assistantMsg, session, requestGeneration)
    assistantMsg.createdAt = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`
  } catch (error) {
    if (error.name === "AbortError") {
      if (!assistantMsg.content) assistantMsg.content = "（已停止生成）"
      assistantMsg.status = "interrupted"
    } else {
      console.warn("Knowledge chat failed.", error)
      const status = error && error.status
      if (status === 401 && !_singleUserMode) {
        clearAuth()
        showLoginOverlay()
        assistantMsg.content = "登录已过期，请重新登录。"
      } else if (status === 403) {
        assistantMsg.content = "当前账号没有执行此操作的权限。"
      } else if (status === 409) {
        assistantMsg.content = "当前会话已有进行中的请求，请停止或稍后重试。"
      } else if (status === 429) {
        assistantMsg.content = "运行额度被未完成会话占用，请等待会话结束后重试。"
      } else if (status >= 500) {
        assistantMsg.content = "后端服务异常（HTTP " + status + "），请稍后重试。"
      } else {
        assistantMsg.content = "请求失败，请检查网络连接或后端服务状态。"
      }
      assistantMsg.status = "failed"
    }
    assistantMsg.createdAt = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`
  }

  if (session.activeStopPromise) await session.activeStopPromise
  if (session.requestGeneration === requestGeneration) {
    session.activeAbortController = null
    session.activeChatRunId = null
    session.activeStopPromise = null
    state.isStreaming = false
    state.activeAbortController = null
    state.activeChatRunId = null
  }
  state.aiContext[session.id] = []
  saveChatSessions()
  saveAiContext()
  updateChatSendButton()
  renderChatSessions()
  renderChatTranscript()
  renderContextChips()
}

function stopChatStream() {
  const sessionId = state.chatSessions.activeSessionId
  const runId = state.activeChatRunId
  const session = getActiveSession()
  if (session?.activeStopPromise) return
  if (state.activeAbortController) {
    state.activeAbortController.abort()
  }
  var chatService = getAppRuntimeService("chat")
  if (chatService && chatService.stopRun && sessionId) {
    session.activeStopPromise = chatService
      .stopRun(sessionId, runId || "active")
      .catch((error) => {
        console.warn("Chat stop contract request failed.", error)
      })
  }
}

function autoResizeChatInput() {
  const input = $("#chatInput")
  if (!input) return
  input.style.height = "auto"
  input.style.height = Math.min(input.scrollHeight, 120) + "px"
}

function kbSearchTerm() {
  // #kbSearchInput only exists in the legacy knowledge section; the AI
  // workbench manage grid reuses these actions without that input.
  const input = $("#kbSearchInput")
  return input ? input.value : ""
}

function bindKnowledgeActions() {
  $$("[data-knowledge-import]").forEach((button) =>
    button.addEventListener("click", () => {
      const item = state.knowledge.find(
        (mapping) => mapping.id === button.dataset.knowledgeImport,
      )
      if (item) openKnowledgeImport()
    }),
  )
  $$("[data-knowledge-toggle]").forEach((button) =>
    button.addEventListener("click", async () => {
      const item = state.knowledge.find(
        (mapping) => mapping.id === button.dataset.knowledgeToggle,
      )
      if (!item) return
      await updateKnowledgeMapping(item.id, { enabled: !item.enabled })
      await fetchKnowledgeMappings(state.kbFilter, kbSearchTerm())
      showToast(item.enabled ? "知识库已停用" : "知识库已启用")
    }),
  )
  $$("[data-knowledge-default]").forEach((button) =>
    button.addEventListener("click", async () => {
      await updateKnowledgeMapping(button.dataset.knowledgeDefault, {
        is_default_import_target: true,
      })
      await fetchKnowledgeMappings(state.kbFilter, kbSearchTerm())
      showToast("默认导入知识库已更新")
    }),
  )
  $$("[data-knowledge-rename]").forEach((button) =>
    button.addEventListener("click", async () => {
      const item = state.knowledge.find(
        (mapping) => mapping.id === button.dataset.knowledgeRename,
      )
      if (!item) return
      const nextName = window.prompt(
        "显示名称",
        item.display_name || item.resource_id,
      )
      if (!nextName || !nextName.trim()) return
      await updateKnowledgeMapping(item.id, { display_name: nextName.trim() })
      await fetchKnowledgeMappings(state.kbFilter, kbSearchTerm())
      showToast("知识库名称已更新")
    }),
  )
  $$("[data-knowledge-delete]").forEach((button) =>
    button.addEventListener("click", async () => {
      const item = state.knowledge.find(
        (mapping) => mapping.id === button.dataset.knowledgeDelete,
      )
      if (
        !item ||
        !window.confirm(
          `删除本地映射：${item.display_name || item.resource_id}？`,
        )
      )
        return
      await deleteKnowledgeMapping(item.id)
      await fetchKnowledgeMappings(state.kbFilter, kbSearchTerm())
      showToast("本地映射已删除")
    }),
  )
  bindKbFileActions()
}

function bindKbFileActions() {
  $$("[data-kb-files]").forEach((button) =>
    button.addEventListener("click", () => {
      const datasetId = button.dataset.kbFilesDataset
      const kbName = button.dataset.kbFilesName
      if (!datasetId) {
        showToast("该知识库没有可用的条目 ID")
        return
      }
      openKbFiles(datasetId, kbName)
    }),
  )
}

async function openKbFiles(datasetId, kbName) {
  const modal = $("#kbFilesModal")
  const title = $("#kbFilesModalTitle")
  const kbNameEl = $("#kbFilesKbName")
  const list = $("#kbFilesList")
  const empty = $("#kbFilesEmpty")
  if (!modal || !list) return
  title.textContent = `文件管理 · ${kbName}`
  kbNameEl.textContent = kbName
  list.innerHTML = `<div class="kb-files-loading">加载中...</div>`
  empty.hidden = true
  modal.classList.add("show")
  try {
    const knowledgeService = requireAppRuntimeService(
      "knowledge",
      "previewContent",
    )
    const payload = await knowledgeService.previewContent(Number(datasetId))
    const items = listItems(payload, [])
    if (items.length === 0) {
      list.innerHTML =
        `<div class="kb-files-empty">当前知识库契约仅提供内容预览，文件级管理需后端补充 operation。</div>`
      empty.hidden = false
    } else {
      renderKbFilesList(items, datasetId)
    }
  } catch (error) {
    list.innerHTML = `<div class="kb-files-empty">加载失败：${error.message}</div>`
    console.warn("Failed to list dataset files", error)
  }
}

function renderKbFilesList(files, datasetId) {
  const list = $("#kbFilesList")
  if (!list) return
  list.innerHTML = files
    .map((f) => {
      const statusClass = f.status === "ready" ? "ready" : ""
      const statusLabel =
        {
          ready: "就绪",
          queued: "排队中",
          training: "训练中",
          unknown: "未知",
        }[f.status] || f.status
      const fileName = f.file_name || f.collection_id || "未知文件"
      return `<div class="kb-file-row">
          <span class="kb-file-name" title="${escapeHTML(fileName)}">${escapeHTML(fileName)}</span>
          <span class="kb-file-status ${statusClass}">${statusLabel}</span>
          <button class="btn danger kb-file-delete" data-delete-file="${escapeHTML(f.knowledge_entry_id || f.entry_id || f.id || f.collection_id)}" data-delete-name="${escapeHTML(fileName)}">删除</button>
        </div>`
    })
    .join("")
  // Bind delete buttons
  $$("#kbFilesList .kb-file-delete").forEach((btn) =>
    btn.addEventListener("click", async () => {
      const fileId = btn.dataset.deleteFile
      const fileName = btn.dataset.deleteName
      if (!window.confirm(`确认删除文件「${fileName}」？此操作不可恢复。`))
        return
      try {
        var knowledgeService = requireAppRuntimeService("knowledge", "archiveEntry")
        var entryId = Number(fileId)
        if (!Number.isInteger(entryId) || entryId <= 0) {
          throw new Error("知识库条目 ID 无效")
        }
        await knowledgeService.archiveEntry(entryId)
        await openKbFiles(datasetId, kbName)
        await fetchKnowledgeMappings(state.kbFilter, kbSearchTerm())
        showToast("知识库文件已归档")
      } catch (error) {
        showToast("文件删除失败")
        console.warn("Failed to delete file", error)
      }
    }),
  )
}

function closeKbFilesModal() {
  const modal = $("#kbFilesModal")
  if (modal) modal.classList.remove("show")
}

async function syncKnowledgeMappings() {
  const status = $("#knowledgeSyncStatus")
  status.textContent = "正在读取知识库运营状态..."
  try {
    const knowledgeService = requireAppRuntimeService(
      "knowledge",
      "getOperationsOverview",
    )
    const payload = await knowledgeService.getOperationsOverview()
    await fetchKnowledgeMappings(state.kbFilter, kbSearchTerm())
    status.textContent = `运营状态已更新：队列 ${payload.queued || 0}，失败 ${payload.failed || 0}，处理中 ${payload.running || 0}。`
    showToast("知识库运营状态已更新")
  } catch (error) {
    status.textContent =
      "运营状态读取失败；请检查知识库 operation 服务。"
    showToast("知识库运营状态读取失败")
    console.warn("Knowledge operations request failed.", error)
  }
}

async function importKnowledgeFile(event) {
  event.preventDefault()
  const input = $("#knowledgeImportFile")
  const status = $("#knowledgeImportStatus")
  const submit = $("#knowledgeImportBtn") || event.submitter
  const file = input.files && input.files[0]
  if (!file) {
    showToast("请先选择文件")
    return
  }
  var knowledgeService = getAppRuntimeService("knowledge")
  const formData = new FormData()
  formData.append("file", file)
  formData.append("title", file.name)
  status.textContent = knowledgeService?.uploadEntry
    ? "正在上传到知识库..."
    : "正在上传到知识库..."
  if (submit) submit.disabled = true
  try {
    var payload
    if (knowledgeService && knowledgeService.uploadEntry && isLoggedIn()) {
      payload = await knowledgeService.uploadEntry(formData, (loaded, total) => {
        if (total) status.textContent = `正在上传到知识库... ${Math.round((loaded / total) * 100)}%`
      })
      const operationId = payload.id || payload.job_id || payload.operation_id
      status.textContent = `${payload.title || payload.file_name || file.name} 已提交到知识库${operationId ? `（任务 ${operationId}）` : ""}`
    } else {
      throw new Error("知识库上传契约服务未初始化")
    }
    input.value = ""
    await fetchKnowledgeImports()
    await fetchKnowledgeMappings(state.kbFilter, kbSearchTerm())
    showToast("文件已提交到知识库")
  } catch (error) {
    const reason = error?.message || error?.code || "知识库服务不可用"
    status.textContent = `导入失败：${reason}`
    showToast(`文件导入失败：${reason}`)
    console.warn("Knowledge import failed.", error)
  } finally {
    if (submit) submit.disabled = false
  }
}

async function retryChatMessage(messageId) {
  const session = getActiveSession()
  if (!session || state.isStreaming) return
  const index = session.messages.findIndex((message) => message.id === messageId)
  if (index < 0 || !["failed", "interrupted"].includes(session.messages[index].status)) return
  const previous = session.messages[index - 1]
  if (!previous || previous.role !== "user") return
  session.messages.splice(index - 1, 2)
  saveChatSessions()
  state.aiContext[session.id] = []
  saveAiContext()
  renderChatTranscript()
  const input = $("#chatInput")
  if (input) input.value = previous.content || ""
  await sendChatMessage({ clientMessageId: previous.id })
}

async function resolveChatCitation(anchor) {
  const turnId = anchor.dataset.refTurnId
  const ordinal = Number(anchor.dataset.refOrdinal)
  const knowledgeService = getAppRuntimeService("knowledge")
  if (!turnId || !Number.isInteger(ordinal) || !knowledgeService?.resolveCitation) {
    showToast("当前引用缺少可解析的来源信息")
    return
  }
  try {
    const result = await knowledgeService.resolveCitation(turnId, ordinal)
    const title = result.title || result.source_locator || "引用来源"
    showToast(`已解析引用：${title}`)
  } catch (error) {
    const status = error?.status
    showToast(status === 403 || status === 404 ? "引用来源当前无权访问或已失效" : "引用解析失败，请稍后重试")
  }
}

function openKnowledgeImport() {
  openAiUploadModal()
}

var _searchTimer = null
async function fetchGlobalSearch(query) {
  if (!query || query.length < 1) {
    $("#searchResults").innerHTML =
      `<div class="search-result"><strong>输入关键词开始搜索</strong><p>支持搜索子系统、公告、文档、报修、资产、OA 流程等</p></div>`
    return
  }
  var knowledgeService = getAppRuntimeService("knowledge")
  var items
  if (knowledgeService && knowledgeService.search && isLoggedIn()) {
    var searchPayload = await knowledgeService.search({
      limit: 20,
      query: query,
    })
    items = mapKnowledgeSearchToLegacyResults(searchPayload)
  } else {
    throw new Error("知识搜索契约服务未初始化")
  }

  // Group by type for category rendering
  var TYPE_LABELS = {
    subsystem: "子系统",
    notice: "公告",
    document: "文档",
    resource: "资源",
    service: "服务",
    repair: "报修",
    asset: "资产",
    oa: "OA流程",
    news: "资讯",
  }
  var groups = {}
  for (var i = 0; i < items.length; i++) {
    var t = items[i].type || "other"
    if (!groups[t]) groups[t] = []
    groups[t].push(items[i])
  }

  var html = ""
  var groupKeys = Object.keys(groups)
  for (var g = 0; g < groupKeys.length; g++) {
    var typeKey = groupKeys[g]
    var groupItems = groups[typeKey]
    html +=
      '<div class="search-group-label">' +
      (TYPE_LABELS[typeKey] || typeKey) +
      " <small>(" +
      groupItems.length +
      ")</small></div>"
    for (var j = 0; j < groupItems.length; j++) {
      var item = groupItems[j]
      var statusHtml = ""
      if (item.status) {
        try {
          statusHtml = window.App.components.statusBadge.render(
            item.status,
            "small",
          )
        } catch (_) {
          statusHtml =
            '<span class="badge badge-small">' +
            escapeHTML(item.status) +
            "</span>"
        }
      }
      html +=
        '<div class="search-result-item" data-search-href="' +
        escapeHTML(item.href || "#") +
        '">' +
        '<div class="search-result-text">' +
        '<div class="search-result-title">' +
        escapeHTML(item.title || "") +
        "</div>" +
        (item.subtitle
          ? '<div class="search-result-subtitle">' +
            escapeHTML(item.subtitle) +
            "</div>"
          : "") +
        "</div>" +
        statusHtml +
        "</div>"
    }
  }

  if (!html) {
    html =
      '<div class="search-result"><strong>没有找到匹配结果</strong><p>换个关键词再试试。</p></div>'
  }

  $("#searchResults").innerHTML = html

  // Click-to-navigate on result items
  $$("#searchResults .search-result-item").forEach((el) => {
    el.addEventListener("click", () => {
      var href = el.getAttribute("data-search-href")
      if (href && href !== "#") {
        $("#searchModal").classList.remove("show")
        window.location.hash = href
      }
    })
  })
}

function bindToasts() {
  $$("[data-toast]").forEach((element) => {
    element.onclick = () => showToast(element.dataset.toast)
  })
}

function bindModalTriggers() {
  $$("[data-open-modal]").forEach((element) => {
    element.onclick = () => openEventModal()
  })
}

function normalizeEmbedUrl(value, fallback) {
  const trimmed = value.trim()
  if (!trimmed) return fallback
  return /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`
}

function saveEmbedUrls() {
  var data = JSON.stringify(state.embedUrls)
  _saveScoped(embedStorageKey, data)
  try {
    window.localStorage.setItem(embedStorageKey, data)
  } catch (e) {}
}

async function saveEmbedUrlsRemote() {
  return apiJson("/__frontend_missing_contract__/integrations/embed-urls", {
    method: "PUT",
    body: JSON.stringify(state.embedUrls),
  })
}

function applyEmbedUrl(key) {
  const input = $(`[data-embed-input="${key}"]`)
  const frame = $(`#${key}Frame`)
  if (!input || !frame) return
  const nextUrl = normalizeEmbedUrl(input.value, defaultEmbedUrls[key])
  state.embedUrls[key] = nextUrl
  input.value = nextUrl
  frame.src = nextUrl
  saveEmbedUrls()
  saveEmbedUrlsRemote().catch((error) =>
    console.warn("Embed URL update stayed local.", error),
  )
  showToast(`${key === "feishu" ? "飞书" : "钉钉"}页面已载入`)
}

function renderEmbeds() {
  Object.keys(defaultEmbedUrls).forEach((key) => {
    const input = $(`[data-embed-input="${key}"]`)
    const frame = $(`#${key}Frame`)
    if (!input || !frame) return
    input.value = state.embedUrls[key]
    frame.src = state.embedUrls[key]
  })
}

function bindEmbeds() {
  renderEmbeds()
  $$("[data-embed-apply]").forEach((button) => {
    button.addEventListener("click", () =>
      applyEmbedUrl(button.dataset.embedApply),
    )
  })
  $$("[data-embed-input]").forEach((input) => {
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") applyEmbedUrl(input.dataset.embedInput)
    })
  })
  $$("[data-embed-refresh]").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.embedRefresh
      const frame = $(`#${key}Frame`)
      if (!frame) return
      frame.src = state.embedUrls[key]
      showToast(`${key === "feishu" ? "飞书" : "钉钉"}页面已刷新`)
    })
  })
  $$("[data-embed-open]").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.embedOpen
      window.open(state.embedUrls[key], "_blank", "noopener,noreferrer")
    })
  })
}

function saveCustomWebsites() {
  _saveScoped(customWebsitesStorageKey, JSON.stringify(state.customWebsites))
}

function createCustomWebsiteId() {
  var randomPart =
    window.crypto && window.crypto.randomUUID
      ? window.crypto.randomUUID().replace(/-/g, "")
      : Math.random().toString(36).slice(2)
  return "custom-site-" + Date.now().toString(36) + randomPart.slice(0, 12)
}

function refreshCustomWebsiteTabs() {
  state.tabs = state.tabs
    .filter(
      (tab) =>
        !hasCustomWebsiteViewPrefix(tab.view) ||
        tab.view === customWebsiteNewView ||
        isCustomWebsiteView(tab.view),
    )
    .map((tab) => {
      var customWebsite = getCustomWebsiteForView(tab.view)
      return customWebsite ? { ...tab, label: customWebsite.name } : tab
    })
}

function createCustomWebsiteMenuButton(site) {
  var button = document.createElement("button")
  button.type = "button"
  button.className = "side-link custom-website-link"
  button.dataset.customWebsiteId = site.id
  button.title = site.name
  button.classList.toggle(
    "active",
    state.activeView === getCustomWebsiteViewId(site.id),
  )
  var label = document.createElement("span")
  label.textContent = site.name
  button.append(label)
  button.addEventListener("click", () => openTab(getCustomWebsiteViewId(site.id)))
  return button
}

function renderCustomWebsiteNavigation() {
  var container = $("#customWebsiteMenu")
  if (container) {
    container.replaceChildren(
      ...state.customWebsites.map((site) => createCustomWebsiteMenuButton(site)),
    )
  }

  var addButton = $("#customWebsiteAdd")
  if (addButton) {
    addButton.title = "添加自定义网站"
    addButton.classList.toggle("active", state.activeView === customWebsiteNewView)
    addButton.onclick = () => {
      openTab(customWebsiteNewView)
    }
  }
}

function createCustomWebsiteField(labelText, inputId, value, type, fieldName) {
  var field = document.createElement("div")
  field.className = "field"
  var label = document.createElement("label")
  label.htmlFor = inputId
  label.textContent = labelText
  var input = document.createElement("input")
  input.id = inputId
  input.type = type
  input.value = value
  input.required = true
  input.dataset.customWebsiteField = fieldName
  field.append(label, input)
  return field
}

function customWebsiteErrorMessage(error) {
  var messages = {
    name_required: "请输入自定义网站名称",
    name_taken: "名称已存在，请使用其他名称",
    url_invalid: "请输入有效的 HTTP 或 HTTPS 网站地址",
  }
  return messages[error] || "无法保存自定义网站"
}

function setCustomWebsiteError(section, error) {
  var element = section.querySelector("[data-custom-website-error]")
  if (!element) return
  element.textContent = error ? customWebsiteErrorMessage(error) : ""
  element.hidden = !error
}

function createCustomWebsiteView(site) {
  var isDraft = !site
  var viewId = isDraft ? customWebsiteNewView : getCustomWebsiteViewId(site.id)
  var section = document.createElement("section")
  section.className = "view custom-website-view"
  section.id = viewId

  var heading = document.createElement("div")
  heading.className = "page-heading"
  var headingText = document.createElement("div")
  var title = document.createElement("h1")
  title.textContent = isDraft ? "添加自定义网站" : site.name
  var description = document.createElement("p")
  description.textContent = "在工作平台内预览已保存的网站地址"
  headingText.append(title, description)
  heading.append(headingText)

  if (!isDraft) {
    var headingActions = document.createElement("div")
    headingActions.className = "heading-actions"
    var refresh = document.createElement("button")
    refresh.type = "button"
    refresh.className = "btn"
    refresh.textContent = "刷新"
    refresh.addEventListener("click", () => {
      var frame = section.querySelector("iframe")
      if (frame) frame.src = site.url
      showToast(site.name + "页面已刷新")
    })
    var openExternal = document.createElement("button")
    openExternal.type = "button"
    openExternal.className = "btn primary"
    openExternal.textContent = "新窗口打开"
    openExternal.addEventListener("click", () => {
      window.open(site.url, "_blank", "noopener,noreferrer")
    })
    headingActions.append(refresh, openExternal)
    heading.append(headingActions)
  }

  var shell = document.createElement("div")
  shell.className = "embed-shell"
  var card = document.createElement("article")
  card.className = "card embed-card custom-website-card"
  var form = document.createElement("form")
  form.className = "custom-website-form"
  form.noValidate = true
  form.append(
    createCustomWebsiteField(
      "自定义网站名称",
      viewId + "-name",
      isDraft ? "" : site.name,
      "text",
      "name",
    ),
    createCustomWebsiteField(
      "自定义网站地址",
      viewId + "-url",
      isDraft ? "" : site.url,
      "url",
      "url",
    ),
  )
  var error = document.createElement("p")
  error.className = "custom-website-error"
  error.dataset.customWebsiteError = ""
  error.setAttribute("role", "alert")
  error.hidden = true
  var actions = document.createElement("div")
  actions.className = "custom-website-actions"
  var save = document.createElement("button")
  save.type = "submit"
  save.className = "btn primary"
  save.textContent = "保存并载入"
  actions.append(save)
  if (!isDraft) {
    var remove = document.createElement("button")
    remove.type = "button"
    remove.className = "btn danger"
    remove.textContent = "删除此网站"
    remove.addEventListener("click", () => deleteCustomWebsite(site.id))
    actions.append(remove)
  }
  form.append(error, actions)
  form.addEventListener("submit", (event) => {
    event.preventDefault()
    saveCustomWebsiteFromForm(section, site ? site.id : null)
  })
  card.append(form)

  var frameWrap = document.createElement("div")
  frameWrap.className = "embed-frame-wrap"
  if (isDraft) {
    var empty = document.createElement("p")
    empty.className = "custom-website-preview-empty"
    empty.textContent = "保存后将在这里预览网站"
    frameWrap.append(empty)
  } else {
    var frame = document.createElement("iframe")
    frame.className = "embed-frame"
    frame.title = site.name + "嵌入页面"
    frame.src = site.url
    frame.loading = "lazy"
    frame.referrerPolicy = "strict-origin-when-cross-origin"
    frameWrap.append(frame)
  }
  card.append(frameWrap)
  shell.append(card)
  section.append(heading, shell)
  return section
}

function renderCustomWebsiteViews() {
  var mount = $("#customWebsiteViews")
  if (!mount) return
  var views = state.customWebsites.map((site) => createCustomWebsiteView(site))
  views.push(createCustomWebsiteView(null))
  mount.replaceChildren(...views)
}

function saveCustomWebsiteFromForm(section, existingId) {
  var name = section.querySelector('[data-custom-website-field="name"]')
  var url = section.querySelector('[data-custom-website-field="url"]')
  if (!name || !url) return
  var id = existingId || createCustomWebsiteId()
  var result = createCustomWebsite(state.customWebsites, {
    id: id,
    name: name.value,
    url: url.value,
  })
  if (!result.ok) {
    setCustomWebsiteError(section, result.error)
    return
  }

  var existingIndex = state.customWebsites.findIndex((site) => site.id === id)
  if (existingIndex === -1) state.customWebsites.push(result.value)
  else state.customWebsites[existingIndex] = result.value
  state.tabs = state.tabs.filter((tab) => tab.view !== customWebsiteNewView)
  refreshCustomWebsiteTabs()
  saveCustomWebsites()
  renderCustomWebsiteNavigation()
  renderCustomWebsiteViews()
  openTab(getCustomWebsiteViewId(id))
  showToast(result.value.name + "已载入")
}

function deleteCustomWebsite(id) {
  var site = state.customWebsites.find((item) => item.id === id)
  if (!site) return
  if (!window.confirm("仅移除当前用户的本地入口，确定删除“" + site.name + "”吗？")) return

  var view = getCustomWebsiteViewId(id)
  state.customWebsites = state.customWebsites.filter((item) => item.id !== id)
  state.tabs = state.tabs.filter((tab) => tab.view !== view)
  saveCustomWebsites()
  renderCustomWebsiteNavigation()
  renderCustomWebsiteViews()
  if (state.activeView === view) openTab("feishu")
  else renderTabs()
}

function changeMonth(delta) {
  state.month += delta
  if (state.month < 0) {
    state.month = 11
    state.year -= 1
  }
  if (state.month > 11) {
    state.month = 0
    state.year += 1
  }
  state.selectedScheduleDate = dateKey(new Date(state.year, state.month, 1))
  updateMonthTitles()
  renderWorkbenchSchedule()
  renderMiniCalendar("portalMonth")
  renderCalendar()
}

function closePopovers() {
  const n = $("#notificationDropdown")
  if (n) n.classList.remove("show")
  const u = $("#userPopover")
  if (u) u.classList.remove("show")
}

function closeEventModal() {
  state.editingEventIndex = null
  const deleteButton = $("#eventDeleteButton")
  if (deleteButton) deleteButton.hidden = true
  $("#eventModal").classList.remove("show")
  $("#eventForm").reset()
}

function deleteEditingEvent() {
  if (state.editingEventIndex === null) return
  const eventItem = state.events[state.editingEventIndex]
  state.events.splice(state.editingEventIndex, 1)
  saveEvents()
  if (eventItem?.id)
    deleteEventRemote(eventItem.id).catch((error) =>
      console.warn("Calendar delete stayed local.", error),
    )
  closeEventModal()
  renderCalendar()
  renderWorkbenchSchedule()
  renderMiniCalendar("portalMonth")
  renderWorkbenchOverview()
  showToast("日程已删除")
}

function togglePortalEditMode() {
  state.portalEditMode = !state.portalEditMode
  const portal = $("#portal")
  const gearBtn = $("#portalSettingsBtn")
  if (!gearBtn || !portal) return
  gearBtn.classList.toggle("active", state.portalEditMode)
  portal.classList.toggle("portal-edit", state.portalEditMode)
  portal.querySelectorAll(".card").forEach((card) => {
    card.draggable = state.portalEditMode
  })
  if (state.portalEditMode) {
    const doneBtn = document.createElement("button")
    doneBtn.className = "btn portal-done-btn primary"
    doneBtn.textContent = "完成"
    doneBtn.id = "portalDoneBtn"
    doneBtn.addEventListener("click", togglePortalEditMode)
    gearBtn.parentNode.insertBefore(doneBtn, gearBtn.nextSibling)
    showToast("已进入门户编辑模式，拖动卡片可调整顺序")
  } else {
    const doneBtn = $("#portalDoneBtn")
    if (doneBtn) doneBtn.remove()
    showToast("门户布局已保存")
  }
}

function handleDragStart(event) {
  if (!state.portalEditMode) return
  const card = event.target.closest(".card")
  if (!card) return
  card.classList.add("dragging")
  event.dataTransfer.effectAllowed = "move"
  event.dataTransfer.setData(
    "text/plain",
    [...card.parentNode.children].indexOf(card),
  )
  event.dataTransfer.setData("grid-id", card.parentNode.id)
}

function handleDragEnd(event) {
  const card = event.target.closest(".card")
  if (card) card.classList.remove("dragging")
  document
    .querySelectorAll(".card.drag-over")
    .forEach((el) => el.classList.remove("drag-over"))
}

function handleDragOver(event) {
  if (!state.portalEditMode) return
  event.preventDefault()
  event.dataTransfer.dropEffect = "move"
  const target = event.target.closest(".card")
  if (target) target.classList.add("drag-over")
}

function handleDragLeave(event) {
  const target = event.target.closest(".card")
  if (target) target.classList.remove("drag-over")
}

function handleDrop(event) {
  event.preventDefault()
  if (!state.portalEditMode) return
  const sourceIndex = Number(event.dataTransfer.getData("text/plain"))
  const sourceGridId = event.dataTransfer.getData("grid-id")
  const targetCard = event.target.closest(".card")
  if (!targetCard) return
  targetCard.classList.remove("drag-over")
  const targetGrid = targetCard.parentNode
  if (!targetGrid || sourceGridId !== targetGrid.id) {
    showToast("卡片只能在同一区域中拖动")
    return
  }
  const children = [...targetGrid.children]
  const targetIndex = children.indexOf(targetCard)
  if (sourceIndex === targetIndex) return
  const [movedCard] = children.splice(sourceIndex, 1)
  children.splice(targetIndex, 0, movedCard)
  children.forEach((child) => targetGrid.appendChild(child))
  showToast("卡片已重新排序")
}

function bindPortalEditTriggers() {
  const gearBtn = $("#portalSettingsBtn")
  if (gearBtn) gearBtn.onclick = togglePortalEditMode
  // Portal card button bindings
  const profileEditBtn = document.querySelector(
    "#portal-personal .card:first-child .card-link",
  )
  if (profileEditBtn) profileEditBtn.onclick = openProfileModal
  const newsSubBtn = document.querySelector(
    "#portal-personal .card:nth-child(2) .card-link",
  )
  if (newsSubBtn) newsSubBtn.onclick = openNewsSubModal
  // Drag handles and drag events
  document.querySelectorAll("#portal .card").forEach((card) => {
    const header = card.querySelector(".card-header")
    if (header && !header.querySelector(".drag-handle")) {
      const handle = document.createElement("span")
      handle.className = "drag-handle"
      handle.innerHTML = `<svg class="icon"><use href="#i-grip"/></svg>`
      header.insertBefore(handle, header.firstChild)
    }
    card.removeEventListener("dragstart", handleDragStart)
    card.removeEventListener("dragend", handleDragEnd)
    card.removeEventListener("dragover", handleDragOver)
    card.removeEventListener("dragleave", handleDragLeave)
    card.removeEventListener("drop", handleDrop)
    card.addEventListener("dragstart", handleDragStart)
    card.addEventListener("dragend", handleDragEnd)
    card.addEventListener("dragover", handleDragOver)
    card.addEventListener("dragleave", handleDragLeave)
    card.addEventListener("drop", handleDrop)
  })
}

function openProfileModal() {
  // Prefer auth data for identity fields; portal profile for local-only fields
  const authName =
    (_authUser && (_authUser.display_name || _authUser.username)) || ""
  const authEmail = (_authUser && _authUser.email) || ""
  const p = state.portalProfile
  $("#profileName").value = authName || p.name || ""
  $("#profileDept").value = p.department || ""
  $("#profileEmail").value = authEmail || p.email || ""
  $("#profilePhone").value = p.phone || ""
  // Name and email come from auth — make read-only to prevent invisible edits
  var nameInput = $("#profileName")
  var emailInput = $("#profileEmail")
  if (authName) {
    nameInput.setAttribute("readonly", "")
    nameInput.style.background = "#f5f6f8"
  } else {
    nameInput.removeAttribute("readonly")
    nameInput.style.background = ""
  }
  if (authEmail) {
    emailInput.setAttribute("readonly", "")
    emailInput.style.background = "#f5f6f8"
  } else {
    emailInput.removeAttribute("readonly")
    emailInput.style.background = ""
  }
  $("#profileModal").classList.add("show")
}

function closeProfileModal() {
  $("#profileModal").classList.remove("show")
}

function syncProfileUI() {
  // Prefer auth user data, fall back to portal profile
  const loggedIn = isLoggedIn()
  const authName =
    (_authUser && (_authUser.display_name || _authUser.username)) || ""
  const name = authName || state.portalProfile.name || ""
  const dept = state.portalProfile.department || ""
  const nameTrimmed = (name || "").trim()
  const initial = nameTrimmed ? nameTrimmed.charAt(0) : "?"
  // Portal card body
  renderPortalProfile()
  // Topbar avatar + name (top-right corner of page)
  const avatar = $(".avatar")
  const userSpan = document.querySelector(".user-trigger span:not(.avatar)")
  if (avatar) avatar.textContent = initial
  if (userSpan) userSpan.textContent = name || (loggedIn ? "用户" : "未登录")
  // Popover (shown when clicking top-right avatar)
  const popoverName = $("#popoverName")
  const popoverDept = $("#popoverDept")
  if (popoverName)
    popoverName.textContent = name || (loggedIn ? "用户" : "未登录")
  if (popoverDept)
    popoverDept.innerHTML = `${escapeHTML(dept || "")}<small>个人信息与账号设置</small>`
  // Sidebar (bottom-left)
  const sidebarAvatar = $("#sidebarAvatar")
  const sidebarName = $("#sidebarName")
  if (sidebarAvatar) sidebarAvatar.textContent = initial
  if (sidebarName)
    sidebarName.textContent = name || (loggedIn ? "用户" : "未登录")
}

function handleProfileSave(event) {
  event.preventDefault()
  // Preserve auth identity fields (name/email come from server)
  const authName =
    (_authUser && (_authUser.display_name || _authUser.username)) || ""
  const authEmail = (_authUser && _authUser.email) || ""
  state.portalProfile = {
    name: authName || $("#profileName").value.trim(),
    department: $("#profileDept").value.trim(),
    email: authEmail || $("#profileEmail").value.trim(),
    phone: $("#profilePhone").value.trim(),
  }
  saveProfile()
  closeProfileModal()
  syncProfileUI()
  showToast("个人资料已保存")
}

function openNewsSubModal() {
  renderNewsSubModal()
  $("#newsSubModal").classList.add("show")
}

function closeNewsSubModal() {
  $("#newsSubModal").classList.remove("show")
}

async function saveNewsSubscriptions() {
  const checked = [
    ...document.querySelectorAll("#newsSubGrid input:checked"),
  ].map((cb) => cb.value)
  state.newsSubscriptions = checked
  state.portalPreferences = {
    ...state.portalPreferences,
    news_subscriptions: checked,
  }
  saveNewsSubs()
  try {
    await savePortalPreferences(state.portalPreferences)
    showToast("新闻订阅已更新")
  } catch (error) {
    showToast(error.message || "新闻订阅已保存到本地，后端同步失败")
  }
  closeNewsSubModal()
  renderPortalNews()
}

function openServiceSubModal() {
  renderServiceSubModal()
  $("#serviceSubModal").classList.add("show")
}

function closeServiceSubModal() {
  $("#serviceSubModal").classList.remove("show")
}

async function saveServiceSubscriptions() {
  const checked = [
    ...document.querySelectorAll("#serviceSubGrid input:checked"),
  ].map((cb) => cb.value)
  state.serviceSubscriptions = checked
  state.portalPreferences = {
    ...state.portalPreferences,
    service_subscriptions: checked,
  }
  saveServiceSubs()
  try {
    await savePortalPreferences(state.portalPreferences)
    showToast("服务订阅已更新")
  } catch (error) {
    showToast(error.message || "服务订阅已保存到本地，后端同步失败")
  }
  closeServiceSubModal()
  renderPortalServices()
}

sidebarToggle.addEventListener("click", () => {
  setSidebarCollapsed(!moduleSidebar.classList.contains("collapsed"))
})
sidebarResizer.setAttribute("aria-valuemin", "180")
sidebarResizer.setAttribute("aria-valuemax", "380")
sidebarResizer.setAttribute("aria-valuenow", "230")
sidebarResizer.addEventListener("pointerdown", (event) => {
  if (moduleSidebar.classList.contains("collapsed")) return
  event.preventDefault()
  const startX = event.clientX
  const startWidth = moduleSidebar.getBoundingClientRect().width
  const handlePointerMove = (moveEvent) =>
    setSidebarWidth(startWidth + moveEvent.clientX - startX)
  const stopResize = () => {
    window.removeEventListener("pointermove", handlePointerMove)
    window.removeEventListener("pointerup", stopResize)
  }
  window.addEventListener("pointermove", handlePointerMove)
  window.addEventListener("pointerup", stopResize)
})
sidebarResizer.addEventListener("keydown", (event) => {
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return
  event.preventDefault()
  const step = event.shiftKey ? 24 : 12
  const width = moduleSidebar.getBoundingClientRect().width
  setSidebarWidth(width + (event.key === "ArrowRight" ? step : -step))
})
bindSidebarHandlers()
$$("[data-view-link]").forEach((button) =>
  button.addEventListener("click", () => setView(button.dataset.viewLink)),
)
bindModalTriggers()
$$("[data-close-modal]").forEach((button) =>
  button.addEventListener("click", () => closeEventModal()),
)
$$("[data-close-search]").forEach((button) =>
  button.addEventListener("click", () =>
    $("#searchModal").classList.remove("show"),
  ),
)
$$("[data-close-kb-files]").forEach((button) =>
  button.addEventListener("click", () => closeKbFilesModal()),
)
$("#kbFilesModal")?.addEventListener("click", (event) => {
  if (event.target === $("#kbFilesModal")) closeKbFilesModal()
})
// Modal close / backdrop / submit bindings (static — modals always in DOM)
$$("[data-close-profile]").forEach((el) =>
  el.addEventListener("click", closeProfileModal),
)
$("#profileModal")?.addEventListener("click", (event) => {
  if (event.target === $("#profileModal")) closeProfileModal()
})
$("#profileForm")?.addEventListener("submit", handleProfileSave)
$$("[data-close-news-sub]").forEach((el) =>
  el.addEventListener("click", closeNewsSubModal),
)
$("#newsSubModal")?.addEventListener("click", (event) => {
  if (event.target === $("#newsSubModal")) closeNewsSubModal()
})
$("#saveNewsSubsBtn")?.addEventListener("click", saveNewsSubscriptions)
$$("[data-close-service-sub]").forEach((el) =>
  el.addEventListener("click", closeServiceSubModal),
)
$("#serviceSubModal")?.addEventListener("click", (event) => {
  if (event.target === $("#serviceSubModal")) closeServiceSubModal()
})
$("#saveServiceSubsBtn")?.addEventListener("click", saveServiceSubscriptions)
$("#kbFilesRefresh")?.addEventListener("click", () => {
  const modal = $("#kbFilesModal")
  if (!modal || !modal.classList.contains("show")) return
  const kbNameEl = $("#kbFilesKbName")
  const list = $("#kbFilesList")
  if (!list) return
  list.innerHTML = `<div class="kb-files-loading">加载中...</div>`
  const title = $("#kbFilesModalTitle")
  const match = title?.textContent.match(/文件管理 · (.+)/)
  const kbName = match ? match[1] : ""
  // Re-fetch: the dataset_id is stored in an open state... we need to track it.
  // For now, find by kbName from the knowledge list.
  const item = state.knowledge.find(
    (m) => (m.display_name || m.title || m.resource_id) === kbName,
  )
  if (item?.id) {
    openKbFiles(item.id, kbName)
  } else {
    list.innerHTML = `<div class="kb-files-empty">无法刷新，请关闭后重试。</div>`
  }
})
// ── T7: Notification bell (component-driven, API-backed) ─────────
if (
  window.App &&
  window.App.components &&
  window.App.components.notificationBell
) {
  App.components.notificationBell.init({
    buttonId: "notificationButton",
    badgeId: "notificationBadge",
    dropdownId: "notificationDropdown",
    onFetch: async () => {
      notificationsContractMissing({ operation: "list", limit: 50 })
      renderLocalOverdueTaskNotifications()
    },
    onMarkRead: async (id) => {
      notificationsContractMissing({ notificationId: id, operation: "markRead" })
      openOverdueTaskNotification(id)
      fetchUnreadCount()
    },
    onMarkAllRead: async () => {
      notificationsContractMissing({ operation: "markAllRead" })
      openOverdueTaskNotification("task-overdue-all")
      fetchUnreadCount()
      renderLocalOverdueTaskNotifications()
    },
  })
}

async function fetchUnreadCount() {
  if (
    !window.App ||
    !window.App.components ||
    !window.App.components.notificationBell
  )
    return
  notificationsContractMissing({ operation: "unreadCount" })
  App.components.notificationBell.setCount(getLocalOverdueTaskNotifications().length)
}

// Start SSE stream for real-time notifications + refresh on window focus
if (
  window.App &&
  window.App.components &&
  window.App.components.notificationBell
) {
  fetchUnreadCount()
  window.addEventListener("focus", fetchUnreadCount)
}
startNotificationStream()

$("#userButton").addEventListener("click", (event) => {
  event.stopPropagation()
  closePopovers()
  if (!isLoggedIn()) {
    showLoginOverlay()
  } else {
    $("#userPopover").classList.toggle("show")
  }
})
$("#popoverDept").addEventListener("click", () => {
  closePopovers()
  openProfileModal()
})
document.addEventListener("click", (event) => {
  if (
    !event.target.closest(".popover") &&
    !event.target.closest("#notificationButton") &&
    !event.target.closest("#userButton")
  )
    closePopovers()
})
$("#globalSearchButton").addEventListener("click", () => {
  $("#searchModal").classList.add("show")
  setTimeout(() => {
    var input = $("#globalSearchInput")
    input.value = ""
    input.focus()
    fetchGlobalSearch("").catch(() => {})
  }, 0)
})

// ── Auth form handlers ──────────────────────────────────
$("#loginForm")?.addEventListener("submit", (event) => {
  event.preventDefault()
  var username = document.getElementById("loginUsername").value.trim()
  var password = document.getElementById("loginPassword").value
  if (!username || !password) return
  if (_loginMode === "register") {
    if (password.length < 8) {
      var errEl = document.getElementById("loginError")
      errEl.textContent = "密码至少需要 8 位字符"
      errEl.classList.add("show")
      return
    }
    var displayName =
      document.getElementById("regDisplayName").value.trim() || null
    var email = document.getElementById("regEmail").value.trim() || null
    handleRegister(username, password, displayName, email)
  } else {
    handleLogin(username, password)
  }
})

$("#loginSwitchBtn")?.addEventListener("click", toggleLoginMode)

$("#changePasswordForm")?.addEventListener("submit", (event) => {
  event.preventDefault()
  var currentPw = document.getElementById("cpCurrentPassword").value
  var newPw = document.getElementById("cpNewPassword").value
  var confirmPw = document.getElementById("cpConfirmPassword").value
  if (!currentPw || !newPw || !confirmPw) return
  if (newPw.length < 8) {
    var errEl = document.getElementById("changePasswordError")
    errEl.textContent = "新密码至少需要 8 位字符"
    errEl.classList.add("show")
    return
  }
  if (newPw !== confirmPw) {
    var errEl2 = document.getElementById("changePasswordError")
    errEl2.textContent = "两次输入的密码不一致"
    errEl2.classList.add("show")
    return
  }
  handleChangePassword(currentPw, newPw)
})

// Close login overlay on backdrop click
document.getElementById("loginOverlay")?.addEventListener("click", (event) => {
  if (event.target === document.getElementById("loginOverlay")) {
    document.getElementById("loginOverlay").classList.remove("show")
  }
})
$("#globalSearchInput").addEventListener("input", (event) => {
  var query = event.target.value.trim()
  clearTimeout(_searchTimer)
  _searchTimer = setTimeout(() => {
    fetchGlobalSearch(query).catch((error) => {
      console.warn("Global search failed.", error)
    })
  }, 250)
})
$("#logoutButton").addEventListener("click", () => {
  closePopovers()
  handleLogout()
  showToast("已安全退出当前会话")
})
$("#miniPrev").addEventListener("click", () => changeMonth(-1))
$("#miniNext").addEventListener("click", () => changeMonth(1))
$("#sidePrev").addEventListener("click", () => changeMonth(-1))
$("#sideNext").addEventListener("click", () => changeMonth(1))
$("#calendarPrev").addEventListener("click", () => changeMonth(-1))
$("#calendarNext").addEventListener("click", () => changeMonth(1))
$("#todayButton").addEventListener("click", () => {
  state.year = currentDate.getFullYear()
  state.month = currentDate.getMonth()
  state.selectedScheduleDate = todayKey
  renderWorkbenchSchedule()
  renderMiniCalendar("portalMonth")
  renderCalendar()
  showToast("已回到今天")
})
$$("#calendarMode button").forEach((button) =>
  button.addEventListener("click", () => {
    $$("#calendarMode button").forEach((item) =>
      item.classList.remove("active"),
    )
    button.classList.add("active")
    showToast(`${button.textContent}视图已切换`)
  }),
)
$$("#calendarMode button").forEach((button) =>
  button.addEventListener("click", () => {
    if (button.dataset.calendarMode !== "month")
      showToast(`${button.textContent}视图将在此处展示`)
  }),
)
$$(".tab[data-task-filter]").forEach((button) =>
  button.addEventListener("click", () => {
    $$(".tab[data-task-filter]").forEach((item) =>
      item.classList.remove("active"),
    )
    button.classList.add("active")
    state.taskFilter = button.dataset.taskFilter
    renderTasks()
  }),
)
$("#taskForm").addEventListener("submit", async (event) => {
  event.preventDefault()
  const titleInput = $("#taskTitle")
  const title = titleInput.value.trim()
  if (!title) {
    showToast("请先输入任务内容")
    titleInput.focus()
    return
  }
  const tag = $("#taskTag").value
  const timeVal = $("#taskTime").value || null

  // Auto-fill deadline from tag selection
  var deadline = null
  if (timeVal) {
    var today = new Date()
    var dateStr =
      today.getFullYear() +
      "-" +
      String(today.getMonth() + 1).padStart(2, "0") +
      "-" +
      String(today.getDate()).padStart(2, "0")
    if (tag === "明天") {
      var tomorrow = new Date(today)
      tomorrow.setDate(tomorrow.getDate() + 1)
      dateStr =
        tomorrow.getFullYear() +
        "-" +
        String(tomorrow.getMonth() + 1).padStart(2, "0") +
        "-" +
        String(tomorrow.getDate()).padStart(2, "0")
    } else if (tag === "本周") {
      var friday = new Date(today)
      var dayOfWeek = friday.getDay()
      var daysUntilFriday = dayOfWeek === 0 ? 5 : 5 - dayOfWeek
      if (daysUntilFriday <= 0) daysUntilFriday += 7
      friday.setDate(friday.getDate() + daysUntilFriday)
      dateStr =
        friday.getFullYear() +
        "-" +
        String(friday.getMonth() + 1).padStart(2, "0") +
        "-" +
        String(friday.getDate()).padStart(2, "0")
    }
    deadline = dateStr + "T" + timeVal + ":00"
  } else if (tag !== "跟进") {
    // Default deadline times by tag (no time picker value)
    var now = new Date()
    var defaultDate = new Date(now)
    var defaultTime = "18:00:00"
    if (tag === "明天") {
      defaultDate.setDate(defaultDate.getDate() + 1)
    } else if (tag === "本周") {
      var dow = defaultDate.getDay()
      var toFri = dow === 0 ? 5 : 5 - dow
      if (toFri <= 0) toFri += 7
      defaultDate.setDate(defaultDate.getDate() + toFri)
    }
    var ds =
      defaultDate.getFullYear() +
      "-" +
      String(defaultDate.getMonth() + 1).padStart(2, "0") +
      "-" +
      String(defaultDate.getDate()).padStart(2, "0")
    deadline = ds + "T" + defaultTime
  }

  let task
  try {
    task = await createTaskRemote(title, tag, deadline)
    task = { ...task, deadline: task.deadline || deadline }
  } catch (error) {
    console.warn("Task create stayed local.", error)
    task = { id: Date.now(), title, tag, deadline, done: false }
  }
  state.tasks.unshift(task)
  state.taskFilter = "todo"
  $$(".tab[data-task-filter]").forEach((item) =>
    item.classList.toggle("active", item.dataset.taskFilter === "todo"),
  )
  titleInput.value = ""
  $("#taskTime").value = ""
  saveTasks()
  renderTasks()
  updateSidebarBadge()
})
$("#clearDoneTasks").addEventListener("click", async () => {
  const before = state.tasks.length
  const doneTasks = state.tasks.filter((task) => task.done)
  // Track deleted done-task IDs so they don't reappear on next bootstrap
  for (const task of doneTasks) {
    state.pendingDeletes.add(task.id)
  }
  state.tasks = state.tasks.filter((task) => !task.done)
  savePendingDeletes()
  saveTasks()
  try {
    await clearDoneTasksRemote()
    for (const task of doneTasks) {
      state.pendingDeletes.delete(task.id)
    }
    savePendingDeletes()
  } catch (error) {
    console.warn("Task cleanup stayed local.", error)
  }
  renderTasks()
  updateSidebarBadge()
  showToast(
    before === state.tasks.length ? "没有可清理的已完成任务" : "已清理完成任务",
  )
})
// Chat controls are rendered during workbench refreshes. Delegate from the
// document so replacing the transcript or session list cannot orphan them.
function bindChatWorkbenchEvents() {
  if (document.documentElement.dataset.chatWorkbenchEventsBound === "true") return
  document.documentElement.dataset.chatWorkbenchEventsBound = "true"
  document.addEventListener("input", (event) => {
    const target = event.target instanceof Element
      ? event.target.closest("[data-platform-draft-field]")
      : null
    if (target) updatePlatformActionDraft(target, false)
  })
  document.addEventListener("change", (event) => {
    const target = event.target instanceof Element
      ? event.target.closest("[data-platform-draft-field]")
      : null
    if (!target) return
    const field = target.dataset.platformDraftField
    updatePlatformActionDraft(
      target,
      field === "approval_required" || field === "approval_assignee_type",
    )
  })
  document.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null
    const platformActionButton = target && target.closest("[data-platform-action-message]")
    if (platformActionButton) {
      const messageId = platformActionButton.dataset.platformActionMessage
      const choice = platformActionButton.dataset.platformActionChoice
      if (messageId && (choice === "confirm" || choice === "cancel")) {
        platformActionButton.disabled = true
        void resolvePlatformAction(messageId, choice)
      }
      return
    }
    const approvalButton = target && target.closest("[data-approval-run]")
    if (approvalButton) {
      const runId = approvalButton.dataset.approvalRun
      const choice = approvalButton.dataset.approvalChoice
      if (runId && (choice === "once" || choice === "deny")) {
        approvalButton.disabled = true
        void resolveChatApproval(runId, choice)
      }
      return
    }
    const createKbButton = target && target.closest("#aiKbCreateButton")
    if (createKbButton) {
      $("#aiKbForm")?.reset()
      $("#aiKbDeleteBtn")?.setAttribute("hidden", "")
      window.App.components.modal.open("aiKbModal")
      return
    }
    const uploadKbButton = target && target.closest("#aiKbUploadButton")
    if (uploadKbButton) {
      openKnowledgeImport()
      return
    }
    const sendButton = target && target.closest("#chatSendBtn")
    if (sendButton) {
      void sendChatMessage()
      return
    }
  })
  document.addEventListener("keydown", (event) => {
    const target = event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLInputElement
      ? event.target
      : null
    if (target?.id !== "chatInput" || event.key !== "Enter" || event.shiftKey) return
    event.preventDefault()
    const sendButton = document.getElementById("chatSendBtn")
    if (sendButton && !sendButton.disabled) void sendChatMessage()
  })
  document.addEventListener("input", (event) => {
    const target = event.target instanceof HTMLTextAreaElement ? event.target : null
    if (target?.id !== "chatInput") return
    updateChatSendButton()
    autoResizeChatInput()
  })
}
bindChatWorkbenchEvents()

// ── Admin panel bindings ──────────────────────────────────
$("#adminAddUserBtn")?.addEventListener("click", openAdminUserModal)
$("#adminRefreshBtn")?.addEventListener("click", () => {
  fetchAdminUsers().catch(() => {})
})
$("#adminUserForm")?.addEventListener("submit", createAdminUser)
$$("[data-close-admin-user]").forEach((el) => {
  el.addEventListener("click", closeAdminUserModal)
})
$("#adminUserModal")?.addEventListener("click", (event) => {
  if (event.target === $("#adminUserModal")) closeAdminUserModal()
})
$$("[data-close-admin-kb]").forEach((el) => {
  el.addEventListener("click", closeAdminKbAuthModal)
})
$("#adminKbAuthModal")?.addEventListener("click", (event) => {
  if (event.target === $("#adminKbAuthModal")) closeAdminKbAuthModal()
})
$$("[data-close-admin-reset-pwd]").forEach((el) => {
  el.addEventListener("click", closeAdminResetPwdModal)
})
$("#adminResetPwdModal")?.addEventListener("click", (event) => {
  if (event.target === $("#adminResetPwdModal")) closeAdminResetPwdModal()
})
$("#adminKbAuthSaveBtn")?.addEventListener("click", saveAdminKbAuth)

// Admin search & pagination
var _adminSearchTimer = null
$("#adminUserSearch")?.addEventListener("input", () => {
  clearTimeout(_adminSearchTimer)
  _adminSearchTimer = setTimeout(() => {
    _adminSearchTerm = $("#adminUserSearch").value.trim()
    _adminPage = 1
    fetchAdminUsers().catch(() => {})
  }, 300)
})
$("#adminPagePrev")?.addEventListener("click", () => {
  if (_adminPage > 1) {
    _adminPage--
    fetchAdminUsers().catch(() => {})
  }
})
$("#adminPageNext")?.addEventListener("click", () => {
  var totalPages = Math.max(1, Math.ceil(_adminTotalUsers / _adminPageSize))
  if (_adminPage < totalPages) {
    _adminPage++
    fetchAdminUsers().catch(() => {})
  }
})

// Phase 6: Admin sub-tabs
$$("#adminSubtabs .admin-subtab").forEach((btn) => {
  btn.addEventListener("click", () => {
    switchAdminSubTab(btn.dataset.adminPanel)
  })
})
// Phase 6: Audit panel
$("#adminAuditRefresh")?.addEventListener("click", () => {
  _adminAuditPage = 1
  fetchAdminAudit()
})
$("#adminAuditAction")?.addEventListener("input", () => {
  _adminAuditPage = 1
  clearTimeout(_adminAuditTimer)
  _adminAuditTimer = setTimeout(fetchAdminAudit, 400)
})
$("#adminAuditDecision")?.addEventListener("change", () => {
  _adminAuditPage = 1
  fetchAdminAudit()
})
$("#adminAuditPagePrev")?.addEventListener("click", adminAuditPrev)
$("#adminAuditPageNext")?.addEventListener("click", adminAuditNext)
var _adminAuditTimer = null
// Phase 6: AI Query panel
$("#adminAIQueryRefresh")?.addEventListener("click", () => {
  _adminAIQueryPage = 1
  fetchAdminAIQueries()
})
$("#adminAIQueryDecision")?.addEventListener("change", () => {
  _adminAIQueryPage = 1
  fetchAdminAIQueries()
})
$("#adminAIQueryRisk")?.addEventListener("change", () => {
  _adminAIQueryPage = 1
  fetchAdminAIQueries()
})
$("#adminAIQueryPagePrev")?.addEventListener("click", adminAIQueryPrev)
$("#adminAIQueryPageNext")?.addEventListener("click", adminAIQueryNext)
// Phase 6: Session panel
$("#adminSessionRefresh")?.addEventListener("click", () => {
  _adminSessionPage = 1
  fetchAdminSessions()
})
$("#adminSessionActiveOnly")?.addEventListener("change", () => {
  _adminSessionPage = 1
  fetchAdminSessions()
})
$("#adminSessionPagePrev")?.addEventListener("click", adminSessionPrev)
$("#adminSessionPageNext")?.addEventListener("click", adminSessionNext)
// Phase 6: Anomaly panel
$("#adminAnomalyRefresh")?.addEventListener("click", fetchAdminAnomalies)
// Admin news panel
$("#adminNewsAddBtn")?.addEventListener("click", () => {
  openNewsModal(null)
})
$("#adminNewsPagePrev")?.addEventListener("click", () => {
  if (_adminNewsPage > 1) {
    _adminNewsPage--
    fetchAdminNews()
  }
})
$("#adminNewsPageNext")?.addEventListener("click", () => {
  _adminNewsPage++
  fetchAdminNews()
})
// Admin news modal
$("#adminNewsModal")?.addEventListener("click", function (e) {
  if (e.target === this) this.classList.remove("show")
})
$("#adminNewsModal [data-close-modal]")?.addEventListener("click", () => {
  $("#adminNewsModal").classList.remove("show")
})
$("#adminNewsForm")?.addEventListener("submit", function (e) {
  e.preventDefault()
  var editingId = this.dataset.editingId
  var payload = {
    title: $("#adminNewsTitle").value.trim(),
    source: $("#adminNewsSource").value.trim(),
    category: $("#adminNewsCategory").value.trim(),
    body: $("#adminNewsBody").value.trim(),
    pinned: $("#adminNewsPinned").checked,
    published_at: $("#adminNewsPublishedAt").value || new Date().toISOString(),
  }
  var submitPromise = editingId
    ? updateAdminNews(parseInt(editingId), payload)
    : createAdminNews(payload)
  submitPromise
    .then(() => {
      $("#adminNewsModal").classList.remove("show")
      showToast(editingId ? "资讯已更新" : "资讯已发布")
      fetchAdminNews()
    })
    .catch((e) => {
      showToast("操作失败: " + (e.message || ""))
    })
})
$("#adminNewsDeleteBtn")?.addEventListener("click", () => {
  var editingId = $("#adminNewsForm").dataset.editingId
  if (editingId) {
    deleteNewsById(parseInt(editingId))
    $("#adminNewsModal").classList.remove("show")
  }
})
// Notice publish
$$("[data-open-publish-notice]").forEach((btn) => {
  btn.addEventListener("click", openNoticePublishModal)
})
$("#noticePublishModal")?.addEventListener("click", function (e) {
  if (e.target === this) this.classList.remove("show")
})
$("#noticePublishModal [data-close-modal]")?.addEventListener("click", () => {
  $("#noticePublishModal").classList.remove("show")
})
$("#noticePublishForm")?.addEventListener("submit", (e) => {
  e.preventDefault()
  var payload = {
    title: $("#noticePublishTitle").value.trim(),
    source: $("#noticePublishSource").value.trim(),
    category: $("#noticePublishCategory").value.trim(),
    body: $("#noticePublishBody").value.trim(),
    published_at:
      $("#noticePublishPublishedAt").value || new Date().toISOString(),
    visibility: $("#noticePublishVisibility").value,
  }
  publishNoticeRemote(payload)
    .then(() => {
      $("#noticePublishModal").classList.remove("show")
      showToast("公告已发布")
      fetchPortalBootstrap()
    })
    .catch((e) => {
      showToast("发布失败: " + (e.message || ""))
    })
})

// AI workbench event bindings are handled in bindAiWorkbench()
$("#eventDeleteButton").addEventListener("click", () => deleteEditingEvent())
$("#eventForm").addEventListener("submit", async (event) => {
  event.preventDefault()
  const title = $("#eventName").value.trim()
  const date = $("#eventDate").value
  const tone = $('[name="eventTone"]:checked').value
  if (title && date) {
    const payload = { title, date, tone }
    if (state.editingEventIndex === null) {
      try {
        state.events.push(await createEventRemote(payload))
      } catch (error) {
        console.warn("Calendar create stayed local.", error)
        state.events.push({ title, date, tone })
      }
    } else {
      const current = state.events[state.editingEventIndex]
      const nextEvent = { ...current, ...payload }
      if (current?.id) {
        try {
          state.events[state.editingEventIndex] =
            await updateEventRemote(nextEvent)
        } catch (error) {
          console.warn("Calendar update stayed local.", error)
          state.events[state.editingEventIndex] = { title, date, tone }
        }
      } else {
        state.events[state.editingEventIndex] = { title, date, tone }
      }
    }
    saveEvents()
    const wasEditing = state.editingEventIndex !== null
    state.editingEventIndex = null
    $("#eventModal").classList.remove("show")
    event.target.reset()
    state.selectedScheduleDate = date
    renderCalendar()
    renderWorkbenchSchedule()
    renderMiniCalendar("portalMonth")
    renderWorkbenchOverview()
    showToast(wasEditing ? "日程已更新" : "日程已保存")
  }
})

// ═══════════════════════════════════════════════════════════════
// AI Workbench — new 3-panel RAG analysis console
// ═══════════════════════════════════════════════════════════════

// ── AI data initializers ──────────────────────────────────────
function getInitialAiFavorites() {
  try {
    return JSON.parse(_loadScoped(aiFavoritesKey, "[]"))
  } catch (_) {
    return []
  }
}
function getInitialAiMemory() {
  try {
    return JSON.parse(_loadScoped(aiMemoryKey, "[]"))
  } catch (_) {
    return []
  }
}
function getInitialAiTemplates() {
  try {
    return JSON.parse(_loadScoped(aiTemplatesKey, "[]"))
  } catch (_) {
    return []
  }
}
function getInitialAiTrash() {
  try {
    return JSON.parse(_loadScoped(aiTrashKey, "[]"))
  } catch (_) {
    return []
  }
}
function getInitialAiLinks() {
  try {
    return JSON.parse(_loadScoped(aiLinksKey, "[]"))
  } catch (_) {
    return []
  }
}
function getInitialAiContext() {
  try {
    return JSON.parse(_loadScoped(aiContextKey, "{}"))
  } catch (_) {
    return {}
  }
}
function getInitialAiPanelPrefs() {
  try {
    return JSON.parse(
      _loadScoped(
        aiPanelKey,
        '{"sessionCollapsed":false,"leftWidth":280,"subMenu":"all","leftSearch":""}',
      ),
    )
  } catch (_) {
    return {
      sessionCollapsed: false,
      leftWidth: 280,
      subMenu: "all",
      leftSearch: "",
    }
  }
}

function saveAiFavorites() {
  _saveScoped(aiFavoritesKey, JSON.stringify(state.ai.favorites))
}
function saveAiMemory() {
  _saveScoped(aiMemoryKey, JSON.stringify(state.ai.memoryCards))
}
function saveAiTemplates() {
  _saveScoped(aiTemplatesKey, JSON.stringify(state.ai.templates))
}
function saveAiTrash() {
  _saveScoped(aiTrashKey, JSON.stringify(state.ai.trash))
}
function saveAiLinks() {
  _saveScoped(aiLinksKey, JSON.stringify(state.ai.links))
}
function saveAiContext() {
  // Strip File objects from chips before persisting (File can't be serialized)
  var cleanContext = {}
  Object.keys(state.aiContext).forEach((k) => {
    cleanContext[k] = state.aiContext[k].map((c) => {
      var clean = {
        chipId: c.chipId,
        kind: c.kind,
        typeLabel: c.typeLabel,
        name: c.name,
        ref: c.ref,
        status: c.status,
      }
      if (c.attachmentTitle) clean.attachmentTitle = c.attachmentTitle
      if (c.attachmentContent) clean.attachmentContent = c.attachmentContent
      if (c.status !== "ok" && c.status !== "error") clean.status = "error"
      return clean
    })
  })
  _saveScoped(aiContextKey, JSON.stringify(cleanContext))
}
function saveAiPanelPrefs() {
  _saveScoped(
    aiPanelKey,
    JSON.stringify({
      sessionCollapsed: state.ai.sessionCollapsed,
      leftWidth: state.ai.leftWidth,
      subMenu: state.ai.subMenu,
      leftSearch: state.ai.leftSearch,
    }),
  )
}

function purgeExpiredTrash() {
  var cutoff = Date.now() - 30 * 24 * 60 * 60 * 1000
  state.ai.trash = state.ai.trash.filter((item) => item.deletedAt > cutoff)
  saveAiTrash()
}

// Inject AI state into the main state object
state.ai = {
  favorites: getInitialAiFavorites(),
  memoryCards: getInitialAiMemory(),
  templates: getInitialAiTemplates(),
  trash: getInitialAiTrash(),
  links: getInitialAiLinks(),
  subMenu: getInitialAiPanelPrefs().subMenu || "all",
  leftSearch: getInitialAiPanelPrefs().leftSearch || "",
  sessionCollapsed: getInitialAiPanelPrefs().sessionCollapsed,
  leftWidth: getInitialAiPanelPrefs().leftWidth || 280,
  pickKbMode: false,
  knowledgeCollections: [],
  experienceDomains: [],
  activeExperienceDomainId: null,
  experienceMethods: {},
}
state.aiContext = getInitialAiContext()
repairStoredAiLinkContext()
purgeExpiredTrash()

// ── AI workbench: main render ─────────────────────────────────
function renderAiWorkbench() {
  var left = $("#aiLeft")
  if (!left) return

  // Left panel width
  left.style.width = state.ai.leftWidth + "px"
  left.style.flexBasis = state.ai.leftWidth + "px"

  // Sync sidebar sub-link highlight
  syncSubLinkActive("kbSubLink", state.ai.subMenu)

  // Restore search input value
  var searchInput = $("#aiLeftSearchInput")
  if (searchInput) searchInput.value = state.ai.leftSearch || ""

  renderAiLeftBrowser()
  // renderChatSessions is called from renderAiSessionsView when sessions sub-menu is active
  renderChatSessions()
  renderChatTranscript()
  updateChatSendButton()
  renderContextChips()

  // Empty mode: input centered when no messages in active session
  var session = getActiveSession()
  var isEmpty = !session || !session.messages || session.messages.length === 0
  var aiChat = $("#aiChat")
  if (aiChat) aiChat.classList.toggle("empty-mode", isEmpty)

  // Mobile overlay
  renderAiMobileOverlay()
}

// ── AI left panel browser ─────────────────────────────────────
function renderAiLeftBrowser() {
  var container = $("#aiLeftBottom")
  if (!container) return
  var q = (state.ai.leftSearch || "").trim().toLowerCase()
  if (state.ai.subMenu === "methods") void fetchExperienceDomains()
  switch (state.ai.subMenu) {
    case "kb":
      renderAiKbView(container, q)
      break
    case "methods":
      renderAiMethodsView(container, q)
      break
    case "skills":
      renderAiSkillsView(container, q)
      break
    case "trash":
      renderAiTrashView(container, q)
      break
    case "sessions":
      renderAiSessionsView(container, q)
      break
    default:
      renderAiTabList(container, "all", q)
  }
}

async function fetchExperienceDomains() {
  const service = getAppRuntimeService("experience")
  if (!service?.listDomains || !isLoggedIn()) return
  try {
    const payload = await service.listDomains()
    state.ai.experienceDomains = listItems(payload, [])
    if (state.ai.subMenu === "methods") renderAiMethodsView($("#aiLeftBottom"), (state.ai.leftSearch || "").trim().toLowerCase())
  } catch (error) {
    state.ai.experienceDomains = []
    console.warn("Experience domains unavailable.", error)
  }
}

async function fetchExperienceMethods(domainId) {
  const service = getAppRuntimeService("experience")
  if (!service?.listMethods || !isLoggedIn()) return
  try {
    const payload = await service.listMethods(Number(domainId))
    state.ai.experienceMethods[domainId] = listItems(payload, [])
    state.ai.activeExperienceDomainId = String(domainId)
    renderAiMethodsView($("#aiLeftBottom"), (state.ai.leftSearch || "").trim().toLowerCase())
  } catch (error) {
    showToast(error.message || "经验方法加载失败")
  }
}

function openExperienceDomainModal() {
  $("#aiDomainForm")?.reset()
  window.App.components.modal.open("aiDomainModal")
}

function openExperienceMethodModal(prefill = null) {
  const select = $("#aiMethodDomain")
  if (!select || !state.ai.experienceDomains.length) {
    showToast("请先创建领域")
    return
  }
  select.innerHTML = state.ai.experienceDomains
    .map((domain) => `<option value="${escapeHTML(domain.id)}">${escapeHTML(domain.name)}</option>`)
    .join("")
  $("#aiMethodForm")?.reset()
  if (prefill?.content) {
    $("#aiMethodTitle").value = prefill.content.split(/\r?\n/)[0].slice(0, 80) || "AI总结经验方法"
    $("#aiMethodContent").value = prefill.content
    $("#aiMethodSourceType").value = "ai_summary"
    $("#aiMethodSourceReference").value = prefill.sourceReference || ""
  }
  window.App.components.modal.open("aiMethodModal")
}

function resolveAiLinkRef(id, fallback) {
  var localLink = state.ai.links.find((link) => String(link.id) === String(id))
  var knowledgeLink = state.knowledge.find(
    (item) =>
      String(item.id) === String(id) && item.resource_type === "link",
  )
  return normalizeChatLink(
    (localLink && localLink.url) ||
      (knowledgeLink && knowledgeLink.link_url) ||
      fallback,
  )
}

function isStoredAiLinkEntry(entry) {
  if (!entry) return false
  var legacyRef = String(entry.id || entry.ref || "")
  return (
    entry.kind === "link" ||
    entry.type === "link" ||
    entry.typeLabel === "link" ||
    legacyRef.startsWith("link_")
  )
}

function repairStoredAiLinkContext() {
  var changed = false
  Object.keys(state.aiContext || {}).forEach((sessionId) => {
    var chips = state.aiContext[sessionId]
    if (!Array.isArray(chips)) return
    chips.forEach((chip) => {
      if (!isStoredAiLinkEntry(chip)) return
      var linkRef = resolveAiLinkRef(chip.ref, chip.ref)
      var status = linkRef ? "ok" : "error"
      if (
        chip.kind !== "link" ||
        chip.typeLabel !== "link" ||
        chip.status !== status ||
        (linkRef && chip.ref !== linkRef)
      ) {
        chip.kind = "link"
        chip.typeLabel = "link"
        chip.status = status
        if (linkRef) chip.ref = linkRef
        changed = true
      }
    })
  })
  if (changed) saveAiContext()
}

function renderAiTabList(container, tab, query) {
  if (!tab) tab = "all"
  if (!query) query = ""
  var items = []

  if (tab === "all") {
    items = state.knowledge.filter((kb) => kb.enabled !== false)
    // Merge user links
    items = items.concat(
      state.ai.links.map((l) => ({
        _local: true,
        id: l.id,
        display_name: l.title,
        resource_type: "link",
        link_url: l.url,
        enabled: true,
      })),
    )
  } else if (tab === "link") {
    items = state.knowledge.filter(
      (kb) => kb.resource_type === "link" && kb.enabled !== false,
    )
    items = items.concat(
      state.ai.links.map((l) => ({
        _local: true,
        id: l.id,
        display_name: l.title,
        resource_type: "link",
        link_url: l.url,
        enabled: true,
      })),
    )
  } else if (tab === "file") {
    items = state.knowledge.filter(
      (kb) => kb.resource_type === "file" && kb.enabled !== false,
    )
  }

  // Filter by query
  if (query) {
    items = items.filter((item) => {
      var name = (
        item.display_name ||
        item.title ||
        item.resource_id ||
        ""
      ).toLowerCase()
      var meta = (
        item.link_url ||
        item.resource_id ||
        ""
      ).toLowerCase()
      return name.indexOf(query) !== -1 || meta.indexOf(query) !== -1
    })
  }

  // Favorites section for "all" tab (only kb/link kinds)
  var favItems = []
  if (tab === "all") {
    favItems = state.ai.favorites.filter(
      (f) => f.kind === "kb" || f.kind === "link",
    )
    if (query) {
      favItems = favItems.filter((f) => {
        var n = (f.name || "").toLowerCase()
        return n.indexOf(query) !== -1
      })
    }
  }

  if (!favItems.length && !items.length) {
    container.innerHTML =
      '<div style="text-align:center;padding:30px 10px;color:var(--muted);font-size:12px">' +
      (query ? "未找到匹配的资料" : "暂无资料") +
      "</div>"
    return
  }

  var html = ""

  // Render favorites section
  if (favItems.length) {
    html += '<div class="ai-sub-section-title">常用</div>'
    favItems.forEach((fav) => {
      var favoriteRef = resolveAiLinkRef(fav.id, fav.ref)
      var favoriteKind =
        favoriteRef || isStoredAiLinkEntry(fav) ? "link" : fav.kind
      var favoriteDragRef =
        favoriteKind === "link" ? favoriteRef : fav.ref || fav.id || ""
      html +=
        '<div class="ai-item" draggable="' +
        (favoriteKind !== "link" || !!favoriteRef ? "true" : "false") +
        '" data-drag-kind="' +
        escapeHTML(favoriteKind) +
        '" data-drag-id="' +
        escapeHTML(fav.id || "") +
        '" data-drag-ref="' +
        escapeHTML(favoriteDragRef) +
        '" data-drag-name="' +
        escapeHTML(fav.name) +
        '" data-drag-type="' +
        escapeHTML(fav.type || "") +
        '">'
      html += '<div class="item-icon dataset">⭐</div>'
      html +=
        '<div class="item-info"><strong>' +
        escapeHTML(fav.name) +
        '</strong><span class="item-meta">' +
        escapeHTML(favoriteKind) +
        "</span></div>"
      html +=
        '<button class="item-star starred" data-ai-unstar="' +
        escapeHTML(fav.id) +
        '" title="取消收藏">★</button>'
      html += "</div>"
    })
  }

  // Render all items
  if (items.length) {
    if (favItems.length) html += '<div class="ai-sub-section-title">全部</div>'
    items.forEach((item) => {
      var itemLinkRef =
        item.resource_type === "link" ? normalizeChatLink(item.link_url) : ""
      var itemFavoriteKind = itemLinkRef ? "link" : "kb"
      var isStarred = state.ai.favorites.some(
        (f) =>
          String(f.id) === String(item.id) &&
          (f.kind === itemFavoriteKind ||
            (itemFavoriteKind === "link" && f.kind === "kb")),
      )
      var name = item.display_name || item.title || item.resource_id || "未命名"
      var typeLabel = item.resource_type || "dataset"
      var typeClass =
        typeLabel === "link"
          ? "link"
          : typeLabel === "file"
            ? "file"
            : "dataset"
      var typeIcon =
        typeLabel === "link" ? "🔗" : typeLabel === "file" ? "📄" : "📚"
      var dragKind = typeLabel === "link" ? "link" : "kb"
      var dragRef = dragKind === "link" ? itemLinkRef : String(item.id || "")
      var isDraggable = dragKind !== "link" || !!dragRef
      var metaText =
        typeLabel === "link"
          ? item.link_url || item.resource_id || ""
          : item.resource_id || ""

      html +=
        '<div class="ai-item" draggable="' +
        (isDraggable ? "true" : "false") +
        '" data-drag-kind="' +
        escapeHTML(dragKind) +
        '" data-drag-id="' +
        escapeHTML(item.id) +
        '" data-drag-ref="' +
        escapeHTML(dragRef) +
        '" data-drag-name="' +
        escapeHTML(name) +
        '" data-drag-type="' +
        escapeHTML(typeLabel) +
        '">'
      html += '<div class="item-icon ' + typeClass + '">' + typeIcon + "</div>"
      html +=
        '<div class="item-info"><strong>' +
        escapeHTML(name) +
        '</strong><span class="item-meta">' +
        escapeHTML(metaText) +
        "</span></div>"
      html +=
        '<button class="item-star' +
        (isStarred ? " starred" : "") +
        '" data-ai-star="' +
        escapeHTML(item.id) +
        '" title="收藏">★</button>'
      html +=
        '<button class="item-delete" data-ai-delete="' +
        escapeHTML(item.id) +
        '" title="删除知识项" aria-label="删除知识项">×</button>'
      html += "</div>"
    })
  }
  container.innerHTML = html
  initAiDrag(container)
}

// ── Knowledge base view (merged list + manage) ──────────────
function renderAiKbView(container, query) {
  var items = state.knowledge.filter(
    (kb) => !state.ai.hiddenMappings || !state.ai.hiddenMappings.has(kb.id),
  )
  if (query) {
    items = items.filter((item) => {
      var n = (
        item.display_name ||
        item.title ||
        item.resource_id ||
        ""
      ).toLowerCase()
      var r = (item.resource_id || "").toLowerCase()
      return n.indexOf(query) !== -1 || r.indexOf(query) !== -1
    })
  }
  var toolbar = '<div class="ai-kb-toolbar"><button class="btn primary" id="aiKbCreateButton">新增</button><button class="btn" id="aiKbUploadButton">上传文件</button></div>'
  if (!items.length) {
    container.innerHTML =
      toolbar + '<div style="text-align:center;padding:20px 10px;color:var(--muted);font-size:12px">' +
      (query ? "未找到匹配的知识库" : "暂无知识库映射") +
      "</div>"
    return
  }
  var html = toolbar + '<div class="ai-manage-grid">'
  items.forEach((item) => {
    var title = item.display_name || item.title || item.resource_id || "未命名"
    var rid = item.resource_id || ""
    html += '<article class="kb-card' + (item.enabled ? "" : " disabled") + '">'
    html +=
      '<div class="kb-top"><span class="kb-cover app-purple">' +
      escapeHTML(title).slice(0, 1) +
      "</span><span><h3>" +
      escapeHTML(title) +
      "</h3><p>" +
      escapeHTML(item.resource_type || "dataset") +
      "</p></span></div>"
    html +=
      '<div class="kb-meta"><span>' +
      escapeHTML(rid) +
      "</span><span>" +
      (item.enabled ? "启用" : "停用") +
      "</span></div>"
    html += '<div class="kb-actions">'
    html +=
      '<button class="btn" data-knowledge-rename="' +
      escapeHTML(item.id) +
      '">重命名</button>'
    html +=
      '<button class="btn" data-knowledge-default="' +
      escapeHTML(item.id) +
      '">设为默认</button>'
    html +=
      '<button class="btn" data-knowledge-toggle="' +
      escapeHTML(item.id) +
      '">' +
      (item.enabled ? "停用" : "启用") +
      "</button>"
    html +=
      '<button class="btn danger" data-knowledge-delete="' +
      escapeHTML(item.id) +
      '">删除</button>'
    html += "</div></article>"
  })
  html += "</div>"
  container.innerHTML = html
  bindKnowledgeActions()
}

// ── Methods view (templates) ──────────────────────────────────
function renderAiMethodsView(container, query) {
  var domains = state.ai.experienceDomains || []
  if (query) domains = domains.filter((domain) => (domain.name || "").toLowerCase().indexOf(query) !== -1)
  var html = '<div class="ai-sub-section-title">经验领域</div>'
  html += '<button class="template-add-btn" id="aiAddDomain">+ 新建领域</button>'
  if (domains.length) {
    html += '<button class="template-add-btn" id="aiAddMethod">+ 新建经验方法</button>'
  }
  if (!domains.length) {
    html += '<div style="text-align:center;padding:16px 10px;color:var(--muted);font-size:12px">暂无领域<br /><small>创建领域后沉淀人工经验或 AI 总结</small></div>'
  } else {
    domains.forEach((domain) => {
      html += '<article class="template-card experience-domain-card" data-experience-domain="' + escapeHTML(domain.id) + '">'
      html += '<div class="template-name">' + escapeHTML(domain.name || "未命名领域") + '</div>'
      html += '<div class="template-preview">' + escapeHTML(domain.description || "暂无领域说明") + '</div>'
      html += '<div class="template-actions"><span>' + escapeHTML(String(domain.method_count || 0)) + ' 条经验方法</span></div></article>'
      if (String(state.ai.activeExperienceDomainId || "") === String(domain.id)) {
        const methods = state.ai.experienceMethods[domain.id] || []
        html += '<div class="experience-method-list">' + (methods.length ? methods.map((method) => '<div class="template-card"><div class="template-name">' + escapeHTML(method.title || "未命名方法") + '</div><div class="template-preview">' + escapeHTML(method.content || "") + '</div><div class="template-actions"><span>' + (method.source_type === "ai_summary" ? "AI总结" : "人工经验") + '</span></div></div>').join("") : '<div class="template-preview">该领域暂无经验方法</div>') + '</div>'
      }
    })
  }
  container.innerHTML = html
}

// ── Skills view (placeholder) ──────────────────────────────────
function renderAiSkillsView(container, query) {
  container.innerHTML =
    '<div style="text-align:center;padding:40px 10px;color:var(--muted);font-size:12px">技能库建设中<br /><small>技能库功能即将上线</small></div>'
}

// ── Trash view ─────────────────────────────────────────────────
function renderAiTrashView(container, query) {
  var items = state.ai.trash
  if (query) {
    items = items.filter((item) => {
      var n = (item.name || item.title || "").toLowerCase()
      return n.indexOf(query) !== -1
    })
  }
  if (!items.length) {
    container.innerHTML =
      '<div style="text-align:center;padding:30px 10px;color:var(--muted);font-size:12px">' +
      (query
        ? "未找到匹配的回收项"
        : "回收站为空<br /><small>删除的知识项和会话会保留 30 天</small>") +
      "</div>"
    return
  }
  var html = ""
  items.forEach((item) => {
    var daysLeft = Math.max(
      0,
      Math.ceil(
        (item.deletedAt + 30 * 24 * 60 * 60 * 1000 - Date.now()) /
          (24 * 60 * 60 * 1000),
      ),
    )
    var isDraggable =
      item.kind === "kb" || item.kind === "link" || item.kind === "file"
    html +=
      '<div class="trash-item' +
      (isDraggable ? " ai-item" : "") +
      '"' +
      (isDraggable
        ? ' draggable="true" data-drag-kind="' +
          escapeHTML(item.kind) +
          '" data-drag-id="' +
          escapeHTML(item.id || "") +
          '" data-drag-name="' +
          escapeHTML(item.name || item.title || "未命名") +
          '" data-drag-type="' +
          escapeHTML(item.kind) +
          '"'
        : "") +
      ">"
    html +=
      '<div class="trash-info"><strong>' +
      escapeHTML(item.name || item.title || "未命名") +
      "</strong>"
    html +=
      '<span class="trash-meta">' +
      escapeHTML(item.kind) +
      " · 剩余 " +
      daysLeft +
      " 天</span></div>"
    html +=
      '<button class="trash-restore" data-trash-restore="' +
      escapeHTML(item.id) +
      '">恢复</button>'
    html += "</div>"
  })
  container.innerHTML = html
  var draggableItems = container.querySelectorAll(".ai-item")
  if (draggableItems.length) initAiDrag(container)
}

// ── Sessions view in left panel ────────────────────────────────
function renderAiSessionsView(container, query) {
  var html = ""
  html +=
    '<button class="btn" id="newChatSession" style="margin-bottom:8px"><svg class="icon" style="width:14px;height:14px"><use href="#i-plus"/></svg>新建</button>'
  html += '<div class="chat-sessions-list" id="chatSessionsList"></div>'
  container.innerHTML = html
  renderChatSessions(query)
  const newSessionButton = $("#newChatSession")
  if (newSessionButton) {
    newSessionButton.onclick = () => {
      void createChatSession()
    }
  }
}

function renderAiQuickList(container, kind) {
  var html = ""
  if (kind === "favorites") {
    if (!state.ai.favorites.length) {
      html =
        '<div style="text-align:center;padding:30px 10px;color:var(--muted);font-size:12px">暂无收藏<br /><small>点击知识项旁的 ★ 收藏</small></div>'
    } else {
      state.ai.favorites.forEach((fav) => {
        var favoriteRef = resolveAiLinkRef(fav.id, fav.ref)
        var favoriteKind =
          favoriteRef || isStoredAiLinkEntry(fav) ? "link" : fav.kind
        var favoriteDragRef =
          favoriteKind === "link" ? favoriteRef : fav.ref || fav.id || ""
        html +=
          '<div class="ai-item" draggable="' +
          (favoriteKind !== "link" || !!favoriteRef ? "true" : "false") +
          '" data-drag-kind="' +
          escapeHTML(favoriteKind) +
          '" data-drag-id="' +
          escapeHTML(fav.id || "") +
          '" data-drag-ref="' +
          escapeHTML(favoriteDragRef) +
          '" data-drag-name="' +
          escapeHTML(fav.name) +
          '" data-drag-type="' +
          escapeHTML(fav.type || "") +
          '">'
        html += '<div class="item-icon dataset">⭐</div>'
        html +=
          '<div class="item-info"><strong>' +
          escapeHTML(fav.name) +
          '</strong><span class="item-meta">' +
          escapeHTML(favoriteKind) +
          "</span></div>"
        html +=
          '<button class="item-star starred" data-ai-unstar="' +
          escapeHTML(fav.id) +
          '" title="取消收藏">★</button>'
        html += "</div>"
      })
    }
  } else if (kind === "domains") {
    html += '<button class="template-add-btn" id="aiAddDomain">+ 新建领域</button>'
    if (!state.ai.experienceDomains.length) {
      html += '<div style="text-align:center;padding:20px 10px;color:var(--muted);font-size:12px">暂无领域<br /><small>将经验内容归类沉淀</small></div>'
    } else {
      state.ai.experienceDomains.forEach((domain) => {
        html += '<div class="template-card" data-experience-domain="' + escapeHTML(domain.id) + '">' +
          '<div class="template-name">' + escapeHTML(domain.name || "未命名领域") + '</div>' +
          '<div class="template-preview">' + escapeHTML(domain.description || "") + '</div></div>'
      })
    }
  } else if (kind === "trash") {
    if (!state.ai.trash.length) {
      html =
        '<div style="text-align:center;padding:30px 10px;color:var(--muted);font-size:12px">回收站为空<br /><small>删除的知识项和会话会保留 30 天</small></div>'
    } else {
      state.ai.trash.forEach((item) => {
        var daysLeft = Math.max(
          0,
          Math.ceil(
            (item.deletedAt + 30 * 24 * 60 * 60 * 1000 - Date.now()) /
              (24 * 60 * 60 * 1000),
          ),
        )
        html += '<div class="trash-item">'
        html +=
          '<div class="trash-info"><strong>' +
          escapeHTML(item.name || item.title || "未命名") +
          "</strong>"
        html +=
          '<span class="trash-meta">' +
          escapeHTML(item.kind) +
          " · 剩余 " +
          daysLeft +
          " 天</span></div>"
        html +=
          '<button class="trash-restore" data-trash-restore="' +
          escapeHTML(item.id) +
          '">恢复</button>'
        html += "</div>"
      })
    }
  }
  container.innerHTML = html
  initAiDrag(container)
}

function renderAiManageGrid(container) {
  var items = state.knowledge.filter(
    (kb) => !state.ai.hiddenMappings || !state.ai.hiddenMappings.has(kb.id),
  )
  if (!items.length) {
    container.innerHTML =
      '<div style="text-align:center;padding:20px 10px;color:var(--muted);font-size:12px">暂无知识条目<br /><small>创建条目或上传文件后即可开始</small></div>'
    return
  }

  var html = '<div class="ai-manage-grid">'
  items.forEach((item) => {
    var title = item.display_name || item.title || item.resource_id || "未命名"
    var rid = item.resource_id || ""
    html += '<article class="kb-card' + (item.enabled ? "" : " disabled") + '">'
    html +=
      '<div class="kb-top"><span class="kb-cover app-purple">' +
      escapeHTML(title).slice(0, 1) +
      "</span><span><h3>" +
      escapeHTML(title) +
      "</h3><p>" +
      escapeHTML(item.resource_type || "dataset") +
      "</p></span></div>"
    html +=
      '<div class="kb-meta"><span>' +
      escapeHTML(rid) +
      "</span><span>" +
      (item.enabled ? "启用" : "停用") +
      "</span></div>"
    html += '<div class="kb-actions">'
    html +=
      '<button class="btn" data-knowledge-rename="' +
      escapeHTML(item.id) +
      '">重命名</button>'
    html +=
      '<button class="btn" data-knowledge-default="' +
      escapeHTML(item.id) +
      '">设为默认</button>'
    html +=
      '<button class="btn" data-knowledge-toggle="' +
      escapeHTML(item.id) +
      '">' +
      (item.enabled ? "停用" : "启用") +
      "</button>"
    html +=
      '<button class="btn danger" data-knowledge-delete="' +
      escapeHTML(item.id) +
      '">删除</button>'
    html += "</div></article>"
  })
  html += "</div>"
  container.innerHTML = html
  bindKnowledgeActions()
}

// ── AI context chips ──────────────────────────────────────────
function getSessionContext(sessionId) {
  if (!sessionId) return []
  return state.aiContext[sessionId] || []
}

function renderContextChips() {
  var wrap = $("#contextChipsWrap")
  var clearBtn = $("#clearContextChips")
  if (!wrap) return
  var session = getActiveSession()
  var chips = session ? getSessionContext(session.id) : []

  if (!chips.length) {
    wrap.innerHTML =
      '<span style="font-size:11px;color:var(--subtle)">拖入知识项或文件建立上下文</span>'
    if (clearBtn) clearBtn.style.display = "none"
  } else {
    wrap.innerHTML = chips
      .map((chip, i) => {
        var cls = chip.status === "error" ? " error" : ""
        cls += " " + (chip.kind || "kb")
        var name = chip.name || "未命名"
        if (name.length > 24) name = name.slice(0, 22) + "…"
        var typeLabel = chip.typeLabel || chip.kind || "kb"
        var html = '<span class="context-chip' + cls + '">'
        html += '<span class="chip-type">[' + escapeHTML(typeLabel) + "]</span>"
        html += '<span class="chip-name">' + escapeHTML(name) + "</span>"
        if (chip.status === "error" && chip.file) {
          html +=
            '<button class="chip-retry" data-chip-retry="' +
            i +
            '">重试</button>'
        }
        if (chip.status === "uploading" && Number.isFinite(chip.progress)) {
          html += '<span class="chip-progress">' + chip.progress + "%</span>"
        }
        html +=
          '<button class="chip-remove" data-chip-remove="' + i + '">×</button>'
        html += "</span>"
        return html
      })
      .join("")
    if (clearBtn) clearBtn.style.display = ""
  }
  updateSessionContextCount()
}

function addContextChip(entry) {
  var session = getActiveSession()
  if (!session) {
    createChatSession()
    session = getActiveSession()
    if (!session) return
  }
  var chips = getSessionContext(session.id)
  var kind = entry.kind || "kb"
  var ref =
    kind === "link"
      ? normalizeChatLink(entry.ref || entry.url)
      : entry.ref || entry.id || ""
  if (kind === "link" && !ref) {
    showToast("链接地址无效，请重新添加")
    return
  }
  // Dedupe by (kind, name)
  var exists = chips.some((c) => c.kind === kind && c.name === entry.name)
  if (exists) return
  chips.push({
    chipId: "c_" + Date.now(),
    kind: kind,
    typeLabel: entry.typeLabel || kind,
    name: entry.name || "未命名",
    ref: ref,
    status: "ok",
  })
  state.aiContext[session.id] = chips
  saveAiContext()
  renderContextChips()
}

function removeContextChip(index) {
  var session = getActiveSession()
  if (!session) return
  var chips = getSessionContext(session.id)
  chips.splice(index, 1)
  state.aiContext[session.id] = chips
  saveAiContext()
  renderContextChips()
}

function clearContextChips() {
  var session = getActiveSession()
  if (!session) return
  var chips = getSessionContext(session.id)
  if (
    chips.length > 5 &&
    !confirm("确定要清空全部 " + chips.length + " 个上下文标签吗？")
  )
    return
  state.aiContext[session.id] = []
  saveAiContext()
  renderContextChips()
}

function updateSessionContextCount() {
  var el = $("#sessionContextCount")
  if (!el) return
  var session = getActiveSession()
  var count = session ? getSessionContext(session.id).length : 0
  el.textContent = count + " 上下文"
}

// ── AI file upload ────────────────────────────────────────────
async function addFileChip(file) {
  var session = getActiveSession()
  if (!session) {
    await createChatSession()
    session = getActiveSession()
    if (!session) return
  }
  var chips = getSessionContext(session.id)
  var chip = {
    chipId: "c_" + Date.now(),
    kind: "file",
    typeLabel: "文件",
    name: file.name,
    ref: "",
    status: "uploading",
    file: file,
  }
  chips.push(chip)
  state.aiContext[session.id] = chips
  saveAiContext()
  renderContextChips()
  uploadContextFile(chips.length - 1, file)
}

function uploadContextFile(index, file) {
  var session = getActiveSession()
  if (!session) return
  var chatService = getAppRuntimeService("chat")
  var fd = new FormData()
  fd.append("file", file)

  var uploadPromise =
    chatService && chatService.prepareAttachment && isLoggedIn()
      ? chatService.prepareAttachment(fd, (loaded, total) => {
          var chips = getSessionContext(session.id)
          if (chips[index] && total) {
            chips[index].progress = Math.round((loaded / total) * 100)
            state.aiContext[session.id] = chips
            renderContextChips()
          }
        })
      : Promise.reject(new Error("聊天附件契约服务未初始化"))
  uploadPromise
    .then((payload) => {
      var chips = getSessionContext(session.id)
      if (chips[index]) {
        chips[index].status = "ok"
        chips[index].attachmentTitle = payload.title || file.name
        chips[index].attachmentContent = payload.content || ""
        chips[index].mediaType =
          payload.media_type || file.type || "application/octet-stream"
        chips[index].size = payload.size || file.size || 0
        chips[index].ref =
          payload.id ||
          payload.attachment_id ||
          payload.file_name ||
          file.name
        state.aiContext[session.id] = chips
        saveAiContext()
        renderContextChips()
      }
    })
    .catch((error) => {
      var chips = getSessionContext(session.id)
      if (chips[index]) {
        chips[index].status = "error"
        state.aiContext[session.id] = chips
        saveAiContext()
        renderContextChips()
        const reason = error?.message || error?.code || "附件服务不可用"
        showToast("文件上传失败: " + file.name + "（" + reason + "）")
      }
    })
}

// ── AI drag & drop ────────────────────────────────────────────
function initAiDrag(container) {
  $$(".ai-item", container).forEach((el) => {
    el.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData(
        "application/json",
        JSON.stringify({
          kind: el.dataset.dragKind,
          id: el.dataset.dragId,
          name: el.dataset.dragName,
          typeLabel: el.dataset.dragType,
          ref: el.dataset.dragRef ||
            (el.dataset.dragKind === "link" ? "" : el.dataset.dragId),
        }),
      )
      e.dataTransfer.effectAllowed = "copy"
    })
  })
}

function bindAiDropTargets() {
  var targets = [$("#contextChips"), $("#chatInput"), $("#aiChat")]
  targets.forEach((target) => {
    if (!target) return
    target.addEventListener("dragover", (e) => {
      e.preventDefault()
      e.dataTransfer.dropEffect = "copy"
    })
    target.addEventListener("drop", (e) => {
      e.preventDefault()
      // Handle files
      if (e.dataTransfer.files && e.dataTransfer.files.length) {
        Array.from(e.dataTransfer.files).forEach((file) => {
          addFileChip(file)
        })
        return
      }
      // Handle JSON payload
      try {
        var data = JSON.parse(e.dataTransfer.getData("application/json"))
        if (data && data.name) {
          addContextChip(data)
        }
      } catch (_) {}
    })
  })
  // File input handler
  var fileInput = $("#chatFileInput")
  if (fileInput) {
    fileInput.addEventListener("change", () => {
      if (fileInput.files && fileInput.files.length) {
        Array.from(fileInput.files).forEach((file) => {
          addFileChip(file)
        })
        fileInput.value = ""
      }
    })
  }
}

// ── AI chat: transcript enhancements ──────────────────────────
function enhanceAssistantHtml(container) {
  // Add copy buttons to code blocks
  $$("pre code", container).forEach((code) => {
    var pre = code.parentElement
    if (pre.querySelector(".code-copy-btn")) return
    var btn = document.createElement("button")
    btn.className = "code-copy-btn"
    btn.textContent = "复制"
    btn.addEventListener("click", () => {
      navigator.clipboard
        .writeText(code.textContent || "")
        .then(() => {
          btn.textContent = "已复制"
          setTimeout(() => {
            btn.textContent = "复制"
          }, 2000)
        })
        .catch(() => {})
    })
    pre.appendChild(btn)
  })
}

// ── AI chat: scroll-to-bottom ─────────────────────────────────
function bindAiChatScroll() {
  var transcript = $("#chatTranscript")
  var scrollBtn = $("#chatScrollBottom")
  if (!transcript || !scrollBtn) return

  transcript.addEventListener("scroll", () => {
    var dist =
      transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight
    scrollBtn.hidden = dist < 80
  })

  scrollBtn.addEventListener("click", () => {
    transcript.scrollTop = transcript.scrollHeight
    scrollBtn.hidden = true
  })
}

// ── AI template system ────────────────────────────────────────

function openTemplateFillModal(template) {
  var modal = $("#aiTemplateModal")
  var form = $("#aiTemplateForm")
  var titleEl = $("#aiTemplateModalTitle")
  if (!modal || !form) return

  // Scan for {{variables}}
  var vars = []
  var content = template.content
  var regex = /\{\{(\w+)\}\}/g
  var match
  while ((match = regex.exec(content)) !== null) {
    if (vars.indexOf(match[1]) === -1) vars.push(match[1])
  }

  if (titleEl) titleEl.textContent = "填充模板: " + template.name
  var nameField = $("#aiTemplateNameField")
  if (nameField) nameField.style.display = "none"

  var varsContainer = $("#aiTemplateVars")
  if (varsContainer) {
    varsContainer.innerHTML = vars.length
      ? vars
          .map(
            (v) =>
              '<div class="template-var-row"><label>{{' +
              v +
              '}}</label><input data-var-name="' +
              v +
              '" placeholder="输入 ' +
              v +
              '" /></div>',
          )
          .join("")
      : ""
  }

  var contentEl = $("#aiTemplateContent")
  if (contentEl) {
    contentEl.value = content
    contentEl.readOnly = true
  }

  var deleteBtn = $("#aiTemplateDeleteBtn")
  if (deleteBtn) {
    deleteBtn.hidden = false
    deleteBtn.dataset.templateId = template.id
    deleteBtn.onclick = () => {
      state.ai.templates = state.ai.templates.filter(
        (t) => t.id !== template.id,
      )
      saveAiTemplates()
      window.App.components.modal.close("aiTemplateModal")
      showToast("模板已删除")
      renderAiWorkbench()
    }
  }

  form.onsubmit = (e) => {
    e.preventDefault()
    var result = content
    if (varsContainer) {
      $$("[data-var-name]", varsContainer).forEach((input) => {
        result = result
          .split("{{" + input.dataset.varName + "}}")
          .join(input.value || "{{" + input.dataset.varName + "}}")
      })
    }
    var chatInput = $("#chatInput")
    if (chatInput) {
      chatInput.value = result
      chatInput.focus()
      autoResizeChatInput()
      updateChatSendButton()
    }
    window.App.components.modal.close("aiTemplateModal")
  }

  window.App.components.modal.open("aiTemplateModal")
}

function openTemplateSaveModal() {
  var modal = $("#aiTemplateModal")
  var form = $("#aiTemplateForm")
  var titleEl = $("#aiTemplateModalTitle")
  if (!modal || !form) return

  if (titleEl) titleEl.textContent = "保存为模板"
  var nameField = $("#aiTemplateNameField")
  if (nameField) nameField.style.display = ""
  var varsContainer = $("#aiTemplateVars")
  if (varsContainer) varsContainer.innerHTML = ""

  var contentEl = $("#aiTemplateContent")
  if (contentEl) {
    contentEl.value = $("#chatInput")?.value || ""
    contentEl.readOnly = false
  }

  var deleteBtn = $("#aiTemplateDeleteBtn")
  if (deleteBtn) deleteBtn.hidden = true

  var nameInput = $("#aiTemplateName")
  if (nameInput) nameInput.value = ""

  form.onsubmit = (e) => {
    e.preventDefault()
    var name = ($("#aiTemplateName")?.value || "").trim()
    var content = ($("#aiTemplateContent")?.value || "").trim()
    if (!name || !content) return
    state.ai.templates.push({
      id: "tpl_" + Date.now(),
      name: name,
      content: content,
      createdAt: new Date().toISOString().slice(0, 10),
    })
    saveAiTemplates()
    window.App.components.modal.close("aiTemplateModal")
    showToast("模板已保存")
    renderAiWorkbench()
  }

  window.App.components.modal.open("aiTemplateModal")
}

// ── AI memory ingestion ───────────────────────────────────────
function ingestMemoryUpdates(updates) {
  if (!updates || !Array.isArray(updates) || !updates.length) return
  var added = 0
  updates.forEach((item) => {
    var content =
      typeof item === "string" ? item : item.content || item.text || ""
    if (!content) return
    // Simple dedupe by content hash
    var hash = content.slice(0, 60)
    if (state.ai.memoryCards.some((c) => c.content.slice(0, 60) === hash))
      return
    state.ai.memoryCards.push({
      id: "mem_" + Date.now() + "_" + Math.random().toString(36).slice(2, 6),
      content: content,
      sessionId: state.chatSessions.activeSessionId || "",
      createdAt: new Date().toISOString().slice(0, 10),
      source: "chat",
    })
    added++
  })
  // Cap at 200
  if (state.ai.memoryCards.length > 200) {
    state.ai.memoryCards = state.ai.memoryCards.slice(-200)
  }
  saveAiMemory()
}

// ── AI plus popover ───────────────────────────────────────────
function togglePlusPopover() {
  var popover = $("#chatPlusPopover")
  if (!popover) return
  var isHidden = popover.hidden
  popover.hidden = !isHidden
  if (!isHidden) return

  // Close on outside click
  var handler = (e) => {
    if (!popover.contains(e.target) && e.target !== $("#chatPlusBtn")) {
      popover.hidden = true
      document.removeEventListener("click", handler)
    }
  }
  setTimeout(() => {
    document.addEventListener("click", handler)
  }, 0)
}

// ── AI left panel actions ─────────────────────────────────────
function toggleAiFavorite(id) {
  var item = state.knowledge.find((kb) => String(kb.id) === String(id))
  var localLink = state.ai.links.find((link) => String(link.id) === String(id))
  var name = item
    ? item.display_name || item.title || item.resource_id
    : localLink
      ? localLink.title
      : id
  var favoriteRef = resolveAiLinkRef(
    id,
    (item && item.link_url) || (localLink && localLink.url),
  )
  var favoriteKind = favoriteRef ? "link" : "kb"
  var existingIdx = state.ai.favorites.findIndex(
    (f) =>
      String(f.id) === String(id) &&
      (f.kind === favoriteKind ||
        (favoriteKind === "link" && f.kind === "kb")),
  )
  if (existingIdx >= 0) {
    state.ai.favorites.splice(existingIdx, 1)
  } else {
    state.ai.favorites.push({
      id: id,
      kind: favoriteKind,
      name: name,
      ref: favoriteRef,
      type: item ? item.resource_type : localLink ? "link" : "unknown",
    })
  }
  saveAiFavorites()
  renderAiWorkbench()
  showToast(existingIdx >= 0 ? "已取消收藏" : "已添加到常用")
}

// ── AI mobile overlay ─────────────────────────────────────────
function renderAiMobileOverlay() {
  if (window.App && window.App.aiMobileOverlay) {
    window.App.aiMobileOverlay.render()
  }
}

function toggleAiMobilePanel() {
  if (window.App && window.App.aiMobileOverlay) {
    window.App.aiMobileOverlay.toggle()
  }
}

// ── AI workbench: all event bindings ──────────────────────────
function bindAiWorkbench() {
  var transcript = $("#chatTranscript")
  if (transcript && !transcript.dataset.bound) {
    transcript.dataset.bound = "true"
    transcript.addEventListener("click", (event) => {
      var retry = event.target.closest("[data-chat-retry]")
      if (retry) {
        void retryChatMessage(retry.dataset.chatRetry)
        return
      }
      var saveExperience = event.target.closest("[data-save-experience-method]")
      if (saveExperience) {
        const session = getActiveSession()
        const message = session?.messages.find(
          (item, index) => String(item.id || index) === saveExperience.dataset.saveExperienceMethod,
        )
        if (message) {
          state.ai.subMenu = "methods"
          saveAiPanelPrefs()
          renderAiWorkbench()
          void fetchExperienceDomains().then(() => {
            openExperienceMethodModal({
              content: message.content,
              sourceReference: `chat:${message.id || "message"}`,
            })
          })
        }
        return
      }
      var citation = event.target.closest("[data-ref-turn-id]")
      if (citation) {
        event.preventDefault()
        void resolveChatCitation(citation)
      }
    })
  }
  // Left panel: search input
  var leftSearch = $("#aiLeftSearchInput")
  if (leftSearch) {
    leftSearch.addEventListener("input", () => {
      state.ai.leftSearch = leftSearch.value
      saveAiPanelPrefs()
      renderAiLeftBrowser()
      if (state.ai.subMenu === "sessions")
        renderChatSessions(state.ai.leftSearch)
    })
  }

  // Left panel: star clicks & template actions & trash restore & new session (delegation)
  var leftBottom = $("#aiLeftBottom")
  if (leftBottom) {
    leftBottom.addEventListener("click", async (e) => {
      var starBtn = e.target.closest("[data-ai-star]")
      if (starBtn) {
        toggleAiFavorite(starBtn.dataset.aiStar)
        return
      }
      var deleteBtn = e.target.closest("[data-ai-delete]")
      if (deleteBtn) {
        var entryId = Number(deleteBtn.dataset.aiDelete)
        if (!Number.isFinite(entryId)) return
        try {
          await requireAppRuntimeService("knowledge", "archiveEntry").archiveEntry(entryId)
          await fetchKnowledgeMappings(state.kbFilter, state.ai.leftSearch)
          renderAiWorkbench()
          showToast("知识项已删除")
        } catch (error) {
          console.warn("Knowledge entry deletion failed.", error)
          showToast(error.message || "知识项删除失败")
        }
        return
      }
      var unstarBtn = e.target.closest("[data-ai-unstar]")
      if (unstarBtn) {
        var idx = state.ai.favorites.findIndex(
          (f) => f.id === unstarBtn.dataset.aiUnstar,
        )
        if (idx >= 0) {
          state.ai.favorites.splice(idx, 1)
          saveAiFavorites()
          renderAiWorkbench()
          showToast("已取消收藏")
        }
        return
      }
      var memDel = e.target.closest("[data-memory-delete]")
      if (memDel) {
        state.ai.memoryCards = state.ai.memoryCards.filter(
          (c) => c.id !== memDel.dataset.memoryDelete,
        )
        saveAiMemory()
        renderAiWorkbench()
        showToast("记忆已删除")
        return
      }
      var tplDel = e.target.closest("[data-template-delete]")
      if (tplDel) {
        state.ai.templates = state.ai.templates.filter(
          (t) => t.id !== tplDel.dataset.templateDelete,
        )
        saveAiTemplates()
        renderAiWorkbench()
        showToast("模板已删除")
        return
      }
      var trashRestore = e.target.closest("[data-trash-restore]")
      if (trashRestore) {
        var item = state.ai.trash.find(
          (t) => t.id === trashRestore.dataset.trashRestore,
        )
        if (item) {
          state.ai.trash = state.ai.trash.filter((t) => t.id !== item.id)
          if (item.kind === "chat-session" && item.payload) {
            state.chatSessions.sessions.unshift(item.payload)
            saveChatSessions()
          }
          saveAiTrash()
          renderAiWorkbench()
          showToast("已恢复")
        }
        return
      }
      var addTplBtn = e.target.closest("#aiAddTemplate")
      if (addTplBtn) {
        openTemplateSaveModal()
        return
      }
      var addDomainBtn = e.target.closest("#aiAddDomain")
      if (addDomainBtn) {
        openExperienceDomainModal()
        return
      }
      var addMethodBtn = e.target.closest("#aiAddMethod")
      if (addMethodBtn) {
        openExperienceMethodModal()
        return
      }
      var experienceDomain = e.target.closest("[data-experience-domain]")
      if (experienceDomain) {
        void fetchExperienceMethods(experienceDomain.dataset.experienceDomain)
        return
      }
      // Template double-click
      var tplCard = e.target.closest("[data-template-id]")
      if (tplCard) {
        var template = state.ai.templates.find(
          (t) => t.id === tplCard.dataset.templateId,
        )
        if (template) openTemplateFillModal(template)
        return
      }
    })
  }

  // Context chips: remove / retry / clear
  var chipsBar = $("#contextChips")
  if (chipsBar) {
    chipsBar.addEventListener("click", (e) => {
      var removeBtn = e.target.closest("[data-chip-remove]")
      if (removeBtn) {
        removeContextChip(parseInt(removeBtn.dataset.chipRemove))
        return
      }
      var retryBtn = e.target.closest("[data-chip-retry]")
      if (retryBtn) {
        var idx = parseInt(retryBtn.dataset.chipRetry)
        var session = getActiveSession()
        if (!session) return
        var chips = getSessionContext(session.id)
        if (chips[idx] && chips[idx].file) {
          chips[idx].status = "uploading"
          renderContextChips()
          uploadContextFile(idx, chips[idx].file)
        }
        return
      }
      var clearBtn = e.target.closest("#clearContextChips")
      if (clearBtn) {
        clearContextChips()
        return
      }
    })
  }

  // Plus popover
  var plusBtn = $("#chatPlusBtn")
  if (plusBtn) {
    plusBtn.addEventListener("click", (e) => {
      e.stopPropagation()
      togglePlusPopover()
    })
  }

  // Plus popover actions (delegation)
  var popover = $("#chatPlusPopover")
  if (popover) {
    popover.addEventListener("click", (e) => {
      var action = e.target.closest("[data-plus-action]")
      if (!action) return
      var cmd = action.dataset.quickCmd
      if (cmd) {
        var input = $("#chatInput")
        if (input) {
          input.value = cmd
          input.focus()
          autoResizeChatInput()
          updateChatSendButton()
        }
      } else if (action.dataset.plusAction === "upload") {
        var fileInput = $("#chatFileInput")
        if (fileInput) fileInput.click()
      } else if (action.dataset.plusAction === "link") {
        openAiLinkModal()
      } else if (action.dataset.plusAction === "pick-kb") {
        state.ai.pickKbMode = true
        state.ai.subMenu = "kb"
        state.ai.leftSearch = ""
        saveAiPanelPrefs()
        renderAiWorkbench()
        showToast("点击知识库卡片添加到上下文")
      } else if (action.dataset.plusAction === "save-template") {
        openTemplateSaveModal()
      }
      popover.hidden = true
    })
  }

  // Mode select change
  var modeSelect = $("#chatModeSelect")
  if (modeSelect) {
    modeSelect.addEventListener("change", () => {
      // Mode is applied on send, no action needed here
    })
  }

  // AI left panel resizer
  initAiResizer()

  // Drop targets
  bindAiDropTargets()

  // Chat scroll
  bindAiChatScroll()

  // Mobile toggle
  var mobileToggle = $("#aiMobileToggle")
  if (mobileToggle)
    mobileToggle.addEventListener("click", () => {
      toggleAiMobilePanel()
    })
  var mobileOverlay = $("#aiMobileOverlay")
  if (mobileOverlay)
    mobileOverlay.addEventListener("click", () => {
      toggleAiMobilePanel()
    })

  // AI KB modal form
  var kbForm = $("#aiKbForm")
  if (kbForm) {
    var kbResourceType = $("#aiKbResourceType")
    var syncKbUrlField = () => {
      var urlField = $("#aiKbUrlField")
      if (urlField) urlField.hidden = kbResourceType?.value !== "link"
    }
    kbResourceType?.addEventListener("change", syncKbUrlField)
    syncKbUrlField()
    kbForm.addEventListener("submit", async (e) => {
      e.preventDefault()
      var name = ($("#aiKbName")?.value || "").trim()
      if (!name) return
    var submitButton = kbForm.querySelector('button[type="submit"]')
      if (submitButton) submitButton.disabled = true
      try {
        var knowledgeService = requireAppRuntimeService("knowledge", "createEntry")
        var resourceType = $("#aiKbResourceType")?.value || "dataset"
        var url = $("#aiKbUrl")?.value.trim() || null
        if (resourceType === "link" && !url) {
          showToast("链接资源需要填写链接地址")
          return
        }
        await knowledgeService.createEntry({
          type: resourceType === "link" ? "link" : resourceType === "file" ? "file" : "workflow_result",
          title: name,
          url,
          content: resourceType === "file" ? "" : null,
        })
        await fetchKnowledgeMappings(state.kbFilter, state.ai.leftSearch)
        window.App.components.modal.close("aiKbModal")
        renderAiWorkbench()
        showToast("知识库已创建")
      } catch (error) {
        console.warn("Knowledge entry creation failed.", error)
        showToast(error.message || "知识库创建失败")
      } finally {
        if (submitButton) submitButton.disabled = false
      }
    })
  }

  var aiUploadForm = $("#aiUploadForm")
  if (aiUploadForm) {
    aiUploadForm.addEventListener("submit", async (event) => {
      event.preventDefault()
      const fileInput = $("#aiKbFileInput")
      const collectionSelect = $("#aiUploadCollection")
      const file = fileInput?.files?.[0]
      const collectionId = collectionSelect?.value
      const status = $("#aiUploadStatus")
      if (!file || !collectionId) {
        if (status) status.textContent = "请选择文件夹和文件后再上传。"
        return
      }
      const submit = aiUploadForm.querySelector("button[type=submit]")
      if (submit) submit.disabled = true
      try {
        const knowledgeService = requireAppRuntimeService("knowledge", "uploadEntry")
        const formData = new FormData()
        formData.append("title", file.name)
        formData.append("collection_id", collectionId)
        formData.append("file", file)
        if (status) status.textContent = "正在上传到选定文件夹..."
        await knowledgeService.uploadEntry(formData)
        await fetchKnowledgeMappings(state.kbFilter, state.ai.leftSearch)
        window.App.components.modal.close("aiUploadModal")
        showToast("文件已提交到选定文件夹")
      } catch (error) {
        console.warn("AI knowledge upload failed.", error)
        if (status) status.textContent = error.message || "文件上传失败"
        showToast(error.message || "文件上传失败")
      } finally {
        if (submit) submit.disabled = false
        if (fileInput) fileInput.value = ""
      }
    })
  }

  $("#aiCreateCollectionButton")?.addEventListener("click", () => {
    void createKnowledgeCollectionFromUpload()
  })

  $("#aiDomainForm")?.addEventListener("submit", async (event) => {
    event.preventDefault()
    try {
      const service = requireAppRuntimeService("experience", "createDomain")
      await service.createDomain({
        name: $("#aiDomainName")?.value.trim(),
        description: $("#aiDomainDescription")?.value.trim() || "",
      })
      await fetchExperienceDomains()
      window.App.components.modal.close("aiDomainModal")
      showToast("领域已创建")
    } catch (error) {
      showToast(error.message || "领域创建失败")
    }
  })

  $("#aiMethodForm")?.addEventListener("submit", async (event) => {
    event.preventDefault()
    try {
      const service = requireAppRuntimeService("experience", "createMethod")
      await service.createMethod(Number($("#aiMethodDomain")?.value), {
        title: $("#aiMethodTitle")?.value.trim(),
        content: $("#aiMethodContent")?.value.trim(),
        source_type: $("#aiMethodSourceType")?.value,
        source_reference: $("#aiMethodSourceReference")?.value.trim() || null,
      })
      await fetchExperienceDomains()
      window.App.components.modal.close("aiMethodModal")
      showToast("经验方法已保存")
    } catch (error) {
      showToast(error.message || "经验方法保存失败")
    }
  })

  // AI Link modal form
  var linkForm = $("#aiLinkForm")
  if (linkForm) {
    linkForm.addEventListener("submit", (e) => {
      e.preventDefault()
      var title = ($("#aiLinkTitle")?.value || "").trim()
      var url = normalizeChatLink($("#aiLinkUrl")?.value || "")
      if (!title || !url) {
        showToast("请输入有效的 HTTP(S) 链接")
        return
      }
      state.ai.links.push({
        id: "link_" + Date.now(),
        title: title,
        url: url,
        createdAt: new Date().toISOString().slice(0, 10),
      })
      saveAiLinks()
      window.App.components.modal.close("aiLinkModal")
      showToast("链接已添加")
      renderAiWorkbench()
    })
  }

  // AI pick-kb mode: clicking kb-card actions in manage grid
  var leftBottom2 = $("#aiLeftBottom")
  if (leftBottom2) {
    leftBottom2.addEventListener("click", (e) => {
      if (!state.ai.pickKbMode) return
      var card = e.target.closest(".kb-card")
      if (!card) return
      var nameEl = card.querySelector("h3")
      var name = nameEl ? nameEl.textContent : "知识库"
      // Find the kb item
      var renameBtn = card.querySelector("[data-knowledge-rename]")
      var kbId = renameBtn ? renameBtn.dataset.kbRename : ""
      addContextChip({ kind: "kb", typeLabel: "知识库", name: name, ref: kbId })
      state.ai.pickKbMode = false
      renderAiWorkbench()
      showToast("已添加上下文: " + name)
    })
  }
}

function initAiResizer() {
  var resizer = $("#aiResizer")
  var left = $("#aiLeft")
  if (!resizer || !left) return

  var startX, startWidth
  resizer.addEventListener("pointerdown", (e) => {
    startX = e.clientX
    startWidth = left.offsetWidth
    resizer.classList.add("active")
    document.body.style.cursor = "col-resize"
    document.body.style.userSelect = "none"

    function onMove(ev) {
      var diff = ev.clientX - startX
      var newWidth = Math.max(200, Math.min(400, startWidth + diff))
      left.style.width = newWidth + "px"
      left.style.flexBasis = newWidth + "px"
      state.ai.leftWidth = newWidth
    }

    function onUp() {
      resizer.classList.remove("active")
      document.body.style.cursor = ""
      document.body.style.userSelect = ""
      document.removeEventListener("pointermove", onMove)
      document.removeEventListener("pointerup", onUp)
      saveAiPanelPrefs()
    }

    document.addEventListener("pointermove", onMove)
    document.addEventListener("pointerup", onUp)
  })
}

function openAiLinkModal() {
  var modal = $("#aiLinkModal")
  if (!modal) return
  var titleEl = $("#aiLinkTitle")
  var urlEl = $("#aiLinkUrl")
  if (titleEl) titleEl.value = ""
  if (urlEl) urlEl.value = ""
  window.App.components.modal.open("aiLinkModal")
}

// ═══════════════════════════════════════════════════════════════
// End AI Workbench
// ═══════════════════════════════════════════════════════════════

installAppShellScale()
updatePlatformTime()
window.setInterval(updatePlatformTime, 1000)
renderTasks()
updateSidebarBadge()
renderWorkbenchSchedule()
renderPortal()
syncProfileUI()
renderCalendar()
renderChatSessions()
renderChatTranscript()
updateChatSendButton()
renderAiWorkbench()
bindAiWorkbench()
bindEmbeds()
renderCustomWebsiteNavigation()
renderCustomWebsiteViews()
_initAuthReady.then(() => {
  fetchPortalBootstrap()
  fetchCockpitDecisions().catch((error) =>
    console.warn("Cockpit decision auth-ready refresh failed.", error),
  )
  fetchChatSessionsFromBackend()
  fetchKnowledgeMappings().catch((error) => {
    console.warn("Knowledge mappings unavailable.", error)
  })
})
updateMonthTitles()
setView(window.location.hash.replace("#", "") || state.activeView, {
  isInit: true,
})
bindCockpitEvents()
bindToasts()
