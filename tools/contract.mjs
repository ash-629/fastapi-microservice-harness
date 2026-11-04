import {
  existsSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  writeFileSync,
  mkdirSync,
} from "node:fs";
import { join, relative } from "node:path";
import { tmpdir } from "node:os";
import { createServer } from "node:net";
import { ROOT, launch, waitReady, npm } from "./lib.mjs";

export async function freePort() {
  const server = createServer();
  return new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const port = server.address().port;
      server.close(() => resolve(port));
    });
  });
}
function sorted(value) {
  if (Array.isArray(value)) return value.map(sorted);
  if (value && typeof value === "object")
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((k) => [k, sorted(value[k])]),
    );
  return value;
}
function files(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((d) =>
    d.isDirectory() ? files(join(dir, d.name)) : [join(dir, d.name)],
  );
}
export async function contract(generate = false) {
  const temp = mkdtempSync(join(tmpdir(), "studio-contract-"));
  for (const service of ["inventory", "orders"]) {
    const port = await freePort(),
      child = launch(service, {
        port,
        db: join(temp, service + ".db"),
        log: "ignore",
        recovery: false,
      });
    try {
      await waitReady(`http://127.0.0.1:${port}/health/ready`, child);
      const response = await fetch(`http://127.0.0.1:${port}/openapi.json`);
      if (!response.ok) throw Error("OpenAPI export failed");
      const schema = await response.json();
      schema.servers = [{ url: "/" }];
      const text = JSON.stringify(sorted(schema), null, 2) + "\n";
      const target = join(ROOT, `contracts/${service}.openapi.json`);
      if (generate) writeFileSync(target, text);
      else if (!existsSync(target) || readFileSync(target, "utf8") !== text)
        throw Error(`${service} contract drift: run contract generate`);
    } finally {
      child.kill();
      await new Promise((r) =>
        child.exitCode !== null ? r() : child.once("exit", r),
      );
    }
  }
  if (generate) {
    npm(["run", "generate"], { cwd: join(ROOT, "web") });
    return;
  }
  const generated = join(temp, "generated");
  mkdirSync(generated);
  for (const service of ["inventory", "orders"]) {
    const out = join(generated, service);
    const dependencyRoot = process.env.HARNESS_DEPENDENCY_ROOT || ROOT;
    const generator = join(
      dependencyRoot,
      "web/node_modules/@hey-api/openapi-ts/bin/run.js",
    );
    const { run } = await import("./lib.mjs");
    run(
      process.execPath,
      [
        generator,
        "-i",
        join(ROOT, `contracts/${service}.openapi.json`),
        "-c",
        "@hey-api/client-fetch",
        "-o",
        out,
      ],
      { cwd: join(ROOT, "web") },
    );
    const old = join(ROOT, `web/src/api/generated/${service}`),
      names = files(out)
        .map((p) => relative(out, p))
        .sort(),
      expected = files(old)
        .map((p) => relative(old, p))
        .sort();
    if (
      JSON.stringify(names) !== JSON.stringify(expected) ||
      names.some(
        (n) =>
          readFileSync(join(out, n), "utf8").replaceAll("\r\n", "\n") !==
          readFileSync(join(old, n), "utf8").replaceAll("\r\n", "\n"),
      )
    )
      throw Error(`${service} SDK drift`);
  }
}
