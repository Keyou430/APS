import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("production entrypoint is fully bundled by Vite", async () => {
  const htmlSource = await readFile(new URL("../index.html", import.meta.url), "utf-8");
  const legacyEntry = await readFile(
    new URL("../src/legacy-entry.ts", import.meta.url),
    "utf-8",
  );
  const mainEntry = await readFile(
    new URL("../src/main.tsx", import.meta.url),
    "utf-8",
  );
  const mountEntry = await readFile(
    new URL("../src/app/mountReactApp.tsx", import.meta.url),
    "utf-8",
  );

  for (const forbiddenSource of [
    'src="/src/app.js"',
    'src="/src/components/',
    'src="/src/views/',
  ]) {
    assert.equal(
      htmlSource.includes(forbiddenSource),
      false,
      `index.html must not load legacy runtime script ${forbiddenSource}`,
    );
  }
  assert.equal(
    htmlSource.includes('src="/node_modules/'),
    false,
    "index.html must not load runtime scripts from /node_modules in production",
  );
  assert.equal(
    htmlSource.includes("https://cdn.jsdelivr.net"),
    false,
    "index.html must not execute runtime code from CDN",
  );
  assert.ok(
    htmlSource.includes('type="module" src="/src/legacy-entry.ts"'),
    "index.html must use the Vite legacy entry module",
  );
  assert.match(legacyEntry, /mountReactApp/);
  assert.match(legacyEntry, /reactAppRoot/);
  assert.match(mainEntry, /mountReactApp/);
  assert.match(mountEntry, /createRoot/);
  assert.match(mountEntry, /App/);
});
