import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { unzipSync } from "fflate";
import {
  fingerprint,
  sourceFiles,
  REQUIRED,
  verified,
  handleHook,
  writeJson,
  readJson,
  checkArchitecture,
  checkDocs,
  command,
} from "../lib.mjs";
import { packageSource } from "../harness.mjs";
import { exportIndex, run, receipt } from "../lib.mjs";
const fixture = () => mkdtempSync(join(tmpdir(), "studio-tools-"));
test("receipt retains the source fingerprint from check start", () => {
  const root = fixture(),
    initial = fingerprint(root);
  writeFileSync(join(root, "changed.java"), "changed");
  const r = receipt(
    "full",
    REQUIRED.full.map((name) => ({ name, status: "PASS" })),
    Date.now(),
    initial,
  );
  assert.equal(r.fingerprint, initial);
  assert(!verified(r, "full", fingerprint(root)));
});
function report(root, scope = "full") {
  const r = {
    status: "PASS",
    fingerprint: fingerprint(root),
    scope,
    checks: REQUIRED[scope].map((name) => ({ name, status: "PASS" })),
  };
  writeJson(join(root, ".harness/latest.json"), r);
  return r;
}
test("source hash excludes local artifacts but includes source changes", () => {
  const root = fixture();
  writeFileSync(join(root, "pom.xml"), "<project/>");
  mkdirSync(join(root, "target"));
  writeFileSync(join(root, "target", "x.class"), "binary");
  const before = fingerprint(root);
  writeFileSync(join(root, "target", "x.class"), "new");
  assert.equal(fingerprint(root), before);
  writeFileSync(join(root, "pom.xml"), "<changed/>");
  assert.notEqual(fingerprint(root), before);
});
test("checks cannot use failed, incomplete, stale, or narrower receipts", () => {
  const root = fixture(),
    r = report(root);
  assert(verified(r, "full", fingerprint(root)));
  assert(!verified({ ...r, status: "FAIL" }, "full", fingerprint(root)));
  assert(
    !verified({ ...r, checks: r.checks.slice(1) }, "full", fingerprint(root)),
  );
  assert(!verified(r, "full", "stale"));
  assert(!verified(report(root, "quick"), "full", fingerprint(root)));
});
test("Stop requires scoped evidence and bounds continuation", async () => {
  const root = fixture();
  writeJson(join(root, ".harness/task.json"), { active: true, scope: "full" });
  assert.equal((await handleHook("Stop", {}, root)).decision, "block");
  assert.equal(
    (await handleHook("Stop", { stop_hook_active: true }, root)).decision,
    undefined,
  );
  report(root);
  assert.deepEqual(await handleHook("Stop", {}, root), {});
  assert.equal(readJson(join(root, ".harness/task.json")).active, false);
});

test("malformed receipts are rejected without crashing the Stop hook", async () => {
  const root = fixture();
  writeJson(join(root, ".harness/task.json"), { active: true, scope: "full" });
  for (const value of [
    null,
    [],
    "bad",
    42,
    { status: "PASS", fingerprint: fingerprint(root), checks: [null] },
  ]) {
    writeJson(join(root, ".harness/latest.json"), value);
    assert.equal((await handleHook("Stop", {}, root)).decision, "block");
    assert.equal(verified(value, "full", fingerprint(root)), false);
  }
  assert.equal(verified(report(root), "unknown", fingerprint(root)), false);
  writeFileSync(join(root, ".harness/latest.json"), "{broken");
  assert.deepEqual(readJson(join(root, ".harness/latest.json")), {});
  assert.equal((await handleHook("Stop", {}, root)).decision, "block");
});
test("consultation does not create a task; source changes mark an active task dirty", async () => {
  const root = fixture();
  assert.deepEqual(await handleHook("Stop", {}, root), {});
  writeJson(join(root, ".harness/task.json"), {
    active: true,
    scope: "affected",
  });
  assert.equal((await handleHook("Stop", null, root)).decision, "block");
  report(root);
  writeFileSync(join(root, "source.java"), "changed");
  await handleHook("PostToolUse", {}, root);
  assert.equal(readJson(join(root, ".harness/task.json")).dirty, true);
  assert.equal((await handleHook("Stop", {}, root)).decision, "block");
});
test("archive requires current full PASS, includes hidden skills, and excludes siblings and local data", () => {
  const parent = fixture(),
    root = join(parent, "source");
  mkdirSync(join(root, ".agents/skills/api"), { recursive: true });
  writeFileSync(join(root, ".agents/skills/api/SKILL.md"), "skill");
  writeFileSync(join(parent, "outside.md"), "private");
  mkdirSync(join(root, ".runtime"));
  writeFileSync(join(root, ".runtime/orders.sqlite3"), "private");
  writeFileSync(join(root, ".env"), "private");
  const output = join(parent, "source.zip");
  assert.throws(() => packageSource(root, output), /full PASS/);
  report(root);
  packageSource(root, output);
  const files = Object.keys(unzipSync(readFileSync(output)));
  assert.deepEqual(
    files.sort(),
    [
      "OrderStudio/.agents/skills/api/SKILL.md",
      "OrderStudio/check-results.json",
    ].sort(),
  );
  assert.throws(() => packageSource(root, output), /exists/);
  assert.throws(() => packageSource(root, join(root, "bad.zip")), /outside/);
  writeFileSync(join(root, "new.java"), "changed");
  assert.throws(
    () => packageSource(root, join(parent, "stale.zip")),
    /full PASS/,
  );
});
test("module boundaries reject imports and dependencies across services", () => {
  const root = fixture();
  mkdirSync(join(root, "services/orders"), { recursive: true });
  writeFileSync(
    join(root, "services/orders/Wrong.java"),
    "import dev.orderstudio.inventory.InventoryService;",
  );
  assert.throws(() => checkArchitecture(root), /Cross-service/);
  writeFileSync(
    join(root, "services/orders/Wrong.java"),
    "package dev.orderstudio.orders;",
  );
  checkArchitecture(root);
});
test("documentation check catches broken local links", () => {
  const root = fixture();
  writeFileSync(join(root, "README.md"), "[Guide](missing.md)");
  assert.throws(() => checkDocs(root), /Broken link/);
  writeFileSync(join(root, "missing.md"), "# Guide");
  checkDocs(root);
});
test("command arguments preserve spaces and reject shell control characters on Windows", () => {
  if (process.platform === "win32") {
    const c = command("C:\\Project Folder\\mvnw.cmd", ["-B", "verify"]);
    assert(c.args.at(-1).includes('"C:\\Project Folder\\mvnw.cmd"'));
    assert.throws(() => command("mvnw.cmd", ["x&y"]), /Unsupported/);
  }
});
test("index snapshot reads staged content and preserves worktree changes", () => {
  const root = fixture(),
    destination = fixture();
  run("git", ["init", "-q"], { cwd: root });
  writeFileSync(join(root, "README.md"), "staged content");
  run("git", ["add", "README.md"], { cwd: root });
  writeFileSync(join(root, "README.md"), "unstaged changes");
  exportIndex(root, destination);
  assert.equal(
    readFileSync(join(destination, "README.md"), "utf8"),
    "staged content",
  );
  assert.equal(
    readFileSync(join(root, "README.md"), "utf8"),
    "unstaged changes",
  );
});
