import { test, expect, type Page } from "@playwright/test";
const id = "22222222-2222-4222-8222-222222222222";
const order = (status = "CONFIRMED") => ({
  order_id: id,
  product_id: "sku-demo-001",
  quantity: 2,
  status,
  rejection_code: null,
  needs_attention: false,
  cancel_requested_at: status === "CONFIRMED" ? null : "2026-11-03T01:00:00Z",
  cancelled_at: status === "CANCELLED" ? "2026-11-03T01:00:01Z" : null,
  created_at: "2026-11-03T00:00:00Z",
  updated_at: "2026-11-03T01:00:00Z",
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
            available_qty: 18,
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
    r.fulfill({ json: { items: [order()], total: 1, limit: 10, offset: 0 } }),
  );
  await page.goto("/");
  await page.locator("tbody tr").first().click();
}

test("释放未确认时只显示取消处理中，确认后才显示已取消", async ({ page }) => {
  await page.route("**/api/v1/orders/*/cancel", (r) =>
    r.fulfill({ status: 202, json: order("CANCEL_PENDING") }),
  );
  let queries = 0;
  await page.route("**/api/v1/orders/" + id, (r) =>
    r.fulfill({ json: order(++queries > 1 ? "CANCELLED" : "CANCEL_PENDING") }),
  );
  await fixture(page);
  await page.getByRole("button", { name: "取消订单并释放库存" }).click();
  await expect(page.getByRole("status")).toContainText("取消处理中");
  await expect(
    page.getByRole("button", { name: "取消订单并释放库存" }),
  ).toHaveCount(0);
  await expect(page.getByRole("status")).toContainText(
    "订单已取消，库存已释放",
    { timeout: 6500 },
  );
});

test("取消网络失败后重试针对同一订单", async ({ page }) => {
  const urls: string[] = [];
  await page.route("**/api/v1/orders/*/cancel", (r) => {
    urls.push(r.request().url());
    return urls.length === 1
      ? r.abort()
      : r.fulfill({ json: order("CANCELLED") });
  });
  await fixture(page);
  await page.getByRole("button", { name: "取消订单并释放库存" }).click();
  await expect(page.getByRole("alert")).toContainText("网络请求失败");
  await page.getByRole("button", { name: "取消订单并释放库存" }).click();
  await expect(page.getByRole("status")).toContainText("订单已取消");
  expect(urls).toHaveLength(2);
  expect(urls[0]).toBe(urls[1]);
});

test("服务拒绝取消时保留错误反馈，不伪装成功", async ({ page }) => {
  await page.route("**/api/v1/orders/*/cancel", (r) =>
    r.fulfill({
      status: 409,
      json: {
        error: {
          code: "ORDER_NOT_CANCELLABLE",
          message: "ORDER_NOT_CANCELLABLE",
          details: {},
        },
        request_id: id,
      },
    }),
  );
  await fixture(page);
  await page.getByRole("button", { name: "取消订单并释放库存" }).click();
  await expect(page.getByRole("alert")).toContainText("当前订单不能取消");
  await expect(page.getByRole("status")).toHaveCount(0);
});
