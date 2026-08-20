import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";

test("TUI stays an API client without watch, driver, or SQLite access", async () => {
  const files = await sourceFiles(process.cwd() + "/src");
  const forbiddenText = [
    "driver" + ".execute",
    "physical_agent." + "watch",
    "physical_agent." + "drivers"
  ];
  const sqlitePackages = ["sqlite", "sqlite" + "3", "better-" + "sqlite" + "3"].join("|");
  const sqliteImport = new RegExp(
    `from\\s+["'](?:${sqlitePackages})["']|require\\(["'](?:${sqlitePackages})["']\\)`
  );
  const sqliteDirectAccess = /state\.db|SELECT\s+.+\s+FROM|INSERT\s+INTO|UPDATE\s+\w+\s+SET/i;

  for (const file of files) {
    const content = await readFile(file, "utf8");
    for (const term of forbiddenText) {
      assert.equal(content.includes(term), false, `${file} contains forbidden ${term}`);
    }
    assert.equal(sqliteImport.test(content), false, `${file} imports SQLite directly`);
    assert.equal(sqliteDirectAccess.test(content), false, `${file} appears to access SQLite directly`);
  }
});

async function sourceFiles(root: string): Promise<string[]> {
  const entries = await readdir(root, { withFileTypes: true });
  const files: string[] = [];
  for (const entry of entries) {
    const path = join(root, entry.name);
    if (entry.isDirectory()) {
      files.push(...await sourceFiles(path));
      continue;
    }
    if (/\.(ts|tsx)$/.test(entry.name)) {
      files.push(path);
    }
  }
  return files;
}
