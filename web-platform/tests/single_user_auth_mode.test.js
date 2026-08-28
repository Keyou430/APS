import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("legacy auth recovery restores the local user before showing a login overlay", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(source, /async function restoreSingleUserIdentity\(\)/);
  assert.match(
    source,
    /agent-platform:session-cleared[\s\S]*?restoreSingleUserIdentity\(\)[\s\S]*?showLoginOverlay\(\)/,
  );
  assert.match(
    source,
    /async function handleLogout\(\)[\s\S]*?contractAuth\.logout\(\)[\s\S]*?restoreSingleUserIdentity\(\)/,
  );
});

test("single-user mode is detected from anonymous auth instead of being hard-coded", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.doesNotMatch(source, /const SINGLE_USER_MODE = true/);
  assert.match(source, /let _singleUserMode = false/);
  assert.match(source, /_singleUserMode = !_authToken/);
  assert.match(source, /status === 401 && !_singleUserMode/);
  assert.match(source, /if \(!isLoggedIn\(\)\)[\s\S]*?showLoginOverlay\(\)/);
});

test("React-owned routes resolve anonymous organization context before mounting", async () => {
  const source = await readFile(new URL("../src/legacy-entry.ts", import.meta.url), "utf8");

  assert.match(
    source,
    /installAppRuntime\(window\)[\s\S]*?await window\.__contractAuth\?\.fetchMe\(\)[\s\S]*?mountReactApp\(shellRoot\)/,
  );
});

test("anonymous React routes return to the source login entry in multi-user mode", async () => {
  const source = await readFile(new URL("../src/legacy-entry.ts", import.meta.url), "utf8");

  assert.match(
    source,
    /catch \(error\)[\s\S]*?error\.status === 401[\s\S]*?window\.location\.replace\("\/"\)/,
  );
});

test("the seeded admin role retains legacy administrator capabilities", async () => {
  const source = await readFile(new URL("../src/app.js", import.meta.url), "utf8");

  assert.match(source, /roles\.includes\("super_admin"\)[\s\S]*roles\.includes\("admin"\)/);
  assert.match(source, /role === "super_admin" \|\| role === "admin"/);
});
