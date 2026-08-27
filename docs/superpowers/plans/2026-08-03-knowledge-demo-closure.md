# Knowledge Demo Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the AI and knowledge-library demonstration reliably produce a non-empty grounded answer and present both chat and knowledge details as dense enterprise workspaces.

**Architecture:** Preserve the existing organization, session-scope, retrieval, and citation boundaries. Tighten the Hermes terminal-message contract, derive refresh-safe knowledge status without a migration, then render those states through the existing Zustand/React surfaces. Deploy through the existing Hermes Compose override and verify fixed run/message association plus real Browser interaction.

**Tech Stack:** FastAPI, SQLAlchemy async, pytest, React 19, TypeScript, Zustand, Arco Design, Vitest, CSS Modules, Docker Compose, in-app Browser.

---

## File Map

- `backend/app/services/hermes_client.py`: validate terminal output and stable assistant-message association.
- `backend/app/routers/chat.py`: own terminal status semantics, context event order, and current unavailable-source derivation.
- `backend/app/schemas/chat.py`: expose the derived unavailable-source count in history.
- `backend/tests/test_hermes_boundary.py`: terminal association failure contracts.
- `backend/tests/test_chat_knowledge_context.py`: stream lifecycle, event order, history, and failure contracts.
- `web-platform/src/shared/types/chat.ts`: validate history fields used by the UI.
- `web-platform/src/stores/assistantStore.ts`: reconstruct knowledge context after refresh.
- `web-platform/src/stores/__tests__/assistantStore.test.ts`: store state reconstruction and failure behavior.
- `web-platform/src/features/assistant/AssistantView.tsx`: enterprise conversation hierarchy and failed-answer rendering.
- `web-platform/src/features/assistant/AssistantView.module.css`: responsive chat workspace styling.
- `web-platform/src/features/assistant/AssistantView.test.tsx`: status strip and answer-state rendering.
- `web-platform/src/components/knowledge/KnowledgeDetailDrawer.tsx`: structured resource summary and detail states.
- `web-platform/src/components/knowledge/KnowledgeDetailDrawer.module.css`: desktop/mobile detail workspace styling.
- `web-platform/src/components/knowledge/KnowledgeDetailDrawer.test.tsx`: detail metadata and permission-bound UI coverage.

### Task 1: Enforce Non-Empty Hermes Answers

**Files:**
- Modify: `backend/app/services/hermes_client.py`
- Modify: `backend/app/routers/chat.py`
- Test: `backend/tests/test_hermes_boundary.py`
- Test: `backend/tests/test_chat_knowledge_context.py`

- [x] **Step 1: Write failing terminal-contract tests**

Add cases that pass `output: ""`, whitespace output, and a whitespace-only assistant message to `associate_terminal_message` and assert `HermesUpstreamError`. Add an async stream lifecycle test whose provider returns a completed event with blank output and blank history message, then assert the persisted `ChatTurn.status == "failed"` and `assistant_message_id is None`.

```python
@pytest.mark.parametrize("output", ["", "   "])
def test_terminal_association_rejects_blank_output(output):
    with pytest.raises(HermesUpstreamError, match="non-empty terminal output"):
        associate_terminal_message(
            before_messages=[],
            history_reads=[[{
                "id": "assistant-empty",
                "role": "assistant",
                "content": output,
            }]] * 3,
            streamed_events=[
                "event: response.completed\n"
                f"data: {json.dumps({'event': 'run.completed', 'output': output})}\n\n"
            ],
        )
```

- [x] **Step 2: Run the focused backend tests and verify RED**

Run: `cd backend && pytest tests/test_hermes_boundary.py tests/test_chat_knowledge_context.py -q`

Expected: the new blank-output assertions fail because empty strings currently associate and the lifecycle stores `association_unavailable` or `completed`.

- [x] **Step 3: Implement the minimal terminal and lifecycle rules**

In `associate_terminal_message`, require `terminal_output.strip()` and require the matched message content to be a non-empty string. In `stream_session_run`, retain `interrupted` when no terminal event is observed, associate only an observed completed event, and fold association failures into `failed`.

```python
terminal_output = terminal_events[0]["output"]
if not terminal_output.strip():
    raise HermesUpstreamError("Hermes run did not expose non-empty terminal output")

matches = [
    message
    for message in history_reads[-1]
    if str(message.get("id")) not in before_ids
    and message.get("role") == "assistant"
    and isinstance(message.get("content"), str)
    and message["content"].strip()
    and message["content"] == terminal_output
]
```

```python
final_status = observed_terminal_status or "interrupted"
if final_status == "completed" and turn_id is not None:
    try:
        assistant_message_id = associate_terminal_message(...)
    except (AttributeError, HermesUpstreamError):
        final_status = "failed"
```

