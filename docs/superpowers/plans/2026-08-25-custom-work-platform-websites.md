# Custom Work Platform Websites Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each logged-in user create, preview, edit, and remove multiple named custom website entries under the legacy work-platform menu.

**Architecture:** Add a small typed, pure website-record module for validation, normalization, and safe storage parsing. The legacy app owns user-scoped persistence and dynamic menu/view rendering; its existing iframe toolbar supplies refresh and external-window fallback without calling an unimplemented API.

**Tech Stack:** Vite, vanilla JavaScript legacy shell, TypeScript/Vitest unit tests, Playwright, Node test runner.

---

### Task 1: Define Tested Custom Website Records

**Files:**
- Create: `web-platform/src/app/customWebsites.ts`
- Create: `web-platform/src/app/customWebsites.test.ts`

- [x] **Step 1: Write failing tests for URL and record validation**

```ts
import { describe, expect, it } from "vitest";
import {
  createCustomWebsite,
  parseCustomWebsites,
} from "./customWebsites";

describe("createCustomWebsite", () => {
  it("normalizes a protocol-less URL", () => {
    expect(createCustomWebsite([], { id: "site-a", name: "采购门户", url: "procurement.example.com" }))
      .toEqual({ ok: true, value: { id: "site-a", name: "采购门户", url: "https://procurement.example.com/" } });
  });

  it("rejects duplicate names except when editing the same record", () => {
    const sites = [{ id: "site-a", name: "采购门户", url: "https://example.com/" }];
    expect(createCustomWebsite(sites, { id: "site-b", name: "采购门户", url: "https://other.example/" }))
      .toEqual({ ok: false, error: "name_taken" });
    expect(createCustomWebsite(sites, { id: "site-a", name: "采购门户", url: "https://other.example/" }))
      .toMatchObject({ ok: true });
  });
});
```

- [x] **Step 2: Run the new test and verify it fails because the module is absent**

Run: `npm exec vitest run src/app/customWebsites.test.ts`

Expected: FAIL with an unresolved `./customWebsites` module.

- [x] **Step 3: Implement a focused pure record module**

Define `CustomWebsite` as `{ id: string; name: string; url: string }` and return either a normalized record or one of `name_required`, `name_taken`, and `url_invalid` from `createCustomWebsite`.

`createCustomWebsite` must trim names, add `https://` if absent, use `URL`, accept only HTTP/S protocols, and compare duplicate names with `toLocaleLowerCase()`. `parseCustomWebsites` must safely drop malformed entries instead of throwing. Both functions use the same validation path so parsed records are normalized with the same rules as newly saved records.

- [x] **Step 4: Run the module test and verify it passes**

Run: `npm exec vitest run src/app/customWebsites.test.ts`

Expected: PASS with all custom-website cases green.

- [x] **Step 5: Commit the pure module and tests**

```powershell
git add web-platform/src/app/customWebsites.ts web-platform/src/app/customWebsites.test.ts
git commit -m "feat: add custom website record helpers"
```

### Task 2: Specify Browser Behaviour Before UI Implementation

**Files:**
- Create: `web-platform/tests/e2e/custom-work-platform-websites.spec.ts`

- [x] **Step 1: Write a failing Playwright flow**

The spec must establish an authenticated session, fulfill local API bootstrap/auth calls, and intercept `https://*.example.test/**` with a simple HTML response. It must:

```ts
await page.getByRole("button", { name: "添加自定义网站" }).click();
await page.getByLabel("自定义网站名称").fill("采购门户");
await page.getByLabel("自定义网站地址").fill("procurement.example.test");
await page.getByRole("button", { name: "保存并载入" }).click();
await expect(page.getByRole("button", { name: "采购门户" })).toBeVisible();
await expect(page.getByRole("heading", { name: "采购门户" })).toBeVisible();
```

Extend the same flow to create a second site, edit the first name, reject the second site when renamed to the same name, accept the delete confirmation, and verify the remaining entry survives `page.reload()`.

- [x] **Step 2: Run the browser spec and verify it fails at the absent menu entry**

Run: `npm exec playwright test tests/e2e/custom-work-platform-websites.spec.ts`

Expected: FAIL because “添加自定义网站” does not exist.

### Task 3: Render Dynamic Work-Platform Website Entries

**Files:**
- Modify: `web-platform/src/app.js`
- Modify: `web-platform/index.html`
- Modify: `web-platform/styles.css`

- [x] **Step 1: Add storage and safe view helpers to the legacy app**

Import `createCustomWebsite` and `parseCustomWebsites`. Add `customWebsitesStorageKey`, `getInitialCustomWebsites`, `saveCustomWebsites`, and a `state.customWebsites` array. Include the key and state in `_resetUserState`, `clearAuth`, and `applyPortalBootstrap` so account switches do not render stale entries.

Add helpers for the stable view ID `custom-website-${site.id}`, a reserved `custom-website-new` draft view, and checks that dynamic views only resolve to a saved record. Update `openTab`, `getViewLabel`, `syncSidebarActive`, and tab closing logic to accept only those validated dynamic IDs while retaining `validViews` protection for fixed pages.

- [x] **Step 2: Add dynamic navigation and page rendering**

In `index.html`, preserve static 飞书/钉钉 buttons and add a custom-site menu container followed by a fixed `添加自定义网站` button. Add a dynamic-view mount point after the fixed embedded pages.

In `app.js`, render saved entries in insertion order using escaped labels and `data-custom-website-id`. Render the draft or selected site page from state with labelled name/address inputs, an inline error element, iframe, refresh button, safe external-open button, and delete button. Bind events after each render so adding, editing, refresh, external opening, and deletion work without duplicating listeners.

- [x] **Step 3: Implement save, validation feedback, and deletion**

Saving invokes `createCustomWebsite`; a validation error updates the inline error without replacing input values or the prior iframe. A successful save persists only with `_saveScoped`, refreshes the dynamic menu/views/tabs, and opens the saved view. Delete requires `window.confirm`, removes only the selected record, removes its tabs, and falls back to 飞书 if the deleted view was active.

Use the stored, validated URL for iframe `src` and `window.open(url, "_blank", "noopener,noreferrer")`. Do not call `saveEmbedUrlsRemote` and do not interpret an iframe `load` event as proof that a third-party page is embeddable.

- [x] **Step 4: Run unit and browser tests until both pass**

Run:

```powershell
npm exec vitest run src/app/customWebsites.test.ts
npm exec playwright test tests/e2e/custom-work-platform-websites.spec.ts
```

Expected: both commands exit 0; the Playwright test demonstrates creation, edit, duplicate rejection, deletion, and reload restoration.

- [ ] **Step 5: Commit the legacy UI feature**

```powershell
git add web-platform/src/app.js web-platform/index.html web-platform/styles.css web-platform/tests/e2e/custom-work-platform-websites.spec.ts
git commit -m "feat: add custom work platform websites"
```

### Task 4: Run the Full Frontend Gate and Push

**Files:**
- Verify only

- [x] **Step 1: Run all required static and build checks**

```powershell
npm test
npm run lint
npm run build
npm exec playwright test
git diff --check
```

Expected: each command exits 0. Investigate and fix any regression before committing the final state.

- [x] **Step 2: Inspect the final change set**

```powershell
git status --short
git log --oneline -3
git diff HEAD~2..HEAD --check
```

Expected: only the custom website feature, its tests, and its approved design/plan documents are included.

- [ ] **Step 3: Push the current branch**

```powershell
git push origin codex/tuesday-single-user-acceptance
```

Expected: remote confirms the branch update.
