import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("frontend toolchain exposes fixed lint and ci test commands", async () => {
  const packageJson = JSON.parse(
    await readFile(new URL("../package.json", import.meta.url), "utf-8"),
  );

  assert.equal(packageJson.scripts.lint, "eslint .");
  assert.equal(packageJson.scripts.test, "node --test tests/*.test.js");
  assert.equal(
    packageJson.scripts["test:ci"],
    "npm test && vitest run && npm run build && playwright test",
  );

  for (const dependencyName of ["react", "react-dom"]) {
    assert.ok(
      packageJson.dependencies?.[dependencyName],
      `missing runtime dependency ${dependencyName}`,
    );
  }

  for (const dependencyName of [
    "@eslint/js",
    "@playwright/test",
    "@testing-library/jest-dom",
    "@testing-library/react",
    "@testing-library/user-event",
    "@types/react",
    "@types/react-dom",
    "eslint",
    "eslint-plugin-react-hooks",
    "eslint-plugin-react-refresh",
    "jsdom",
    "typescript-eslint",
    "vitest",
  ]) {
    assert.ok(
      packageJson.devDependencies?.[dependencyName],
      `missing dev dependency ${dependencyName}`,
    );
  }
});

test("playwright e2e tests are isolated from node contract tests", async () => {
  const playwrightConfig = await readFile(
    new URL("../playwright.config.ts", import.meta.url),
    "utf-8",
  );

  assert.ok(
    playwrightConfig.includes("testDir: './tests/e2e'"),
    "playwright must only discover e2e tests",
  );
});
