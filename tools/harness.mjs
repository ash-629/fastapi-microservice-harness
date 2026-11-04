import {
  existsSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
  openSync,
  closeSync,
} from "node:fs";
import { join, relative, resolve, sep, isAbsolute } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { spawn, spawnSync } from "node:child_process";
import { zipSync, strToU8 } from "fflate";
import {
  ROOT,
  sourceFiles,
  fingerprint,
  readJson,
  writeJson,
  environment,
  java,
  command,
  run,
  maven,
  npm,
  jar,
  launch,
  waitReady,
  checkArchitecture,
  checkDocs,
  REQUIRED,
  verified,
  handleHook,
  receipt,
} from "./lib.mjs";
import { contract } from "./contract.mjs";
import { exportIndex } from "./lib.mjs";

const args = process.argv.slice(2),
  cmd = args[0],
  action = args[1];
const option = (name, fallback) => {
  const i = args.indexOf("--" + name);
  return i < 0 ? fallback : args[i + 1];
};
function scope() {
  const value = option("scope", "affected");
  if (!Object.hasOwn(REQUIRED, value)) throw Error("Invalid scope");
  return value;
}
export function packageSource(root, output) {
  const destination = relative(resolve(root), resolve(output));
  if (!(
    isAbsolute(destination) ||
    destination === ".." ||
    destination.startsWith(".." + sep)
  ))
    throw Error("Archive must be outside source directory");
  if (existsSync(output)) throw Error("Archive already exists");
  const report = readJson(join(root, ".harness/latest.json"));
  if (!verified(report, "full", fingerprint(root)))
    throw Error("A current full PASS is required");
  const entries = {};
  for (const path of sourceFiles(root))
    entries["OrderStudio/" + relative(root, path).split(sep).join("/")] = [
      new Uint8Array(readFileSync(path)),
      {
        attrs:
          (path.includes(".githooks") ||
          path.endsWith("/mvnw") ||
          path.endsWith("\\mvnw")
            ? 0o100755
            : 0o100644) << 16,
      },
    ];
  entries["OrderStudio/check-results.json"] = strToU8(
    JSON.stringify(report, null, 2),
  );
  mkdirSync(resolve(output, ".."), { recursive: true });
  writeFileSync(output, zipSync(entries), { flag: "wx" });
  return output;
}
async function check() {
  const selected = scope(),
    checks = [],
    start = Date.now(),
    initialFingerprint = fingerprint();
  const step = async (name, fn) => {
    console.log(`Checking ${name}`);
    try {
      await fn();
      checks.push({ name, status: "PASS" });
    } catch (e) {
      checks.push({ name, status: "FAIL", message: e.message });
      throw e;
    }
  };
  try {
    await step("documentation", () => checkDocs());
    await step("architecture", () => checkArchitecture());
    await step(selected === "quick" ? "java-build" : "java-tests", () =>
      maven(["verify", ...(selected === "quick" ? ["-DskipTests"] : [])]),
    );
    await step("tool-tests", () => {
      run(process.execPath, [
        join(ROOT, "web/node_modules/prettier/bin/prettier.cjs"),
        "--check",
        "tools/*.mjs",
        "tools/tests/*.mjs",
        "package.json",
      ]);
      run(process.execPath, [
        "--test",
        ...sourceFiles(ROOT).filter((p) => p.endsWith(".test.mjs")),
      ]);
    });
    await step("contract", () => contract(false));
    await step("frontend-build", () =>
      npm(["run", "build"], { cwd: join(ROOT, "web") }),
    );
    await step("frontend-format", () =>
      npm(["run", "format:check"], { cwd: join(ROOT, "web") }),
    );
    if (selected === "full")
      await step("playwright", () =>
        npm(["exec", "--", "playwright", "test"], { cwd: join(ROOT, "web") }),
      );
  } finally {
    const changed = fingerprint() !== initialFingerprint;
    if (changed)
      checks.push({
        name: "source-stability",
        status: "FAIL",
        message: "Source changed while checks were running",
      });
    const report = receipt(selected, checks, start, initialFingerprint);
    if (checks.length !== REQUIRED[selected].length) report.status = "FAIL";
    writeJson(join(ROOT, ".harness/latest.json"), report);
    writeJson(join(ROOT, `.harness/runs/${report.run_id}.json`), report);
    console.log(JSON.stringify(report, null, 2));
    if (changed)
      throw Error(
        "Source changed while checks were running; rerun on stable sources",
      );
  }
}
async function up() {
  const state = readJson(join(ROOT, ".runtime/processes.json"));
  if (Object.keys(state).length)
    throw Error("Process records exist; run down before up");
  maven(["package", "-DskipTests"]);
  for (const port of [8001, 8002, 5173]) {
    const net = await import("node:net");
    await new Promise((resolve, reject) => {
      const s = net.createServer();
      s.once("error", () => reject(Error(`Port ${port} is occupied`)));
      s.listen(port, "127.0.0.1", () => s.close(resolve));
    });
  }
  mkdirSync(join(ROOT, ".runtime"), { recursive: true });
  const records = {};
  try {
    for (const [name, exe, argv, cwd] of [
      ["inventory", java(), ["-jar", jar("inventory")], ROOT],
      ["orders", java(), ["-jar", jar("orders")], ROOT],
      [
        "web",
        process.execPath,
        [
          join(ROOT, "web/node_modules/vite/bin/vite.js"),
          "--host",
          "127.0.0.1",
          "--port",
          "5173",
          "--strictPort",
        ],
        join(ROOT, "web"),
      ],
    ]) {
      const fd = openSync(join(ROOT, `.runtime/${name}.log`), "a");
      const child = spawn(exe, argv, {
        cwd,
        env: environment(),
        detached: true,
        windowsHide: true,
        stdio: ["ignore", fd, fd],
      });
      closeSync(fd);
      await new Promise((resolve, reject) => {
        child.once("spawn", resolve);
        child.once("error", reject);
      });
      child.unref();
      records[name] = {
        pid: child.pid,
        token:
          name === "web"
            ? join(ROOT, "web/node_modules/vite/bin/vite.js")
            : jar(name),
      };
      writeJson(join(ROOT, ".runtime/processes.json"), records);
      await waitReady(
        name === "web"
          ? "http://127.0.0.1:5173"
          : `http://127.0.0.1:${name === "orders" ? 8001 : 8002}/health/ready`,
        child,
      );
    }
  } catch (e) {
    down();
    throw e;
  }
  console.log(
    "Ready: http://127.0.0.1:5173 ; API docs: 8001/docs and 8002/docs",
  );
}
function down() {
  const file = join(ROOT, ".runtime/processes.json"),
    records = readJson(file),
    left = {};
  for (const [name, r] of Object.entries(records)) {
    let line = "";
    if (process.platform === "win32")
      line =
        spawnSync(
          "powershell.exe",
          [
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            `(Get-CimInstance Win32_Process -Filter 'ProcessId = ${Number(r.pid)}').CommandLine`,
          ],
          { encoding: "utf8", windowsHide: true },
        ).stdout || "";
    else
      line =
        spawnSync("ps", ["-p", String(r.pid), "-o", "args="], {
          encoding: "utf8",
        }).stdout || "";
    if (!line.trim()) continue;
    if (typeof r.token !== "string" || !line.includes(r.token)) {
      left[name] = r;
      console.error(`Process identity mismatch: ${name}`);
      continue;
    }
    try {
      process.kill(r.pid);
    } catch (e) {
      if (e.code !== "ESRCH") left[name] = r;
    }
  }
  writeJson(file, left);
  if (Object.keys(left).length)
    throw Error("Some processes could not be stopped safely");
}
async function staged() {
  const dir = mkdtempSync(join(tmpdir(), "studio-index-"));
  exportIndex(ROOT, dir);
  for (const path of [
    "pom.xml",
    "tools/harness.mjs",
    "package-lock.json",
    "web/package-lock.json",
  ])
    if (!existsSync(join(dir, path)))
      throw Error(`Missing staged file: ${path}`);
  checkDocs(dir);
  checkArchitecture(dir);
  const env = { ...environment(), HARNESS_DEPENDENCY_ROOT: ROOT };
  maven(["verify", "-DskipTests"], { cwd: dir, env });
  // Import project tools and source only from the index snapshot; dependencies are shared.
  const fs = await import("node:fs");
  fs.symlinkSync(
    join(ROOT, "node_modules"),
    join(dir, "node_modules"),
    process.platform === "win32" ? "junction" : "dir",
  );
  run(process.execPath, [join(dir, "tools/harness.mjs"), "contract", "check"], {
    cwd: dir,
    env,
  });
}
async function main() {
  if (cmd === "check") return check();
  if (cmd === "up") return up();
  if (cmd === "down") return down();
  if (cmd === "serve") {
    const service = action;
    if (!["orders", "inventory"].includes(service))
      throw Error("Unknown service");
    const child = launch(service, {
      port: Number(option("port", service === "orders" ? 8001 : 8002)),
      db: option(
        "db",
        process.env.DB_PATH || join(ROOT, `.runtime/${service}.sqlite3`),
      ),
      inventoryUrl: process.env.INVENTORY_URL || "http://127.0.0.1:8002",
    });
    process.on("SIGTERM", () => child.kill());
    process.on("SIGINT", () => child.kill());
    await new Promise((r, j) => {
      child.on("error", j);
      child.on("exit", (code) =>
        code === 0 ? r() : j(Error(`Service exit ${code}`)),
      );
    });
    return;
  }
  if (cmd === "contract") return contract(action === "generate");
  if (cmd === "doctor") {
    run(java(), ["-version"]);
    maven(["-version"]);
    run(process.execPath, ["--version"]);
    npm(["--version"]);
    for (const file of [
      "package-lock.json",
      "web/package-lock.json",
      "contracts/orders.openapi.json",
      "contracts/inventory.openapi.json",
    ])
      if (!existsSync(join(ROOT, file))) throw Error(`Missing ${file}`);
    return console.log("Environment PASS");
  }
  if (cmd === "smoke") {
    if (args.includes("--isolated"))
      return run(process.execPath, [
        "--test",
        join(ROOT, "tools/tests/http.test.mjs"),
      ]);
    for (const port of [8001, 8002])
      await waitReady(`http://127.0.0.1:${port}/health/ready`, null, 5000);
    return console.log("Read-only readiness PASS");
  }
  if (cmd === "reconcile") {
    const id = option("order-id");
    if (
      !id ||
      !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(
        id,
      )
    )
      throw Error("--order-id UUID required");
    run(java(), ["-jar", jar("orders"), "--reconcile", `--order-id=${id}`]);
    return;
  }
  if (cmd === "seed") {
    run(java(), ["-jar", jar("inventory"), "--seed"]);
    return;
  }
  if (cmd === "staged") return staged();
  if (cmd === "hooks" && action === "install") {
    run("git", ["config", "core.hooksPath", ".githooks"]);
    return;
  }
  if (cmd === "hook") {
    let input = "";
    for await (const chunk of process.stdin) input += chunk;
    let data = {};
    try {
      data = JSON.parse(input);
    } catch {}
    console.log(JSON.stringify(await handleHook(action, data)));
    return;
  }
  if (cmd === "task") {
    if (action === "start")
      writeJson(join(ROOT, ".harness/task.json"), {
        active: true,
        scope: scope(),
      });
    else if (action === "finish") {
      const task = readJson(join(ROOT, ".harness/task.json"));
      if (
        !verified(
          readJson(join(ROOT, ".harness/latest.json")),
          task.scope || "affected",
          fingerprint(),
        )
      )
        throw Error("Current scoped checks are required");
      writeJson(join(ROOT, ".harness/task.json"), {
        ...task,
        active: false,
        verified_fingerprint: fingerprint(),
      });
      console.log("Task verified and finished");
    } else throw Error("Use task start or task finish");
    return;
  }
  if (cmd === "report") {
    const report = readJson(join(ROOT, ".harness/latest.json"));
    console.log(
      JSON.stringify(
        { ...report, current: report.fingerprint === fingerprint() },
        null,
        2,
      ),
    );
    return;
  }
  if (cmd === "package") {
    const output = option("output");
    if (!output) throw Error("--output required");
    return console.log(packageSource(ROOT, resolve(output)));
  }
  throw Error(
    "Commands: doctor up down serve smoke contract check report hooks hook task staged package",
  );
}
if (resolve(process.argv[1] || "") === fileURLToPath(import.meta.url)) {
  main().catch((e) => {
    console.error(e.message);
    process.exitCode = 1;
  });
}
