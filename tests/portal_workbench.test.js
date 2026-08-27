import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("portal workbench refinement contracts", async () => {
  const appSource = await readFile(new URL("../src/app.js", import.meta.url), "utf-8");
  const legacyEntrySource = await readFile(new URL("../src/legacy-entry.ts", import.meta.url), "utf-8");
  const htmlSource = await readFile(new URL("../index.html", import.meta.url), "utf-8");
  const cssSource = await readFile(new URL("../styles.css", import.meta.url), "utf-8");
  const notificationBellSource = await readFile(
    new URL("../src/components/notification-bell.js", import.meta.url),
    "utf-8",
  );

  // Service category filtering
  assert.ok(appSource.includes("_serviceCategory"), "missing _serviceCategory state");
  assert.ok(appSource.includes("bindServiceMenu"), "missing bindServiceMenu function");
  const validViewsBlock =
    appSource.match(/const validViews = new Set\(\[([\s\S]*?)\]\)/)?.[1] || "";
  assert.ok(
    validViewsBlock.includes('"service-center"'),
    "service center must be a valid tab view",
  );

  // Document assistant should not be embedded in the cockpit card
  assert.ok(
    appSource.includes("renderWorkspaceAssistant"),
    "missing renderWorkspaceAssistant function",
  );
  assert.ok(!htmlSource.includes("assistantRecentDocs"), "assistantRecentDocs should be removed");
  assert.ok(!htmlSource.includes("assistantStream"), "assistantStream should be removed");
  assert.ok(!htmlSource.includes("连接飞书文档"), "Feishu connect button should be removed");

  // GridStack CSS must be loaded by the legacy page entry that renders cockpit shortcuts.
  assert.ok(
    legacyEntrySource.includes('gridstack/dist/gridstack.min.css'),
    "legacy entry must import GridStack CSS for horizontal cockpit shortcut layout",
  );
  assert.ok(
    legacyEntrySource.includes("installAppShellScale"),
    "legacy entry must install the viewport shell scale",
  );
  assert.ok(
    /\.app-shell\s*\{[^}]*width:\s*100vw;[^}]*height:\s*100dvh;[^}]*transform:\s*none;/.test(
      cssSource,
    ),
    "app shell must use the native viewport instead of scaling the whole interface",
  );
  assert.ok(
    /\.layout\s*\{[^}]*height:\s*100%;/.test(cssSource),
    "layout height must use the app-frame content height without subtracting the topbar twice",
  );
  assert.ok(
    /\.module-sidebar\s*\{[^}]*height:\s*100%;/.test(cssSource),
    "sidebar height must fill the scaled layout",
  );
  assert.ok(
    /\.view\s*\{[^}]*width:\s*100%;[^}]*max-width:\s*none;[^}]*margin:\s*0;/.test(cssSource),
    "legacy main views must fill the available content width",
  );
  assert.ok(
    /\.page-view\s*\{[^}]*width:\s*100%;[^}]*max-width:\s*none;[^}]*margin:\s*0;/.test(cssSource),
    "React page views must fill the available content width",
  );
  assert.ok(
    /\.ai-workbench\s*\{[^}]*width:\s*100%;/.test(cssSource),
    "AI workbench must fill its main view",
  );
  assert.ok(
    /#knowledge\.active\s*\{[^}]*height:\s*100%;/.test(cssSource) &&
      /\.ai-workbench\s*\{[^}]*height:\s*100%;/.test(cssSource) &&
      !/\.ai-workbench\s*\{\s*flex-direction:\s*column;\s*height:\s*calc/.test(cssSource),
    "AI service must fill the available main content height",
  );
  assert.ok(
    /@media\s*\(max-width:\s*1200px\)[\s\S]*?\.ai-workbench\s*\{[^}]*flex-direction:\s*column;/.test(
      cssSource,
    ),
    "AI service must stack vertically when the content width is constrained",
  );
  assert.ok(
    appSource.includes("function getCockpitShortcutPosition"),
    "missing deterministic cockpit shortcut position helper",
  );
  assert.ok(
    appSource.includes("function getCockpitAddEntryPosition"),
    "missing fixed add-entry placeholder position helper",
  );
  assert.ok(
    appSource.includes("function _finishCockpitShortcutDrag"),
    "missing drag-stop reflow helper for cockpit shortcuts",
  );
  assert.ok(
    appSource.includes("dragstop"),
    "cockpit grid must reflow after dragging to keep add-entry last",
  );
  assert.ok(
    appSource.includes("getCockpitAddEntryPosition(entries.length, maxH)"),
    "add-entry placeholder must be positioned after the real entries",
  );

  // Smart decisions own a full cockpit row below the data board.
  assert.ok(
    htmlSource.indexOf('id="cockpitKpiGrid"') < htmlSource.indexOf('id="cockpit-decisions"'),
    "smart decisions must appear below the data board",
  );
  assert.ok(
    htmlSource.indexOf('id="cockpit-decisions"') < htmlSource.indexOf('class="cockpit-panels"'),
    "smart decisions must be outside and above the lower cockpit panel grid",
  );
  assert.ok(
    !htmlSource.includes('id="cockpit-scheduled-tasks"'),
    "scheduled task board must not render as a standalone cockpit card",
  );
  assert.ok(
    appSource.includes('title: "定时任务看板"'),
    "cockpit shortcuts must include a scheduled task board entry",
  );
  assert.ok(
    appSource.includes("openCockpitScheduledTaskBoard"),
    "scheduled task shortcut must open the scheduled task board modal",
  );
  assert.ok(
    !appSource.includes("演示数据：仅在 VITE_USE_MOCK=true 时展示"),
    "smart decisions must not render the mock-mode demo boundary copy",
  );
  assert.ok(
    !htmlSource.includes('id="cockpitDecisionDrawer"'),
    "smart decisions must not use a drawer for status tabs",
  );
  assert.ok(
    !htmlSource.includes('id="cockpitDecisionViewAll"'),
    "smart decisions must not expose a drawer-based view-all action",
  );
  assert.ok(
    htmlSource.includes('class="tabs cockpit-decision-filters"'),
    "smart decision status tabs must live inside the card",
  );
  assert.ok(
    appSource.includes("renderCockpitScheduledTasks"),
    "scheduled task board needs an independent renderer",
  );
  assert.ok(
    appSource.includes("COCKPIT_DECISION_PREVIEW_LIMIT = 5"),
    "cockpit smart decision preview must show 5 decisions",
  );
  assert.ok(
    appSource.includes("function fetchCockpitDecisions"),
    "smart decisions must load through a dashboard decision contract when available",
  );
  assert.ok(
    appSource.includes("function approveCockpitDecision"),
    "smart decisions must support approve actions",
  );
  assert.ok(
    appSource.includes("function rejectCockpitDecision"),
    "smart decisions must support reject actions",
  );
  assert.ok(
    appSource.includes('reason_type: "no_need"') &&
      appSource.includes('reason_type: "other"') &&
      appSource.includes('reason_type: "regenerate"'),
    "rejecting decisions must distinguish archive-only and regeneration reasons",
  );
  assert.ok(
    cssSource.includes(".cockpit-decision-preview-grid"),
    "smart decisions need a full-width preview grid style",
  );
  assert.ok(
    cssSource.includes(".cockpit-scheduled-task-list"),
    "scheduled task board needs list styles",
  );
  assert.ok(
    cssSource.includes(".modal.cockpit-scheduled-task-modal") &&
      /max-width:\s*calc\(100vw - 32px\)/.test(cssSource) &&
      /width:\s*min\(960px,\s*calc\(100vw - 32px\)\)/.test(cssSource) &&
      /max-height:\s*calc\(100vh - 32px\)/.test(cssSource) &&
      cssSource.includes("overflow-y: auto") &&
      /grid-template-columns:\s*repeat\(auto-fit,\s*minmax\(220px,\s*1fr\)\)/.test(
        cssSource,
      ),
    "scheduled task modal must expand within the viewport and scroll task results",
  );

  // Overdue workspace tasks should surface in the top-right notification bell.
  assert.ok(
    appSource.includes("function getLocalOverdueTaskNotifications"),
    "missing local overdue task notification mapper",
  );
  assert.ok(
    appSource.includes("function openOverdueTaskNotification"),
    "missing overdue task notification click handler",
  );
  assert.ok(
    appSource.includes('state.taskFilter = "overdue"'),
    "clicking an overdue notification must switch to the overdue task filter",
  );
  assert.ok(
    appSource.includes("App.components.notificationBell.setCount(getLocalOverdueTaskNotifications().length)"),
    "notification bell count must be derived from current overdue tasks",
  );
  assert.ok(
    appSource.includes("function getTaskDeadlineTime"),
    "task overdue detection must parse local deadline times before comparing",
  );
  assert.ok(
    appSource.includes("function scheduleNextTaskDeadlineRefresh"),
    "notification bell must schedule a refresh for the next local task deadline",
  );
  assert.ok(
    appSource.includes("function refreshTaskDeadlineState"),
    "task deadline refresh must recompute overdue UI state when a deadline passes",
  );
  assert.ok(
    appSource.includes("setTimeout(refreshTaskDeadlineState, delay)"),
    "deadline refresh must wake exactly when the next task becomes overdue",
  );
  assert.ok(
    /function refreshTaskDeadlineState\(\)\s*\{[\s\S]*renderLocalOverdueTaskNotifications\(\)[\s\S]*renderTasks\(\)[\s\S]*updateSidebarBadge\(\)/.test(
      appSource,
    ),
    "deadline refresh must update the bell, task list, and sidebar badge together",
  );
  assert.ok(
    !appSource.includes("task.deadline < now"),
    "task overdue detection must not compare local deadlines with UTC ISO strings",
  );
  assert.ok(
    /\.notification-dropdown\s*\{[^}]*position:\s*fixed/.test(cssSource),
    "notification dropdown must be fixed to the viewport near the top-right bell",
  );
  assert.ok(
    !/\.notification-dropdown\s*\{[^}]*top:\s*100%/.test(cssSource),
    "notification dropdown is not a child of the bell button and must not use top:100%",
  );
  assert.ok(
    notificationBellSource.includes("notification-header"),
    "notification dropdown must render a visible header for the bell panel",
  );
  assert.ok(
    appSource.includes('action_label: "查看过期待办"'),
    "overdue task notification panel must expose a clear action label",
  );
  assert.ok(
    appSource.includes("function openEventModalForDate"),
    "calendar summary needs a date-based add-event helper",
  );
  assert.ok(
    appSource.includes('addEventListener("dblclick"'),
    "calendar dates and schedule items must support double-click actions",
  );
  assert.ok(
    appSource.includes("data-calendar-date"),
    "full calendar date cells must expose a date target for double-click add",
  );
  assert.ok(
    !appSource.includes("element.onclick = () => openEventModal(Number(element.dataset.editEvent))"),
    "schedule items must not open edit modal on single click",
  );

  // AI service panel
  assert.ok(
    !appSource.includes('<div class="ai-sub-section-title">记忆库</div>') &&
      !appSource.includes("AI 会在对话中自动提取关键信息") &&
      !appSource.includes("已存入记忆库"),
    "experience methods must not display the memory library",
  );
  const aiSubMenuBlock = appSource.slice(
    appSource.indexOf("function switchAiSubMenu"),
    appSource.indexOf("function renderChatSessions"),
  );
  assert.ok(
    /if \(button\.dataset\.kbSubLink\) \{\s*if \(state\.activeView !== "knowledge"\) openTab\("knowledge"\)[\s\S]*switchAiSubMenu\(button\.dataset\.kbSubLink\)/.test(
      appSource,
    ),
    "AI service submenu switching must not reopen the knowledge view when it is already active",
  );
  assert.ok(
    aiSubMenuBlock.includes("renderAiLeftBrowser()") &&
      !aiSubMenuBlock.includes("renderChatTranscript()") &&
      !aiSubMenuBlock.includes("renderAiWorkbench()"),
    "AI service submenu switching must only refresh the left browser, not the chat transcript",
  );

  // Admin news tab
  assert.ok(htmlSource.includes('data-admin-panel="news"'), "missing admin news sub-tab");
  assert.ok(appSource.includes("fetchAdminNews"), "missing fetchAdminNews function");

  // Notice publish
  assert.ok(appSource.includes("canPublishNotices"), "missing canPublishNotices function");
  assert.ok(appSource.includes("openNoticePublishModal"), "missing openNoticePublishModal function");
  assert.ok(htmlSource.includes("noticePublishModal"), "missing noticePublishModal element");
});
