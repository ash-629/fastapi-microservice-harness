import { createHash, randomUUID } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  lstatSync,
  writeFileSync,
} from "node:fs";
import { dirname, join, resolve, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn, spawnSync } from "node:child_process";

export const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
export const EXCLUDED = new Set([
  ".git",
  ".harness",
  ".runtime",
  ".venv",
  "node_modules",
  "target",
  "dist",
  "__pycache__",
  ".pytest_cache",
  ".ruff_cache",
  ".mypy_cache",
  ".vite",
  "test-results",
  "playwright-report",
]);
export function sourceFiles(root = ROOT) {
  const files = [];
  function visit(dir) {
    for (const name of readdirSync(dir).sort()) {
      if (EXCLUDED.has(name)) continue;
      const path = join(dir, name),
        info = lstatSync(path);
      if (info.isSymbolicLink())
        throw Error(`Source links are not allowed: ${path}`);
      if (info.isDirectory()) visit(path);
      else if (
        !(name.startsWith(".env") && name !== ".env.example") &&
        !/\.(zip|db|sqlite3(?:-wal|-shm)?|log|pyc|class|jar)$/.test(name)
      )
        files.push(path);
    }
  }
  visit(root);
  return files;
}
export function fingerprint(root = ROOT) {
  const hash = createHash("sha256");
  hash.update(process.version);
  for (const path of sourceFiles(root)) {
    hash.update(relative(root, path).split(sep).join("/"));
    hash.update(readFileSync(path));
  }
  return hash.digest("hex");
}
export function readJson(path) {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch {
    return {};
  }
}
export function writeJson(path, data) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(data, null, 2) + "\n");
}
export function environment(root = ROOT) {
  const env = { ...process.env };
  if (!env.JAVA_HOME && existsSync(join(root, ".harness/java-home.txt")))
    env.JAVA_HOME = readFileSync(
      join(root, ".harness/java-home.txt"),
      "utf8",
    ).trim();
  const pathValue = process.env.PATH || process.env.Path || "";
  for (const key of Object.keys(env))
    if (key.toLowerCase() === "path") delete env[key];
  env.PATH =
    (env.JAVA_HOME ? join(env.JAVA_HOME, "bin") + sepForPath() : "") +
    pathValue;
  return env;
}
function sepForPath() {
  return process.platform === "win32" ? ";" : ":";
}
export function java(root = ROOT) {
  const env = environment(root);
  return env.JAVA_HOME
    ? join(
        env.JAVA_HOME,
        "bin",
        process.platform === "win32" ? "java.exe" : "java",
      )
    : "java";
}
export function command(exe, args, options = {}) {
  const opts = { cwd: ROOT, env: environment(), ...options };
  if (process.platform === "win32" && /\.(cmd|bat)$/.test(exe)) {
    if (!exe.includes("\\") && !exe.includes("/")) {
      const found = (opts.env.PATH || "")
        .split(";")
        .map((p) => join(p, exe))
        .find((p) => existsSync(p));
      if (found) exe = found;
    }
    if ([exe, ...args].some((a) => /["%!&|<>^\r\n]/.test(a)))
      throw Error("Unsupported shell characters");
    return {
      exe: process.env.ComSpec || "C:\\Windows\\System32\\cmd.exe",
      args: [
        "/d",
        "/s",
        "/c",
        '"' + [exe, ...args].map((a) => '"' + a + '"').join(" ") + '"',
      ],
      opts: { ...opts, windowsVerbatimArguments: true },
    };
  }
  return { exe, args, opts };
}
export function run(exe, args, options = {}) {
  const c = command(exe, args, options),
    r = spawnSync(c.exe, c.args, { ...c.opts, stdio: "inherit" });
  if (r.error) throw r.error;
  if (r.status !== 0)
    throw Error(`Command failed (${r.status}): ${exe} ${args.join(" ")}`);
}
export function maven(args, options = {}) {
  const root = options.cwd || ROOT;
  run(
    join(root, process.platform === "win32" ? "mvnw.cmd" : "mvnw"),
    ["-B", "-ntp", ...args],
    options,
  );
}
export function exportIndex(root, destination) {
  run(
    "git",
    [
      "checkout-index",
      "--all",
      "--prefix=" + resolve(destination).split(sep).join("/") + "/",
    ],
    { cwd: root },
  );
}
export function npm(args, options = {}) {
  run(process.platform === "win32" ? "npm.cmd" : "npm", args, options);
}
export function jar(service) {
  return join(ROOT, `services/${service}/target/${service}-2.0.0.jar`);
}
export async function waitReady(url, child, timeout = 45000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (child && child.exitCode !== null) throw Error(`Service exited: ${url}`);
    try {
      if ((await fetch(url, { signal: AbortSignal.timeout(1500) })).ok) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 200));
  }
  throw Error(`Readiness timed out: ${url}`);
}
export function launch(service, options = {}) {
  const {
    port = service === "inventory" ? 8002 : 8001,
    db = join(ROOT, `.runtime/${service}.sqlite3`),
    inventoryUrl = "http://127.0.0.1:8002",
    log = "inherit",
    recovery = true,
  } = options;
  return spawn(
    java(),
    [
      "-jar",
      jar(service),
      `--server.port=${port}`,
      `--studio.db-path=${db}`,
      `--studio.inventory-url=${inventoryUrl}`,
      `--studio.recovery=${recovery}`,
    ],
    { cwd: ROOT, env: environment(), stdio: log },
  );
}
export function checkArchitecture(root = ROOT) {
  for (const path of sourceFiles(root).filter(
    (p) => p.endsWith(".java") || p.endsWith("pom.xml"),
  )) {
    const file = relative(root, path).split(sep).join("/");
    const text = readFileSync(path, "utf8");
    if (
      (file.startsWith("services/orders/") &&
        /import\s+dev\.orderstudio\.inventory|<artifactId>inventory<\/artifactId>/.test(
          text,
        )) ||
      (file.startsWith("services/inventory/") &&
        /import\s+dev\.orderstudio\.orders|<artifactId>orders<\/artifactId>/.test(
          text,
        )) ||
      (file.startsWith("services/common/") &&
        /import\s+dev\.orderstudio\.(orders|inventory)/.test(text))
    )
      throw Error(`Cross-service dependency: ${file}`);
  }
}
export function checkDocs(root = ROOT) {
  for (const path of sourceFiles(root).filter((p) => p.endsWith(".md"))) {
    for (const match of readFileSync(path, "utf8").matchAll(
      /\[[^\]]+\]\(([^)]+)\)/g,
    )) {
      const link = match[1];
      if (
        !/^(https?:|#)/.test(link) &&
        !existsSync(resolve(dirname(path), link.split("#")[0]))
      )
        throw Error(`Broken link: ${path} -> ${link}`);
    }
  }
}
export const REQUIRED = {
  quick: [
    "documentation",
    "architecture",
    "java-build",
    "tool-tests",
    "contract",
    "frontend-build",
    "frontend-format",
  ],
  affected: [
    "documentation",
    "architecture",
    "java-tests",
    "tool-tests",
    "contract",
    "frontend-build",
    "frontend-format",
  ],
  full: [
    "documentation",
    "architecture",
    "java-tests",
    "tool-tests",
    "contract",
    "frontend-build",
    "frontend-format",
    "playwright",
  ],
};
export function verified(report, scope, current) {
  const checks = report.checks || [];
  return (
    report.status === "PASS" &&
    report.fingerprint === current &&
    Array.isArray(checks) &&
    checks.every((c) => c.status === "PASS") &&
    REQUIRED[scope].every((name) =>
      checks.some(
        (c) =>
          c.name === name || (name === "java-build" && c.name === "java-tests"),
      ),
    )
  );
}
export async function handleHook(event, data = {}, root = ROOT) {
  if (event === "SessionStart")
    return {
      systemMessage:
        "入口 AGENTS.md；命令 node tools/harness.mjs；代码任务先 task start。",
    };
  const taskPath = join(root, ".harness/task.json"),
    task = readJson(taskPath);
  if (!task.active) return {};
  const current = fingerprint(root);
  if (event === "PostToolUse") {
    task.dirty = task.verified_fingerprint !== current;
    writeJson(taskPath, task);
  }
  if (event === "Stop") {
    const scope = Object.hasOwn(REQUIRED, task.scope) ? task.scope : "affected";
    if (
      verified(readJson(join(root, ".harness/latest.json")), scope, current)
    ) {
      writeJson(taskPath, {
        ...task,
        active: false,
        dirty: false,
        verified_fingerprint: current,
      });
      return {};
    }
    const reason = `代码任务缺少当前 ${scope} 检查。运行 node tools/harness.mjs check --scope ${scope}，修复失败后记录真实结果。`;
    return data.stop_hook_active
      ? { systemMessage: reason + " 已续跑一次，报告尚未解决的原因。" }
      : { decision: "block", reason };
  }
  return {};
}
export function receipt(
  scope,
  checks,
  start,
  initialFingerprint = fingerprint(),
) {
  return {
    run_id: randomUUID(),
    scope,
    status: checks.every((c) => c.status === "PASS") ? "PASS" : "FAIL",
    fingerprint: initialFingerprint,
    duration_seconds: (Date.now() - start) / 1000,
    checks,
  };
}
