# Feishu Base Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow AI chat to read an explicitly authorized Feishu Base table link through platform-owned application credentials.

**Architecture:** Extend the existing server-owned Feishu reader with a structured resource reference for Docx, Wiki, and Base links. Base authorization is organization- and table-specific, and Base records are fetched through the Bitable OpenAPI with bounded pagination before being injected into transient chat context.

**Tech Stack:** Python 3.12, FastAPI, Pydantic Settings, httpx, pytest, Docker Compose.

---

### Task 1: Parse And Authorize Base Links

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/services/feishu_resource_reader.py`
- Test: `backend/tests/test_feishu_resource_reader.py`

- [ ] **Step 1: Write failing parser and policy tests**

Add tests that parse `/base/{app_token}?table={table_id}&view={view_id}` into a typed Base reference and require all of `organization_id`, `app_token`, and `table_id` to match an explicit `app_token:table_id` allowlist entry.

- [ ] **Step 2: Verify the tests fail for missing Base support**

Run: `pytest tests/test_feishu_resource_reader.py -k "base_link or base_access" -v`

Expected: FAIL because Base references and grants are not implemented.

- [ ] **Step 3: Implement the typed reference and strict Base grant**

Add `feishu_read_allowed_base_tables` to Settings, parse comma-separated `app_token:table_id` grants, expose a resource-reference parser, and keep existing document/chat authorization behavior unchanged.

- [ ] **Step 4: Verify parser and policy tests pass**

Run: `pytest tests/test_feishu_resource_reader.py -k "base_link or base_access" -v`

Expected: PASS.

### Task 2: Read Base Records With Bounded Pagination

**Files:**
- Modify: `backend/app/services/feishu_resource_reader.py`
- Test: `backend/tests/test_feishu_resource_reader.py`

- [ ] **Step 1: Write a failing Base OpenAPI test**

Use `httpx.MockTransport` to assert requests target `/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records`, forward `view_id`, follow one `page_token`, and format returned field values as deterministic readable text.

- [ ] **Step 2: Verify the test fails at `unsupported_feishu_link`**

Run: `pytest tests/test_feishu_resource_reader.py -k "reads_base" -v`

Expected: FAIL because `read_link()` does not dispatch Base references.

- [ ] **Step 3: Implement bounded Base reads**

Fetch at most five pages of 100 records, stop at 500 records or 50,000 output characters, preserve field names, JSON-serialize structured cells with Unicode intact, and append a truncation marker when the source exceeds a bound.

- [ ] **Step 4: Verify Base reader tests pass**

Run: `pytest tests/test_feishu_resource_reader.py -v`

Expected: PASS.

### Task 3: Connect Base Authorization To Chat

**Files:**
- Modify: `backend/app/routers/chat.py`
- Test: `backend/tests/test_chat_knowledge_context.py`

- [ ] **Step 1: Write failing chat authorization tests**

Add one test proving an authorized Base link reaches the Feishu reader and one proving an ungranted table never reaches either the credential reader or public fetcher.

- [ ] **Step 2: Verify the tests fail because chat assumes document tokens**

Run: `pytest tests/test_chat_knowledge_context.py -k "feishu_base" -v`

Expected: FAIL with `feishu_resource_not_authorized` for the allowed Base link.

- [ ] **Step 3: Authorize by typed resource kind**

Replace document-only token checks with policy checks against the parsed reference in both link preview and normal chat context resolution. Keep default-deny behavior and the no-public-fallback guarantee for every Feishu/Lark URL.

- [ ] **Step 4: Verify chat tests pass**

Run: `pytest tests/test_chat_knowledge_context.py -k "feishu" -v`

Expected: PASS.

### Task 4: Publish Deployment Contract

**Files:**
- Modify: `deploy/compose.formal-hermes.yaml`
- Modify: `deploy/.env.example`
- Modify: `deploy/README.md`
- Modify: `backend/tests/test_hermes_web_contract.py`

- [ ] **Step 1: Write a failing Compose contract assertion**

Require `FEISHU_READ_ALLOWED_BASE_TABLES` to map from `${PLATFORM_FEISHU_READ_ALLOWED_BASE_TABLES:-}` in the API service.

- [ ] **Step 2: Verify the contract test fails**

Run: `pytest tests/test_hermes_web_contract.py -k "formal_compose" -v`

Expected: FAIL because the mapping is absent.

- [ ] **Step 3: Add configuration and operator instructions**

Document the `app_token:table_id` format, the `bitable:app:readonly` scope, target Base application access, rebuild/restart requirement, and a live acceptance check. Do not put real credentials into tracked files.

- [ ] **Step 4: Verify the contract test passes**

Run: `pytest tests/test_hermes_web_contract.py -k "formal_compose" -v`

Expected: PASS.

### Task 5: Verify And Publish

**Files:**
- Review all modified files.

- [ ] **Step 1: Run focused and regression tests**

Run: `pytest tests/test_feishu_resource_reader.py tests/test_chat_knowledge_context.py tests/test_hermes_web_contract.py -q`

Expected: all selected tests pass.

- [ ] **Step 2: Run backend lint**

Run: `ruff check app tests/test_feishu_resource_reader.py tests/test_chat_knowledge_context.py tests/test_hermes_web_contract.py`

Expected: no lint errors.

- [ ] **Step 3: Verify repository consistency**

Run: `git diff --check`

Expected: no whitespace errors.

- [ ] **Step 4: Review, commit, and push**

Commit only the Base reader implementation and its tests/docs, then push `codex/tuesday-single-user-acceptance` without rewriting history.
