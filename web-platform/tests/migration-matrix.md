# Frontend Test Migration Matrix

Baseline commit: `5c29449`

Legacy test files: 71

This matrix is the deletion gate for the old frontend test baseline. A legacy test may only be removed when the target column points to an equivalent passing test and the status is no longer an unqualified `port`.

Status values:

- `keep`: still valid in the current transition branch.
- `port`: must be migrated to Vitest, React Testing Library, or Playwright.
- `merge`: behavior is merged into a broader current test.
- `replace`: old assertion is replaced by a more contract-accurate current test.
- `delete-after-equivalent`: old E2E/regression file can be deleted only after equivalent Playwright coverage passes.

| Legacy test at `5c29449` | Original coverage | Target test | Status | Deletion condition |
| --- | --- | --- | --- | --- |
| `web-platform/src/api/auth.contract.test.ts` | Auth client contract, token refresh, logout | `src/features/auth/*.test.ts`, `src/auth/*.test.ts` | `replace` | Current auth contract tests cover login -> me, refresh single-flight, logout, organization switch rollback. |
| `web-platform/src/api/chat-stream.contract.test.ts` | Chat SSE request and parser | `src/api/services/chatStream.test.ts` plus page SSE tests | `port` | Bearer SSE, terminal events, interrupted state, stop-after-abort, approval tests pass. |
| `web-platform/src/api/chat.contract.test.ts` | Chat JSON and multipart service methods | `src/api/services/chatService.test.ts`, `tests/platform_contracts.test.js` | `merge` | Contract service and page usage tests cover sessions/history/attachments/link-preview/stop/approval. |
| `web-platform/src/api/dashboardPersistence.contract.test.ts` | Dashboard layout persistence and revision | `src/api/services/dashboardService.test.ts`, `tests/platform_contracts.test.js` | `merge` | Dashboard page migration covers expectedRevision, 409 conflict UI, save/reset. |
| `web-platform/src/api/enterprise.contract.test.ts` | Enterprise portal and announcement service | `src/api/services/enterpriseService.test.ts`, `tests/platform_contracts.test.js` | `merge` | Portal page migration covers enterprise, portal, announcements, portal todos. |
| `web-platform/src/api/invitations.contract.test.ts` | Invitation service contracts | `src/api/services/invitationsService.test.ts` | `port` | Invitation list/create/revoke/regenerate/accept/guest revoke contract and page tests pass. |
| `web-platform/src/api/knowledge.contract.test.ts` | Knowledge entries, upload, grants, search | `src/api/services/knowledgeService.test.ts`, `tests/platform_contracts.test.js` | `merge` | Knowledge page covers list/upload/preview/download/grants/search/retrieve/citation without `/api/v1` fallback. |
| `web-platform/src/api/knowledgeOperations.contract.test.ts` | Knowledge operations overview/jobs/retry/cancel | `src/api/services/knowledgeService.test.ts` | `port` | Operations page tests cover overview, jobs, retry/cancel, permissions and errors. |
| `web-platform/src/api/memory.contract.test.ts` | Memory service contract | `src/api/services/memoryService.test.ts` | `merge` | Memory page migration covers list/create/update/delete and error states. |
| `web-platform/src/api/organizationStructure.contract.test.ts` | Organization structure revision mutations | `src/api/services/organizationService.test.ts` | `port` | Organization page tests cover units, positions, placements and 409 rollback. |
| `web-platform/src/api/services/services.test.ts` | Service registry exports | `src/app/appRuntime.test.ts`, service tests | `merge` | Runtime exposes every canonical service used by React routes. |
| `web-platform/src/api/skills.contract.test.ts` | Skills service, hub, generate | `src/api/services/skillsService.test.ts` | `merge` | Skills page migration labels hub/generate mock boundary and covers CRUD. |
| `web-platform/src/api/workItems.contract.test.ts` | Work item service and status events | `src/api/services/workItemsService.test.ts`, `tests/platform_contracts.test.js` | `merge` | Work item page covers state transitions, events and conflict/error states. |
| `web-platform/src/components/AppLayout.organization.test.tsx` | Layout organization switch behavior | `src/app/App.test.tsx`, future layout tests | `port` | React app shell owns organization switch controls and cache invalidation tests pass. |
| `web-platform/src/components/common/common-components.test.tsx` | Shared component rendering states | `src/toolchain-smoke.test.tsx`, future common component tests | `port` | React common components cover loading, empty, error, forbidden, conflict, success. |
| `web-platform/src/components/dashboard/DashboardGrid.test.tsx` | Dashboard grid rendering and drag contract | Future dashboard RTL tests | `port` | Dashboard grid React slice passes save/reset/revision tests without legacy DOM. |
| `web-platform/src/components/dashboard/dashboard.test.tsx` | Dashboard widgets and toolbar | Future dashboard RTL tests | `port` | Dashboard page covers widget registry, loading, empty, error, 409. |
| `web-platform/src/components/knowledge/AIPanel.test.tsx` | Knowledge AI assistant panel | Future chat/knowledge RTL tests | `port` | Chat/knowledge panel covers streaming, approval, context and error states. |
| `web-platform/src/components/knowledge/CitationList.test.tsx` | Citation list rendering | Future knowledge citation tests | `port` | Citation resolve UI covers authorized, 403, 404 and missing citation states. |
| `web-platform/src/components/knowledge/KnowledgeAttachmentControl.test.ts` | Chat attachment client behavior | Future chat attachment tests | `port` | Attachment tests cover file limit, content type, upload error mapping. |
| `web-platform/src/components/knowledge/KnowledgeDetailDrawer.test.tsx` | Knowledge detail drawer | Future knowledge detail tests | `port` | Detail drawer covers preview/download/grants/archive/restore/purge. |
| `web-platform/src/components/knowledge/KnowledgeNavigator.test.tsx` | Knowledge navigation and submodules | Future knowledge page tests | `port` | React route covers knowledge subroutes and permission-gated tabs. |
| `web-platform/src/components/knowledge/KnowledgeOperationsView.test.tsx` | Knowledge operations UI | Future operations tests | `port` | Overview/jobs/retry/cancel UI and permissions pass. |
| `web-platform/src/components/knowledge/KnowledgeScopeControl.test.tsx` | Chat knowledge scope selector | Future chat session tests | `port` | Knowledge-scope update and max source behavior pass. |
| `web-platform/src/components/knowledge/chatAttachmentUtils.test.ts` | Attachment utility mapping | Future attachment utility tests | `replace` | New mapper validates contract file limits and server error codes. |
| `web-platform/src/components/platform/PlatformPageLayout.test.tsx` | Platform page layout | Future route/layout tests | `port` | React route shell and page layout tests cover heading, nav and empty states. |
| `web-platform/src/config/brand.test.ts` | Brand config | Future app shell tests | `merge` | App shell renders the approved product name without fabricated labels. |
| `web-platform/src/config/theme.test.ts` | Theme config | Future visual regression or RTL tests | `port` | Existing confirmed CSS remains unchanged and theme toggle scope is tested. |
| `web-platform/src/features/assistant/AssistantView.test.tsx` | Assistant page | Future assistant/chat tests | `port` | Assistant route covers loading/error/stream states and no token-in-URL. |
| `web-platform/src/hooks/__tests__/useApprovalFlow.test.tsx` | Approval flow hook | Future chat approval tests | `port` | Approval once/deny request and response behavior passes. |
| `web-platform/src/hooks/__tests__/useDashboardData.persistence.test.tsx` | Dashboard data persistence hook | Future dashboard hook tests | `port` | Dashboard cache key includes organization and invalidates on mutation. |
| `web-platform/src/hooks/__tests__/useKnowledgeSources.test.tsx` | Knowledge source hook | Future knowledge hook tests | `port` | Knowledge source cache, loading and errors pass. |
| `web-platform/src/hooks/__tests__/useKnowledgeSubmodules.test.tsx` | Knowledge submodule hook | Future knowledge route tests | `port` | Knowledge subroute state and permissions pass. |
| `web-platform/src/hooks/__tests__/useKnowledgeUpload.test.tsx` | Knowledge upload hook | Future upload tests | `port` | Upload validates type/size and maps 413/422 errors. |
| `web-platform/src/hooks/useChatAttachmentUpload.test.ts` | Chat attachment upload hook | Future chat attachment tests | `port` | Attachment upload uses `/api/chat/attachments` and fail-closed mocks. |
| `web-platform/src/mock/fixtures/organizationDirectory.test.ts` | Organization mock fixtures | Future mock fixture tests | `port` | Mock mode keeps organization data in adapter and blocks real requests. |
| `web-platform/src/mock/knowledgeExtended.test.ts` | Extended knowledge mock data | Future mock adapter tests | `replace` | New mock adapter data is deterministic and never used in real mode. |
| `web-platform/src/mock/mockServices.test.ts` | Mock service handlers | `src/api/mockMode.test.ts` | `merge` | Fail-closed network guard covers non Auth/Chat real requests. |
| `web-platform/src/pages/AssistantPage.test.tsx` | Assistant page route | Future assistant route tests | `port` | React route renders assistant and handles auth/permission states. |
| `web-platform/src/pages/CalendarPage.test.tsx` | Calendar page | Future missing-interface issue or presentation tests | `port` | Calendar has confirmed backend operation or is explicitly presentation-only. |
| `web-platform/src/pages/InvitationAcceptPage.test.tsx` | Invitation accept security | Future invitation tests | `port` | Token read from fragment only and not logged/query persisted. |
| `web-platform/src/pages/KnowledgePage.test.tsx` | Knowledge page | Future knowledge page tests | `port` | Knowledge React page fully replaces legacy list/search/upload/detail. |
| `web-platform/src/pages/LoginPage.test.tsx` | Login page | Future auth page tests | `port` | Login -> token -> me -> sessionStorage and errors pass. |
| `web-platform/src/pages/OrganizationMembersPage.test.tsx` | Organization members/users | Future users page tests | `port` | Users CRUD and role assignment UI use `/api/users`. |
| `web-platform/src/pages/OrganizationStructurePage.test.tsx` | Organization structure page | Future organization page tests | `port` | Units/positions/placements revision UI passes. |
| `web-platform/src/pages/PortalPage.test.tsx` | Portal page | Future portal page tests | `port` | Portal uses `/enterprise/portal` and portal todo/announcement mutations. |
| `web-platform/src/router/organization.contract.test.tsx` | Router organization boundaries | Future route contract tests | `port` | Route guard and organization-scoped cache isolation pass. |
| `web-platform/src/shared/types/new-types.test.ts` | Shared DTO types | Future type/mapper tests | `replace` | DTO/ViewModel mapper tests cover explicit field conversions. |
| `web-platform/src/shared/types/types.test.ts` | Legacy shared type exports | Future type barrel tests | `merge` | Shared type exports match canonical services. |
| `web-platform/src/stores/__tests__/assistantStore.test.ts` | Assistant store | Future chat/assistant store tests | `port` | Store is removed or covered by route-local/server cache tests. |
| `web-platform/src/stores/__tests__/knowledgeStore.test.ts` | Knowledge store | Future knowledge cache tests | `port` | Store is removed or covered by organization-scoped cache tests. |
| `web-platform/src/stores/__tests__/stores.test.ts` | Store barrels | Future app store tests | `replace` | Auth/UI stores plus request cache replace old global business stores. |
| `web-platform/tests/assistant-real-api.spec.ts` | Assistant real API E2E | Future Playwright real API suite | `delete-after-equivalent` | Real API assistant flow passes against confirmed environment. |
| `web-platform/tests/frontend-refactor-calendar.spec.ts` | Calendar E2E | Future calendar/presentation Playwright suite | `delete-after-equivalent` | Calendar backend decision is recorded and matching E2E passes. |
| `web-platform/tests/frontend-refactor-cleanup.spec.ts` | Cleanup regression | Future replacement acceptance suite | `delete-after-equivalent` | Legacy code cleanup and no stale routes are verified. |
| `web-platform/tests/frontend-refactor-dashboard.spec.ts` | Dashboard E2E | Future dashboard Playwright suite | `delete-after-equivalent` | Dashboard save/reset/409 and responsive screenshots pass. |
| `web-platform/tests/frontend-refactor-knowledge.spec.ts` | Knowledge E2E | Future knowledge Playwright suite | `delete-after-equivalent` | Knowledge full path list/upload/preview/download/grant/citation passes. |
| `web-platform/tests/frontend-refactor-platform.spec.ts` | Platform integrations E2E | Future platform route tests | `delete-after-equivalent` | Feishu/Dingtalk/presentation boundaries are confirmed and tested. |
| `web-platform/tests/frontend-refactor-portal.spec.ts` | Portal E2E | Future portal Playwright suite | `delete-after-equivalent` | Portal, announcements and todos pass desktop and 390px screenshots. |
| `web-platform/tests/frontend-refactor-smoke.spec.ts` | Refactor smoke | `tests/e2e/production-artifact.spec.ts` | `merge` | Production artifact smoke plus React shell smoke pass. |
| `web-platform/tests/frontend-refactor-task5.spec.ts` | Task 5 acceptance | Future acceptance Playwright suite | `delete-after-equivalent` | Matching acceptance scope is covered by current feature tests. |
| `web-platform/tests/frontend-refactor-task6.spec.ts` | Task 6 acceptance | Future acceptance Playwright suite | `delete-after-equivalent` | Matching acceptance scope is covered by current feature tests. |
| `web-platform/tests/phase-b-guest-invitations.spec.ts` | Guest invitation E2E | Future invitation Playwright suite | `delete-after-equivalent` | Guest accept/revoke and forbidden paths pass. |
| `web-platform/tests/phase-b-knowledge-ai.spec.ts` | Knowledge AI E2E | Future chat/knowledge Playwright suite | `delete-after-equivalent` | Chat + knowledge context + citation behavior passes. |
| `web-platform/tests/phase-b-knowledge-operations.spec.ts` | Knowledge operations E2E | Future knowledge operations Playwright suite | `delete-after-equivalent` | Jobs overview/retry/cancel E2E passes. |
| `web-platform/tests/phase-b-knowledge-resources.spec.ts` | Knowledge resources E2E | Future knowledge Playwright suite | `delete-after-equivalent` | Upload/download/share/archive/purge E2E passes. |
| `web-platform/tests/phase-b-live-test-deployment.spec.ts` | Live deployment smoke | Future real API smoke suite | `delete-after-equivalent` | Real API deployment smoke passes in approved environment. |
| `web-platform/tests/task-33-accessibility.spec.ts` | Accessibility regression | Future accessibility Playwright suite | `delete-after-equivalent` | Keyboard, focus, landmarks, contrast and reduced motion pass. |
| `web-platform/tests/task-34-theme-consistency.spec.ts` | Theme visual consistency | Future visual/style tests | `delete-after-equivalent` | Existing approved style is unchanged across required viewports. |
| `web-platform/tests/task-f15-errors.spec.ts` | Error-state E2E | Future error-state Playwright suite | `delete-after-equivalent` | 400/401/403/404/409/413/422/429/5xx UI states pass. |
| `web-platform/tests/ui-layout-regressions.spec.ts` | Layout regression screenshots | Future responsive Playwright suite | `delete-after-equivalent` | 320/390/414/768/1280/1440 screenshots pass without overflow. |
