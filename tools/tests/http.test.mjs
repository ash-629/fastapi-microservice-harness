import { test } from "node:test";
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
import { ROOT, launch, waitReady } from "../lib.mjs";
import { freePort } from "../contract.mjs";

test("real Java HTTP services preserve validation, contracts, stock, cancellation, and restart recovery", async (t) => {
  const dir = mkdtempSync(join(tmpdir(), "studio-http-")),
    ip = await freePort(),
    op = await freePort();
  const base = `http://127.0.0.1:${op}`,
    inventory = `http://127.0.0.1:${ip}`;
  let stock = launch("inventory", {
      port: ip,
      db: join(dir, "inventory.db"),
      log: "ignore",
    }),
    orders;
  const stop = async (child) => {
    if (child && child.exitCode === null) {
      child.kill();
      await new Promise((r) => child.once("exit", r));
    }
  };
  const startOrders = async () => {
    orders = launch("orders", {
      port: op,
      db: join(dir, "orders.db"),
      inventoryUrl: inventory,
      log: "ignore",
    });
    await waitReady(base + "/health/ready", orders);
  };
  t.after(async () => {
    await stop(orders);
    await stop(stock);
  });
  await waitReady(inventory + "/health/ready", stock);
  await startOrders();
  const body = { product_id: "sku-demo-001", quantity: 2 },
    key = randomUUID(),
    rid = randomUUID();
  async function send(
    path,
    { method = "GET", body: payload, key: idem = key, ...rest } = {},
  ) {
    return fetch(base + path, {
      method,
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": idem,
        "X-Request-ID": rid,
      },
      ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
      ...rest,
    });
  }
  const ajv = new Ajv2020({ strict: false });
  addFormats(ajv);
  const schemas = {};
  for (const name of ["orders", "inventory"]) {
    const schema = JSON.parse(
      readFileSync(join(ROOT, `contracts/${name}.openapi.json`), "utf8"),
    );
    ajv.addSchema(schema, name);
    schemas[name] = schema;
  }
  function validate(name, model, value) {
    const check = ajv.compile({ $ref: `${name}#/components/schemas/${model}` });
    assert(check(value), JSON.stringify(check.errors));
  }
  await t.test(
    "health success responses are documented and match live payloads",
    async () => {
      for (const [name, url] of [
        ["orders", base],
        ["inventory", inventory],
      ]) {
        for (const path of ["/health/live", "/health/ready"]) {
          assert(schemas[name].paths[path].get.responses["200"]);
          const r = await fetch(url + path);
          assert.equal(r.status, 200);
          const value = await r.json();
          assert.equal(value.status, path.endsWith("live") ? "ok" : "ready");
          validate(name, "Health", value);
        }
        assert.equal(
          schemas[name].info.version,
          JSON.parse(readFileSync(join(ROOT, "package.json"), "utf8")).version,
        );
      }
    },
  );
  await t.test(
    "unsupported HTTP methods and media types keep client-error semantics",
    async () => {
      const method = await send("/api/v1/orders", { method: "PUT" });
      assert.equal(method.status, 405);
      assert(method.headers.get("allow").includes("GET"));
      const wrongBody = await fetch(base + "/api/v1/orders", {
        method: "POST",
        headers: {
          "Content-Type": "text/plain",
          "Idempotency-Key": randomUUID(),
          "X-Request-ID": rid,
        },
        body: "{}",
      });
      assert.equal(wrongBody.status, 415);
      const accept = await send("/api/v1/orders", {
        headers: { Accept: "text/plain", "X-Request-ID": rid },
      });
      assert.equal(accept.status, 406);
      for (const [r, code] of [
        [method, "METHOD_NOT_ALLOWED"],
        [wrongBody, "UNSUPPORTED_MEDIA_TYPE"],
        [accept, "NOT_ACCEPTABLE"],
      ]) {
        const value = await r.json();
        assert.equal(value.error.code, code);
        assert.equal(value.request_id, rid);
        validate("orders", "Error", value);
      }
    },
  );
  await t.test("strict input and uniform errors", async () => {
    for (const quantity of [0, 100, -1, 1.5, true, "2", null]) {
      const r = await send("/api/v1/orders", {
        method: "POST",
        body: { ...body, quantity },
        key: randomUUID(),
      });
      assert.equal(r.status, 422);
      const error = await r.json();
      assert.equal(error.error.code, "VALIDATION_ERROR");
      assert.equal(error.request_id, rid);
      validate("orders", "Error", error);
    }
    for (const payload of [
      { ...body, product_id: "   " },
      { ...body, product_id: 123 },
      { ...body, product_id: true },
      { ...body, product_id: "x".repeat(81) },
      { ...body, extra: 1 },
    ])
      assert.equal(
        (await send("/api/v1/orders", { method: "POST", body: payload }))
          .status,
        422,
      );
    assert.equal(
      (await send("/api/v1/orders", { method: "POST", body, key: "not-uuid" }))
        .status,
      422,
    );
    assert.equal((await send("/api/v1/orders?status=UNKNOWN")).status, 422);
    assert.equal((await send("/api/v1/orders?limit=101")).status, 422);
    assert.equal((await send("/api/v1/orders?offset=-1")).status, 422);
    assert.equal((await send("/api/v1/orders/not-uuid")).status, 422);
    assert.equal((await send("/api/v1/orders/" + randomUUID())).status, 404);
  });
  let id;
  await t.test(
    "real reserve, idempotent create, changed-key conflict and cancellation",
    async () => {
      const response = await send("/api/v1/orders", { method: "POST", body });
      assert.equal(response.status, 201);
      assert.equal(response.headers.get("x-request-id"), rid);
      const first = await response.json();
      id = first.order_id;
      validate("orders", "Order", first);
      assert.equal(first.status, "CONFIRMED");
      assert.equal(
        (
          await (
            await fetch(inventory + "/api/v1/products/sku-demo-001")
          ).json()
        ).available_qty,
        18,
      );
      const replay = await send("/api/v1/orders", { method: "POST", body });
      assert.equal(replay.status, 200);
      assert.equal((await replay.json()).order_id, id);
      assert.equal(
        (
          await send("/api/v1/orders", {
            method: "POST",
            body: { ...body, quantity: 3 },
          })
        ).status,
        409,
      );
      const cancelled = await send(`/api/v1/orders/${id}/cancel`, {
        method: "POST",
      });
      assert.equal(cancelled.status, 200);
      const final = await cancelled.json();
      assert.equal(final.status, "CANCELLED");
      validate("orders", "Order", final);
      assert.equal(
        (
          await (
            await send(`/api/v1/orders/${id}/cancel`, { method: "POST" })
          ).json()
        ).cancelled_at,
        final.cancelled_at,
      );
      assert.equal(
        (await (await send("/api/v1/orders", { method: "POST", body })).json())
          .status,
        "CANCELLED",
      );
      assert.equal(
        (
          await (
            await fetch(inventory + "/api/v1/products/sku-demo-001")
          ).json()
        ).available_qty,
        20,
      );
      const page = await (
        await send("/api/v1/orders?status=CANCELLED&limit=1")
      ).json();
      assert.equal(page.total, 1);
      assert.equal(page.items.length, 1);
      validate("orders", "OrderPage", page);
      validate(
        "inventory",
        "ProductPage",
        await (await fetch(inventory + "/api/v1/products")).json(),
      );
    },
  );
  await t.test("business rejections return stable HTTP errors", async () => {
    const r = await send("/api/v1/orders", {
      method: "POST",
      body: { ...body, quantity: 99 },
      key: randomUUID(),
    });
    assert.equal(r.status, 409);
    const error = await r.json();
    assert.equal(error.error.code, "INSUFFICIENT_STOCK");
    assert.equal(
      (
        await send(`/api/v1/orders/${error.error.details.order_id}/cancel`, {
          method: "POST",
        })
      ).status,
      409,
    );
    assert.equal(
      (
        await send("/api/v1/orders", {
          method: "POST",
          body: { product_id: "missing", quantity: 1 },
          key: randomUUID(),
        })
      ).status,
      404,
    );
  });
  await t.test(
    "pending order and pending cancellation recover after actual process restart",
    async () => {
      await stop(stock);
      const pending = await send("/api/v1/orders", {
        method: "POST",
        body,
        key: randomUUID(),
      });
      assert.equal(pending.status, 202);
      const order = await pending.json();
      assert.equal(order.status, "PENDING_INVENTORY");
      await stop(orders);
      stock = launch("inventory", {
        port: ip,
        db: join(dir, "inventory.db"),
        log: "ignore",
      });
      await waitReady(inventory + "/health/ready", stock);
      await startOrders();
      async function until(id, state) {
        for (let i = 0; i < 60; i++) {
          const r = await (await send("/api/v1/orders/" + id)).json();
          if (r.status === state) return r;
          await new Promise((r) => setTimeout(r, 250));
        }
        assert.fail("Recovery timed out: " + state);
      }
      await until(order.order_id, "CONFIRMED");
      await stop(stock);
      assert.equal(
        (
          await send(`/api/v1/orders/${order.order_id}/cancel`, {
            method: "POST",
          })
        ).status,
        202,
      );
      await stop(orders);
      stock = launch("inventory", {
        port: ip,
        db: join(dir, "inventory.db"),
        log: "ignore",
      });
      await waitReady(inventory + "/health/ready", stock);
      await startOrders();
      await until(order.order_id, "CANCELLED");
      assert.equal(
        (
          await (
            await fetch(inventory + "/api/v1/products/sku-demo-001")
          ).json()
        ).available_qty,
        20,
      );
    },
  );
});
