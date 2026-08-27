import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("cockpit decisions use demo samples only behind the explicit mock flag", async () => {
  const appSource = await readFile(new URL("../src/app.js", import.meta.url), "utf-8");

  assert.ok(
    appSource.includes("isCockpitDecisionDemoMode"),
    "cockpit decision samples must be gated by VITE_USE_MOCK=true",
  );

  assert.ok(
    appSource.includes("setCockpitDecisionDemoFallback"),
    "sample decisions must flow through one explicit demo fallback helper",
  );

  assert.ok(
    !/renderCockpitDecisions\(\)\s*\{[\s\S]*?COCKPIT_SAMPLE_DECISIONS/.test(appSource),
    "rendering an empty production decision list must not repopulate sample decisions",
  );

  assert.ok(
    !/catch\(\(error\) => \{[\s\S]*?COCKPIT_SAMPLE_DECISIONS/.test(appSource),
    "backend decision failures must not silently show local sample decisions",
  );

  assert.ok(
    !/replaceCockpitDecision\(updated,\s*\{[\s\S]*?status:\s*"approved"/.test(appSource),
    "production approval must not fabricate an approved result when the backend response is incomplete",
  );
});
