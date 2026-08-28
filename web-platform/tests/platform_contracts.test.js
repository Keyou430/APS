import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import test from "node:test";

async function readSourceFiles(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const url = new URL(entry.name, dir);
    if (entry.isDirectory()) {
      files.push(...(await readSourceFiles(new URL(`${entry.name}/`, dir))));
    } else if (/\.(js|jsx|ts|tsx)$/.test(entry.name)) {
      files.push(url);
    }
  }
  return files;
}

test("exports portal bootstrap contracts", async () => {
  const source = await readFile(new URL("../src/types/index.ts", import.meta.url), "utf8");

  for (const name of [
    "EmbedUrls",
    "PortalCatalogItem",
    "PortalCatalog",
    "PortalBootstrapResponse",
  ]) {
    assert.equal(source.includes(`export interface ${name}`), true, `${name} is missing`);
  }
});

test("cockpit layout actions call dashboard layout services", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(source, /getAppRuntimeService\("dashboard"\)/);
  assert.match(source, /\.saveLayout\(/);
  assert.match(source, /\.resetLayout\(/);
  assert.match(source, /expectedRevision/);
  assert.match(source, /status === 409/);
});

test("frontend runtime sources do not call legacy api v1 endpoints", async () => {
  const sourceFiles = await readSourceFiles(new URL("../src/", import.meta.url));
  const offenders = [];

  for (const file of sourceFiles) {
    const source = await readFile(file, "utf8");
    if (source.includes("/api/v1")) {
      offenders.push(file.pathname);
    }
  }

  assert.deepEqual(offenders, []);
});

test("frontend auth runtime does not call missing auth contract endpoints", async () => {
  const sourceFiles = await readSourceFiles(new URL("../src/", import.meta.url));
  const offenders = [];

  for (const file of sourceFiles) {
    const source = await readFile(file, "utf8");
    if (/authBaseUrl\s*\+\s*["']\/(?:register|change-password)["']/.test(source)) {
      offenders.push(file.pathname);
    }
    if (/\$\{API_BASE\}\/(?:register|change-password)/.test(source)) {
      offenders.push(file.pathname);
    }
  }

  assert.deepEqual(offenders, []);
});

test("knowledge list uses the contract runtime service without legacy fallback", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(source, /getAppRuntimeService\("knowledge"\)/);
  assert.match(source, /\.listEntries\(/);
  assert.match(source, /mapKnowledgeEntriesToLegacyCards/);
  assert.doesNotMatch(
    source,
    /const payload = await apiJson\("\/api\/v1\/knowledge\/mappings"\)/,
  );
});

test("chat sessions use the contract runtime service without legacy fallback", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(source, /getAppRuntimeService\("chat"\)/);
  assert.match(source, /\.listSessions\(/);
  assert.match(source, /session\.surface === "agent"/);
  assert.match(source, /\.getMessages\(/);
  assert.match(source, /\.createSession\(/);
  assert.match(source, /\.deleteSession\(/);
  assert.match(source, /function isBackendChatSessionId/);
  assert.match(source, /Backend history is authoritative/);
  assert.match(source, /session = await createChatSession\(\)/);
  assert.doesNotMatch(
    source,
    /const data = await apiJson\("\/api\/v1\/chat\/sessions"\)/,
  );
  assert.doesNotMatch(
    source,
    /`\/api\/v1\/chat\/sessions\/\$\{encodeURIComponent\(s\.id\)\}\/messages`/,
  );
});

test("chat send uses the contract SSE runtime service without legacy fallback", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(source, /getAppRuntimeService\("chatStream"\)/);
  assert.match(source, /\.sendMessageStream\(/);
  assert.match(source, /response\.output_text\.delta/);
  assert.match(source, /response\.completed/);
  assert.match(source, /response\.failed|upstream\.disconnected/);
  assert.match(source, /\.stopRun\(/);
  assert.match(source, /\.stopRun\(sessionId,\s*runId\s*\|\|\s*["']active["']\)/);
  assert.match(source, /activeStopPromise/);
  assert.doesNotMatch(source, /\/api\/v1\/knowledge\/chat/);
  assert.doesNotMatch(source, /\/api\/v1\/chat\/messages/);
});

test("streaming chat changes the send control into an enabled stop control", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(source, /btn\.disabled\s*=\s*!state\.isStreaming\s*&&\s*!hasText/);
  assert.match(source, /aria-label",\s*state\.isStreaming\s*\?\s*"暂停生成"\s*:\s*"发送"/);
  assert.match(source, /title",\s*state\.isStreaming\s*\?\s*"暂停生成"\s*:\s*"发送"/);
  assert.match(source, /if \(state\.isStreaming\)\s*\{[\s\S]*?stopChatStream\(\)/);
});

test("chat explains the per-user run quota instead of reporting a network error", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(source, /status === 429/);
  assert.match(source, /运行额度被未完成会话占用/);
});

test("ordinary AI chat uses the agent surface and preserves uploaded attachment content", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(source, /options\.surface === "knowledge" \? "knowledge" : "agent"/);
  assert.match(source, /surface,/);
  assert.match(source, /attachments:\s*messageAttachments/);
  assert.match(source, /payload\.content/);
  assert.doesNotMatch(source, /surface:\s*"knowledge",\s*title/);
  assert.doesNotMatch(source, /source_ids:\s*context_ids/);
});

test("AI chat sends selected link context and renders verified platform actions", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(source, /const messageLinks = chips/);
  assert.match(source, /c\.kind === "link"/);
  assert.match(source, /links:\s*messageLinks/);
  assert.match(source, /client_message_id:\s*userMsg\.id/);
  assert.match(source, /sendChatMessage\(\{ clientMessageId: previous\.id \}\)/);
  assert.match(source, /event === "platform\.action"/);
  assert.match(source, /assistantMsg\.platformAction = data/);
  assert.match(source, /platformActionHTML/);
  assert.match(source, /data-platform-action-choice="confirm"/);
  assert.match(source, /data-platform-action-choice="cancel"/);
  assert.match(source, /getAppRuntimeService\("pipeline"\)/);
  assert.match(source, /pipelineService\.createTask\(\{ \.\.\.action\.draft, confirmed: true \}\)/);
  assert.match(source, /action\.run_now/);
  assert.match(source, /pipelineService\.runTask\(task\.id\)/);
  assert.doesNotMatch(source, /links:\s*\[\]/);
});

test("dragged link context carries the real URL instead of a local id", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(source, /link_url:\s*linkUrl/);
  assert.match(source, /data-drag-ref=/);
  assert.match(source, /function resolveAiLinkRef/);
  assert.match(source, /entry\.type === "link"/);
  assert.match(source, /isStoredAiLinkEntry\(fav\)/);
  assert.match(source, /startsWith\("link_"\)/);
  assert.match(source, /function repairStoredAiLinkContext/);
  assert.match(source, /repairStoredAiLinkContext\(\)/);
  assert.match(source, /chip\.status === "error" && chip\.file/);
  assert.match(source, /ref:\s*el\.dataset\.dragRef/);
  assert.match(source, /normalizeChatLink\(c\.ref\)/);
  assert.doesNotMatch(source, /ref:\s*el\.dataset\.dragId/);
  assert.doesNotMatch(source, /data-drag-kind="kb" data-drag-id=/);
});

test("chat messages use safe markdown and stable streaming updates", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(source, /const contentHTML = renderAssistantMessageContent\(m\.content \|\| ""\)/);
  assert.match(source, /security\.renderAssistantMessage/);
  assert.match(source, /updateStreamingAssistantMessage\(assistantMsg\)/);
  assert.match(source, /Keep partial Markdown as stable plain text/);
  assert.doesNotMatch(source, /marked\.parse/);
});

test("recent AI answers surface missing live-source evidence", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");
  const evidence = await readFile(new URL("../src/app/chatEvidence.ts", import.meta.url), "utf8");

  assert.match(source, /getFreshnessNotice/);
  assert.match(source, /webSearchUsed/);
  assert.match(source, /data-testid="freshness-evidence-notice"/);
  // Only platform-validated web evidence may prove freshness.
  assert.match(evidence, /webEvidence/);
  assert.match(evidence, /webSearchFailed/);
  // Model-written URLs must not count as evidence.
  assert.doesNotMatch(evidence, /LIVE_SOURCE/);
});

test("notification bell stays local-only until a backend contract exists", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  // No backend notifications endpoint exists yet; the entry must stay
  // explicitly disabled rather than fabricating backend data.
  assert.match(source, /function notificationsContractMissing/);
  assert.match(source, /Notifications API contract missing\./);
  assert.match(source, /getLocalOverdueTaskNotifications/);
  assert.doesNotMatch(source, /\/api\/notifications/);
  assert.doesNotMatch(source, /\/api\/v1\/notifications/);
});

test("chat web evidence renders only platform-validated sources with real links", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(source, /event === "web\.search\.completed"/);
  assert.match(source, /event === "web\.search\.failed"/);
  assert.match(source, /renderWebEvidenceHTML/);
  assert.match(source, /data-testid="chat-web-sources"/);
  assert.match(source, /rel="noopener noreferrer nofollow"/);
  assert.match(source, /web_sources/);
});

test("knowledge upload and chat attachments use contract services before legacy fallback", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(source, /getAppRuntimeService\("knowledge"\)/);
  assert.match(source, /\.uploadEntry\(/);
  assert.match(source, /getAppRuntimeService\("chat"\)/);
  assert.match(source, /\.prepareAttachment\(/);
  assert.match(source, /attachments:\s*messageAttachments/);
  assert.match(source, /chips\[index\]\.attachmentContent = payload\.content/);
  assert.doesNotMatch(source, /source_ids:\s*context_ids/);
  assert.doesNotMatch(source, /\/api\/v1\/knowledge\/import/);
  assert.doesNotMatch(source, /\/api\/v1\/knowledge\/imports/);
});

test("AI workbench desktop controls remain interactive and knowledge CRUD is complete", async () => {
  const appSource = await readFile(new URL("../src/app.js", import.meta.url), "utf8");
  const overlaySource = await readFile(
    new URL("../src/app/aiMobileOverlay.ts", import.meta.url),
    "utf8",
  );
  const markup = await readFile(new URL("../index.html", import.meta.url), "utf8");

  assert.match(appSource, /isMobile: \(\) => window\.matchMedia/);
  assert.match(overlaySource, /left\.inert = isMobile && !mobilePanelOpen/);
  assert.match(appSource, /#newChatSession/);
  assert.match(appSource, /\.createSession\(/);
  assert.match(appSource, /requireAppRuntimeService\("knowledge", "createEntry"\)/);
  assert.match(appSource, /requireAppRuntimeService\("knowledge", "uploadEntry"\)/);
  assert.match(appSource, /requireAppRuntimeService\("knowledge", "archiveEntry"\)/);
  assert.match(markup, /id="aiKbUrl"/);
  assert.match(markup, /id="aiKbFileInput"/);
});

test("portal bootstrap and dashboard use contract services without legacy fallback", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(
    source,
    /requireAppRuntimeService\(\s*"enterprise",\s*"getLegacyBootstrap",?\s*\)/,
  );
  assert.match(source, /\.getLegacyBootstrap\(/);
  assert.match(source, /getAppRuntimeService\("dashboard"\)/);
  assert.match(source, /\.getDashboard\(/);
  assert.doesNotMatch(source, /\/api\/v1\/portal\/bootstrap/);
  assert.doesNotMatch(source, /\/api\/v1\/portal\/dashboard/);
});

test("login distinguishes credential failures from network failures", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(source, /Number\(e\.status\) === 401/);
  assert.match(source, /用户名或密码错误/);
  assert.match(source, /网络错误，请稍后再试/);
});

test("portal preferences fail closed without legacy fallback", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(source, /loadPortalPreferencesFromLocalCache/);
  assert.match(source, /savePortalPreferencesToLocalCache/);
  assert.doesNotMatch(source, /\/api\/v1\/portal\/preferences/);
});

test("knowledge item actions use contract services without legacy fallback", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(source, /requireAppRuntimeService\(\s*"knowledge",\s*"updateEntry",?\s*\)/);
  assert.match(source, /requireAppRuntimeService\(\s*"knowledge",\s*"archiveEntry",?\s*\)/);
  assert.match(source, /requireAppRuntimeService\(\s*"knowledge",\s*"listOperationJobs",?\s*\)/);
  assert.match(source, /requireAppRuntimeService\(\s*"knowledge",\s*"previewContent",?\s*\)/);
  assert.match(source, /requireAppRuntimeService\(\s*"knowledge",\s*"getOperationsOverview",?\s*\)/);
  assert.match(source, /\.updateEntry\(/);
  assert.match(source, /\.archiveEntry\(/);
  assert.match(source, /\.listOperationJobs\(/);
  assert.match(source, /\.previewContent\(/);
  assert.match(source, /\.getOperationsOverview\(/);
  assert.match(source, /requireAppRuntimeService\("knowledge", "createEntry"\)/);
  assert.match(source, /\.createEntry\(/);
  assert.doesNotMatch(source, /\/api\/v1\/knowledge\/mappings/);
  assert.doesNotMatch(source, /\/api\/v1\/knowledge\/datasets/);
  assert.doesNotMatch(source, /\/api\/v1\/knowledge\/sync/);
});

test("workspace tasks use work item contract services without legacy fallback", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(source, /getAppRuntimeService\("workItems"\)/);
  assert.match(source, /mapWorkItemToLegacyTask/);
  assert.match(source, /\.createWorkItem\(/);
  assert.match(source, /\.updateWorkItem\(/);
  assert.match(source, /\.updateWorkItemStatus\(/);
  assert.match(source, /\.deleteWorkItem\(/);
  assert.doesNotMatch(source, /\/api\/v1\/tasks/);
});

test("notice publishing uses enterprise announcements without legacy fallback", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(source, /requireAppRuntimeService\(\s*"enterprise",/);
  assert.match(source, /\.createPublishedAnnouncement\(/);
  assert.match(source, /content: payload\.body/);
  assert.doesNotMatch(source, /\/api\/v1\/admin\/notices/);
});

test("cockpit preserves backend decision terminal states", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(source, /changes_requested:\s*"需修改"/);
  assert.match(source, /superseded:\s*"已替代"/);
});

test("cockpit rejection tracks regeneration until a fresh decision is available", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(source, /regeneration_run_id/);
  assert.match(source, /function poll.*(?:Pipeline|pipeline).*Run|function wait.*(?:Pipeline|pipeline).*Run/);
  assert.match(source, /getRun\(/);
  assert.match(source, /status === "completed"/);
  assert.match(source, /fetchCockpitDecisions\(\)/);
  assert.match(source, /status === "failed"/);
  assert.match(source, /重新生成失败/);
});

test("cockpit approval accepts an optional comment", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(source, /data-decision-approval-comment/);
  assert.match(source, /approveDecision\(decisionId,\s*payload\)/);
});

test("failed cockpit regeneration remains retryable with a fresh intent", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(source, /data-decision-regenerate/);
  assert.match(source, /status:\s*"changes_requested"/);
  assert.match(source, /regenerationError/);
  assert.match(source, /releaseDecisionIntent/);
  assert.match(source, /const maxAttempts = 180/);
  assert.match(source, /attempt < 180/);
});

test("legacy chat scheduled-task confirmation exposes the complete editable draft", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  for (const field of [
    "title",
    "prompt",
    "schedule",
    "timezone",
    "approval_required",
    "approval_assignee_type",
    "approval_assignee_id",
    "approval_role_name",
    "approval_reminder_after_minutes",
    "approval_escalation_after_minutes",
    "approval_escalation_role_name",
  ]) {
    assert.match(source, new RegExp(`fieldAttrs\\(["']${field}["']\\)`));
  }
  assert.match(source, /data-platform-draft-field=/);
  assert.match(source, /function updatePlatformActionDraft/);
  assert.match(source, /action\.draft\[field\]\s*=/);
  assert.match(source, /createTask\(\{ \.\.\.action\.draft, confirmed: true \}\)/);
});

test("chat switching isolates active streams and keeps session-scoped state", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(source, /session\.requestGeneration/);
  assert.match(source, /session\.activeAbortController/);
  assert.match(source, /generation.*===.*session\.requestGeneration|session\.requestGeneration.*===.*generation/);
  assert.match(source, /switchChatSession[\s\S]*activeAbortController\.abort/);
  assert.match(source, /sessionScoped|session-scoped|按会话/);
});

test("admin news uses enterprise announcements without legacy fallback", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(source, /requireAppRuntimeService\(\s*"enterprise",\s*"listAnnouncements"/);
  assert.match(source, /requireAppRuntimeService\(\s*"enterprise",\s*"createPublishedAnnouncement"/);
  assert.match(source, /requireAppRuntimeService\(\s*"enterprise",\s*"updateAnnouncement"/);
  assert.match(source, /requireAppRuntimeService\(\s*"enterprise",\s*"withdrawAnnouncement"/);
  assert.match(source, /\.listAnnouncements\(/);
  assert.match(source, /\.updateAnnouncement\(/);
  assert.match(source, /\.withdrawAnnouncement\(/);
  assert.doesNotMatch(source, /\/api\/v1\/admin\/news/);
});

test("admin users use users service without legacy fallback", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(source, /requireAppRuntimeService\("users", "listUsers"\)/);
  assert.match(source, /requireAppRuntimeService\("users", "createUser"\)/);
  assert.match(source, /requireAppRuntimeService\("users", "updateUser"\)/);
  assert.match(source, /requireAppRuntimeService\("users", "deleteUser"\)/);
  assert.match(source, /requireAppRuntimeService\("users", "assignRoles"\)/);
  assert.match(source, /\.listUsers\(/);
  assert.match(source, /\.createUser\(/);
  assert.match(source, /\.updateUser\(/);
  assert.match(source, /\.deleteUser\(/);
  assert.match(source, /\.assignRoles\(/);
  assert.doesNotMatch(source, /\/api\/v1\/admin\/users(?!\/.*reset-password)/);
});

test("admin audit uses audit-events service without legacy fallback", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(source, /requireAppRuntimeService\("audit", "listAuditEvents"\)/);
  assert.match(source, /\.listAuditEvents\(/);
  assert.doesNotMatch(source, /\/api\/v1\/admin\/audit\?/);
});

test("global search uses knowledge search without legacy fallback", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(source, /getAppRuntimeService\("knowledge"\)/);
  assert.match(source, /\.search\(/);
  assert.match(source, /mapKnowledgeSearchToLegacyResults/);
  assert.doesNotMatch(source, /\/api\/v1\/search/);
});

test("calendar notifications and portal asset views are frontend-reserved without legacy network", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(source, /calendarEventContractMissing/);
  assert.match(source, /notificationsContractMissing/);
  assert.match(source, /getPortalAssetCollectionItems/);
  assert.doesNotMatch(source, /\/api\/v1\/calendar\/events/);
  assert.doesNotMatch(source, /\/api\/v1\/notifications/);
  assert.doesNotMatch(source, /\/api\/v1\/portal\/notices/);
  assert.doesNotMatch(source, /\/api\/v1\/portal\/documents/);
  assert.doesNotMatch(source, /\/api\/v1\/portal\/resources/);
  assert.doesNotMatch(source, /\/api\/v1\/portal\/services/);
  assert.doesNotMatch(source, /\/api\/v1\/portal\/news/);
});