- [x] **Step 4: Run focused tests and full backend regression**

Run: `cd backend && pytest tests/test_hermes_boundary.py tests/test_chat_knowledge_context.py -q`

Run: `cd backend && pytest -q`

Expected: all tests pass; blank output never leaves a completed knowledge turn.

- [x] **Step 5: Check off Task 1 and commit**

```powershell
git add backend/app/services/hermes_client.py backend/app/routers/chat.py backend/tests/test_hermes_boundary.py backend/tests/test_chat_knowledge_context.py docs/superpowers/plans/2026-08-03-knowledge-demo-closure.md
git commit -m "fix(chat): reject empty Hermes answers"
git push origin codex/hermes-platform-integration
```

### Task 2: Make Knowledge Context Ordered and Refresh-Safe

**Files:**
- Modify: `backend/app/routers/chat.py`
- Modify: `backend/app/schemas/chat.py`
- Test: `backend/tests/test_chat_knowledge_context.py`

- [x] **Step 1: Write failing event-order and history-count tests**

Assert `knowledge.context` precedes the first upstream event even when the provider emits `response.completed` without `run.created`. For a selected session, make one selected entry unavailable to the current membership and assert history includes `rejected_source_count: 1`; assert all-visible and none scopes return zero.

```python
assert streamed.text.index("event: knowledge.context") < streamed.text.index(
    "event: response.completed"
)
assert history.json()["items"][0]["rejected_source_count"] == 1
```

- [x] **Step 2: Run the focused tests and verify RED**

Run: `cd backend && pytest tests/test_chat_knowledge_context.py -q`

Expected: event ordering depends on `run.created`, and history has no rejected-source field.

- [x] **Step 3: Emit context first and derive current unavailable sources**

Yield `knowledge_context_event` immediately before consuming/yielding the first upstream event. In `get_messages`, for `selected` scope, compare the session's selected ids with ids satisfying the current authorization repository and attach the difference to each associated assistant turn. Add the nullable integer field to `ChatMessage`.

```python
if knowledge_context_event is not None:
    yield knowledge_context_event
    context_emitted = True

current_rejected_source_count = 0
if session.surface == "knowledge" and session.knowledge_scope == "selected":
    selected_ids = set((await db.scalars(
        select(ChatSessionKnowledgeSource.knowledge_entry_id).where(
            ChatSessionKnowledgeSource.chat_session_id == session.id
        )
    )).all())
    visible_ids = set((await db.scalars(
        select(KnowledgeEntry.id).where(
            KnowledgeEntry.id.in_(selected_ids),
            *_authorization_repository(db, context).visible_predicate(),
        )
    )).all()) if selected_ids else set()
    current_rejected_source_count = len(selected_ids - visible_ids)
```

- [x] **Step 4: Run focused tests and full backend regression**

Run: `cd backend && pytest tests/test_chat_knowledge_context.py -q`

Run: `cd backend && pytest -q`

Expected: context is always first, history exposes current authorization-derived counts, and no migration is generated.

- [x] **Step 5: Check off Task 2 and commit**

```powershell
git add backend/app/routers/chat.py backend/app/schemas/chat.py backend/tests/test_chat_knowledge_context.py docs/superpowers/plans/2026-08-03-knowledge-demo-closure.md
git commit -m "fix(knowledge): restore chat context after refresh"
git push origin codex/hermes-platform-integration
```

### Task 3: Reconstruct Knowledge Product State in the Web Store

**Files:**
- Modify: `web-platform/src/shared/types/chat.ts`
- Modify: `web-platform/src/stores/assistantStore.ts`
- Test: `web-platform/src/stores/__tests__/assistantStore.test.ts`

- [x] **Step 1: Write failing store tests**

Add history containing a completed answer with citations and `rejected_source_count`, then assert `loadSessions('knowledge')` reconstructs ready context. Add failed and interrupted history cases and assert the context retains the turn status for UI rendering.

```typescript
expect(useAssistantStore.getState().knowledgeContext).toMatchObject({
  turnId: 44,
  mode: 'hybrid',
  rejectedSourceCount: 1,
  turnStatus: 'completed',
})
```

- [x] **Step 2: Run the store test and verify RED**

Run: `cd web-platform && npm exec vitest -- run src/stores/__tests__/assistantStore.test.ts`

Expected: schema/context lacks `rejected_source_count` and `turnStatus`.

- [x] **Step 3: Extend types and context reconstruction**

Add `rejected_source_count` to `ChatMessageSchema`, add `turnStatus` to `KnowledgeContextState`, and use the server value rather than hard-coding zero.

```typescript
rejected_source_count: z.number().int().nonnegative().nullable().optional(),
```

