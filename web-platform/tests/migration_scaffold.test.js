import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

const requiredScaffoldFiles = [
  "../src/api/client.ts",
  "../src/api/cache.ts",
  "../src/api/mockMode.ts",
  "../src/api/services/index.ts",
  "../src/app/appRuntime.ts",
  "../src/app/uiStore.ts",
  "../src/features/auth/authStore.ts",
  "../src/mock/fixtures/index.ts",
  "../src/mock/generators/index.ts",
  "../src/mock/handlers/index.ts",
  "../src/shared/types/index.ts",
];

test("M0 migration scaffold files exist", async () => {
  for (const file of requiredScaffoldFiles) {
    await assert.doesNotReject(
      access(new URL(file, import.meta.url)),
      `missing scaffold file ${file}`,
    );
  }
});

test("migration matrix covers the 5c29449 legacy test baseline", async () => {
  const matrix = await readFile(
    new URL("./migration-matrix.md", import.meta.url),
    "utf8",
  );
  const rows = matrix
    .split(/\r?\n/)
    .filter((line) => line.startsWith("| `web-platform/"));

  assert.match(matrix, /Baseline commit: `5c29449`/);
  assert.match(matrix, /Legacy test files: 71/);
  assert.equal(rows.length, 71);

  const allowedStatuses = [
    "keep",
    "port",
    "merge",
    "replace",
    "delete-after-equivalent",
  ];
  for (const status of allowedStatuses) {
    assert.match(matrix, new RegExp(`- \`${status}\`:`));
  }
  for (const row of rows) {
    const columns = row.split("|").map((column) => column.trim());
    const status = columns[4].replaceAll("`", "");
    assert.equal(
      allowedStatuses.includes(status),
      true,
      `invalid matrix status ${status}`,
    );
  }
});
