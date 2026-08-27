# Chat Acceptance Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the confirmed Chat contract, authorization, ID mapping, dependency, and regression-test gaps from the full project review.

**Architecture:** Add a narrowly scoped PATCH operation beside the existing owned-session mutations. Keep authorization server-side and use explicit DTO mapping in React so API integer IDs remain integer-backed path values. Preserve the legacy knowledge operations renderer because it is still wired to live operation-job controls.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, React, TypeScript, Vitest, pytest.

---

### Task 1: Session title update contract

**Files:**
- Modify: `backend/app/schemas/chat.py`
- Modify: `backend/app/routers/chat.py`
- Test: `backend/tests/test_api.py`

- [x] Add tests for owned title update, validation, and cross-user isolation.
- [x] Add `ChatSessionUpdate` and PATCH route using `owned_session(..., for_update=True)`.
- [x] Run the focused API tests.

### Task 2: React Chat API mapping and surface contract

**Files:**
- Modify: `web-platform/src/pages/ChatPage.tsx`
- Test: `web-platform/src/pages/ChatPage.test.tsx`

- [x] Add tests using numeric API session IDs and verify agent surface list/create requests.
- [x] Map numeric IDs to stable string path values without fallback substitution.
- [x] Pass `surface: "agent"` when listing and creating Chat sessions.
- [x] Run the focused Vitest file.

### Task 3: Runtime dependency declaration

**Files:**
- Modify: `backend/requirements.txt`

- [x] Add the `tzdata` runtime dependency required by `zoneinfo` on minimal images.
- [x] Run scheduler tests and dependency-sensitive validation.

### Task 4: Full verification and acceptance report

**Files:**
- Create: `docs/full-code-review-report-2026-08-22.md`

- [x] Run frontend contract tests, Vitest, lint, and build.
- [x] Run backend focused tests and full pytest with an isolated temporary directory.
- [x] Record exact pass/fail counts and remaining environmental limitations.
- [ ] Review diff, commit implementation and report, and push the current branch.