```typescript
return {
  turnId: message.turn_id,
  mode: message.retrieval_mode,
  rejectedSourceCount: message.rejected_source_count ?? 0,
  citations: message.citations ?? [],
  turnStatus: message.turn_status ?? null,
}
```

- [x] **Step 4: Run store tests and full web regression**

Run: `cd web-platform && npm exec vitest -- run src/stores/__tests__/assistantStore.test.ts`

Run: `cd web-platform && npm exec vitest -- run`

Expected: all web tests pass.

- [x] **Step 5: Check off Task 3 and commit**

```powershell
git add web-platform/src/shared/types/chat.ts web-platform/src/stores/assistantStore.ts web-platform/src/stores/__tests__/assistantStore.test.ts docs/superpowers/plans/2026-08-03-knowledge-demo-closure.md
git commit -m "fix(web): restore knowledge turn state"
git push origin codex/hermes-platform-integration
```

### Task 4: Build the Enterprise Conversation Workspace

**Files:**
- Modify: `web-platform/src/features/assistant/AssistantView.tsx`
- Modify: `web-platform/src/features/assistant/AssistantView.module.css`
- Test: `web-platform/src/features/assistant/AssistantView.test.tsx`

- [x] **Step 1: Write failing conversation UI tests**

Render completed, streaming, and failed knowledge turns. Assert the header/scope grouping, retrieval status text, citation section, and explicit failure panel. Preserve guest hiding, mobile session controls, and current ARIA labels.

```typescript
expect(document.body.textContent).toContain('已检索 1 个来源')
expect(document.body.querySelector('[data-answer-state="failed"]')?.textContent)
  .toContain('回答生成失败')
expect(document.body.querySelector('[aria-label="引用来源"]')).not.toBeNull()
```

- [x] **Step 2: Run the component test and verify RED**

Run: `cd web-platform && npm exec vitest -- run src/features/assistant/AssistantView.test.tsx`

Expected: status strip, answer-state markers, and structured citation region do not exist.

- [x] **Step 3: Implement message states and workbench hierarchy**

Render a compact knowledge status strip from active request state and reconstructed context. For assistant messages with `failed` or `interrupted`, render a failure panel instead of Markdown; retain stopped/cancelled wording. Group citation UI under an `aria-label="引用来源"` section and restructure header/composer without changing service calls.

```tsx
const failedTurn = message.turn_status === 'failed' || message.turn_status === 'interrupted'

{failedTurn ? (
  <div className={styles.answerFailure} data-answer-state="failed" role="status">
    <strong>回答生成失败</strong>
    <span>知识检索已完成，但 AI 未返回可用回答。请重试。</span>
  </div>
) : (
  <ReactMarkdown>{message.content}</ReactMarkdown>
)}
```

- [x] **Step 4: Apply dense responsive CSS**

Use stable grid/flex dimensions, restrained neutral surfaces, 8px-or-less radii, readable answer width, non-overlapping mobile header/actions, and a fixed composer boundary. Do not add decorative gradients or nested cards.

- [x] **Step 5: Run component, full web, lint, and build checks**

Run: `cd web-platform && npm exec vitest -- run src/features/assistant/AssistantView.test.tsx`

Run: `cd web-platform && npm exec vitest -- run && npm run lint && npm run build`

Expected: all checks pass and no text overflows at mobile widths.

- [x] **Step 6: Check off Task 4 and commit**

```powershell
git add web-platform/src/features/assistant/AssistantView.tsx web-platform/src/features/assistant/AssistantView.module.css web-platform/src/features/assistant/AssistantView.test.tsx docs/superpowers/plans/2026-08-03-knowledge-demo-closure.md
git commit -m "feat(web): refine knowledge conversation workspace"
git push origin codex/hermes-platform-integration
```

### Task 5: Build the Knowledge Detail Workspace

**Files:**
- Modify: `web-platform/src/components/knowledge/KnowledgeDetailDrawer.tsx`
- Modify: `web-platform/src/components/knowledge/KnowledgeDetailDrawer.module.css`
- Test: `web-platform/src/components/knowledge/KnowledgeDetailDrawer.test.tsx`

- [x] **Step 1: Write failing detail hierarchy tests**

Assert the summary exposes type, visibility, access source, update time, and description; assert content preview, permission-restricted access, loading, and audit behavior remain intact.

```typescript
expect(document.body.querySelector('[aria-label="知识资源摘要"]')?.textContent)
  .toContain('组织可见')
expect(document.body.textContent).toContain('授权获得')
expect(document.body.textContent).toContain('更新时间')
```

- [x] **Step 2: Run the drawer test and verify RED**

