import { test, expect, type Page } from "@playwright/test";

const order = (
  status = "CONFIRMED",
  id = "11111111-1111-4111-8111-111111111111",
) => ({
  order_id: id,
  product_id: "sku-demo-001",
  quantity: 1,
  status,
  rejection_code: null,
  needs_attention: false,
  created_at: "2026-11-03T00:00:00Z",
  updated_at: "2026-11-03T00:00:00Z",
});

async function fixture(page: Page) {
  await page.route("**/api/v1/products", (r) =>
    r.fulfill({
      json: {
        items: [
          {
            product_id: "sku-demo-001",
            sku: "DEMO-1",
            name: "机械键盘",
            available_qty: 20,
            updated_at: "2026-11-03T00:00:00Z",
          },
        ],
        total: 1,
        limit: 20,
        offset: 0,
      },
    }),
  );
  await page.route("**/api/v1/orders?**", (r) =>
    r.fulfill({ json: { items: [], total: 0, limit: 10, offset: 0 } }),
  );
}

test("损坏的浏览器存储不会锁死提交", async ({ page }) => {
  await fixture(page);
  await page.addInitScript(() =>
    sessionStorage.setItem("pending-order", "{broken"),
  );
  await page.route("**/api/v1/orders", (r) =>
    r.fulfill({ status: 201, json: order() }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "确认创建订单" }).click();
  await expect(page.getByRole("status")).toContainText("订单已确认", {
    timeout: 4000,
  });
  await expect(
    page.getByRole("button", { name: "确认创建订单" }),
  ).toBeEnabled();
});

test("迟到的旧列表响应不能覆盖新筛选", async ({ page }) => {
  await fixture(page);
  await page.route("**/api/v1/orders?**", async (r) => {
    const filtered = new URL(r.request().url()).searchParams.get("status");
    if (!filtered) await new Promise((resolve) => setTimeout(resolve, 700));
    await r.fulfill({
      json: {
        items: [order(filtered ? "CONFIRMED" : "REJECTED")],
        total: 1,
        limit: 10,
        offset: 0,
      },
    });
  });
  await page.goto("/");
  const oldResponse = page.waitForResponse(
    (r) => r.url().includes("/api/v1/orders?") && !r.url().includes("status="),
  );
  await page.getByLabel("订单状态").selectOption("CONFIRMED");
  await expect(page.locator("tbody")).toContainText("已确认");
  await oldResponse;
  await expect(page.locator("tbody")).not.toContainText("已拒绝");
});

test("处理中订单完成后同步提示和详情", async ({ page }) => {
  await fixture(page);
  await page.route("**/api/v1/orders", (r) =>
    r.fulfill({ status: 202, json: order("PENDING_INVENTORY") }),
  );
  await page.route("**/api/v1/orders/*", (r) => r.fulfill({ json: order() }));
  await page.goto("/");
  await page.getByRole("button", { name: "确认创建订单" }).click();
  await expect(page.getByRole("status")).toContainText("订单已确认", {
    timeout: 5000,
  });
});

test("关闭详情后旧轮询不能重新打开详情", async ({ page }) => {
  await fixture(page);
  await page.route("**/api/v1/orders", (r) =>
    r.fulfill({ status: 202, json: order("PENDING_INVENTORY") }),
  );
  await page.route("**/api/v1/orders/*", (r) => r.fulfill({ json: order() }));
  await page.goto("/");
  await page.getByRole("button", { name: "确认创建订单" }).click();
  await page.getByRole("button", { name: "关闭详情" }).click();
  // 超过首次轮询间隔后仍保持关闭。
  await page.waitForTimeout(1800);
  await expect(page.getByRole("heading", { name: "订单详情" })).toHaveCount(0);
});

test("网络失败后重试沿用同一幂等键", async ({ page }) => {
  await fixture(page);
  const keys: string[] = [];
  await page.route("**/api/v1/orders", async (r) => {
    keys.push(r.request().headers()["idempotency-key"]);
    if (keys.length === 1) await r.abort();
    else await r.fulfill({ status: 201, json: order() });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "确认创建订单" }).click();
  await expect(page.getByRole("alert")).toContainText("网络请求失败");
  await page.getByRole("button", { name: "确认创建订单" }).click();
  await expect(page.getByRole("status")).toContainText("订单已确认");
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
});

test("移动端长文本不会溢出页面或执行HTML", async ({ page }) => {
  await fixture(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/v1/products", (r) =>
    r.fulfill({
      json: {
        items: [
          {
            product_id: "sku-demo-001",
            sku: "LONG",
            name: "<img src=x onerror=alert(1)>" + "a".repeat(150),
            available_qty: 20,
            updated_at: "2026-11-03T00:00:00Z",
          },
        ],
        total: 1,
        limit: 20,
        offset: 0,
      },
    }),
  );
  await page.goto("/");
  await expect(page.locator(".product")).toHaveCount(1);
  await expect(page.locator(".product img")).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
