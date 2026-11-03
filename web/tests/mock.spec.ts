import { test, expect } from "@playwright/test";
import { setupServer } from "msw/node";
import { createHandlers } from "../src/mocks/handlers";
test("MSW契约：幂等、库存、冲突、校验、筛选分页与404", async () => {
  const server = setupServer(...createHandlers("http://mock.test"));
  server.listen({ onUnhandledRequest: "error" });
  try {
    const body = { product_id: "sku-demo-001", quantity: 2 };
    const headers = {
      "Content-Type": "application/json",
      "Idempotency-Key": crypto.randomUUID(),
    };
    const post = (value: unknown, key = headers) =>
      fetch("http://mock.test/api/v1/orders", {
        method: "POST",
        headers: key,
        body: JSON.stringify(value),
      });
    const first = await post(body);
    expect(first.status).toBe(201);
    const row = await first.json();
    const repeated = await post(body);
    expect(repeated.status).toBe(200);
    expect((await repeated.json()).order_id).toBe(row.order_id);
    expect((await post({ ...body, quantity: 3 })).status).toBe(409);
    expect((await post({ ...body, quantity: 0 })).status).toBe(422);
    const stock = await (
      await fetch("http://mock.test/api/v1/products")
    ).json();
    expect(stock.items[0].available_qty).toBe(18);
    const page = await (
      await fetch(
        "http://mock.test/api/v1/orders?status=CONFIRMED&limit=1&offset=1",
      )
    ).json();
    expect(page.total).toBe(1);
    expect(page.items).toEqual([]);
    expect(
      (await fetch("http://mock.test/api/v1/orders?status=BAD")).status,
    ).toBe(422);
    const missing = await fetch("http://mock.test/api/v1/orders/missing");
    expect(missing.status).toBe(404);
    expect((await missing.json()).error.code).toBe("ORDER_NOT_FOUND");
  } finally {
    server.close();
  }
});