Run: `cd web-platform && npm exec vitest -- run src/components/knowledge/KnowledgeDetailDrawer.test.tsx`

Expected: resource metadata and structured summary region are missing.

- [x] **Step 3: Implement the structured detail drawer**

Widen the desktop drawer to 680px, add a semantic summary header using existing `type`, `visibility`, `accessSource`, `updatedAt`, and `summary` fields, retain four permission-gated tabs, and give preview/access/activity consistent empty and error regions.

```tsx
<section className={styles.resourceSummary} aria-label="知识资源摘要">
  <div className={styles.summaryTags}>...</div>
  <h2>{source.title}</h2>
  <p>{source.summary || '暂无摘要'}</p>
  <dl className={styles.metadataGrid}>...</dl>
</section>
```

- [x] **Step 4: Run drawer, full web, lint, and build checks**

Run: `cd web-platform && npm exec vitest -- run src/components/knowledge/KnowledgeDetailDrawer.test.tsx`

Run: `cd web-platform && npm exec vitest -- run && npm run lint && npm run build`

Expected: all checks pass; the drawer remains full-screen at 520px and below.

- [x] **Step 5: Check off Task 5 and commit**

```powershell
git add web-platform/src/components/knowledge/KnowledgeDetailDrawer.tsx web-platform/src/components/knowledge/KnowledgeDetailDrawer.module.css web-platform/src/components/knowledge/KnowledgeDetailDrawer.test.tsx docs/superpowers/plans/2026-08-03-knowledge-demo-closure.md
git commit -m "feat(web): refine knowledge detail workspace"
git push origin codex/hermes-platform-integration
```

### Task 6: Complete Regression, Deployment, and Live Demo Acceptance

**Files:**
- Modify: `docs/superpowers/plans/2026-08-03-knowledge-demo-closure.md`
- Create: `docs/superpowers/checkpoints/2026-08-03-ai-knowledge-demo-acceptance.md`

- [x] **Step 1: Run clean local verification**

Run: `cd backend && pytest -q`

Run: `cd web-platform && npm exec vitest -- run && npm run lint && npm run build`

Run: `git diff --check && git status --short`

Expected: all suites pass; only protected `.superpowers/` may remain untracked.

- [x] **Step 2: Verify remote ancestry and deploy with real Hermes override**

On `192.168.3.131`, verify the remote branch contains every task commit, fast-forward `/opt/agent-platform-system`, and run:

```bash
cd /opt/agent-platform-system/deploy
sh scripts/up.sh --with-hermes
docker compose --env-file .env -f compose.yaml -f compose.hermes.yaml ps
```

Expected: `api`, `web`, `rag-worker`, `hermes`, `hermes-knowledge`, and `db` are healthy. Do not print environment values or perform a production migration.

- [x] **Step 3: Run the fixed message-id/run live contract acceptance**

Create a disposable internal test user and authorized knowledge source through public APIs. Ask a deterministic question, capture that request's run id and persisted `ChatTurn.assistant_message_id`, retrieve that exact Hermes session history, and assert the associated message id is stable across three reads with non-empty content and recorded citations. Never select the latest message heuristically.

Expected: the exact turn is `completed`, has one stable non-empty assistant message, and cites only its authorized source. Delete the disposable user/source/session afterwards.

- [x] **Step 4: Verify AI and knowledge flows in the in-app Browser**

Use the same authenticated Browser session to verify the general AI workspace and knowledge workspace, knowledge upload/readiness, selected scope, a grounded non-empty answer, citation resolution, detail tabs, and widths 390/768/1024/1440. Inspect console and request failures. Preserve one harmless `deliverable` tab; never call `finalize({ keep: [] })` or close the last tab.

Expected: both demonstrations complete without blank answers, 404s, overlaps, or credential exposure.

- [x] **Step 5: Record secret-free acceptance evidence and commit**

Write `docs/superpowers/checkpoints/2026-08-03-ai-knowledge-demo-acceptance.md` with commit ids, test counts, container health, exact non-secret run/message association evidence, responsive Browser results, and remaining gates. Exclude runtime reports, `.secret/`, `.superpowers/`, uploaded private content, tokens, keys, and credentials.

```powershell
git add docs/superpowers/checkpoints/2026-08-03-ai-knowledge-demo-acceptance.md docs/superpowers/plans/2026-08-03-knowledge-demo-closure.md
git commit -m "docs: record AI knowledge demo acceptance"
git push origin codex/hermes-platform-integration
```

- [x] **Step 6: Verify PR head and mark the goal complete**

Run: `git status --short && git log -1 --oneline && git ls-remote origin refs/heads/codex/hermes-platform-integration`

Expected: local and remote heads match; `.superpowers/` is the only allowed untracked path; the Draft PR contains all commits.
