import { test, expect } from "@playwright/test";
test("工作台空态与筛选", async ({ page }) => {
  await page.route("**/api/v1/products", (r) =>
    r.fulfill({ json: { items: [], total: 0, limit: 20, offset: 0 } }),
  );
  await page.route("**/api/v1/orders?**", (r) =>
    r.fulfill({ json: { items: [], total: 0, limit: 10, offset: 0 } }),
  );
  await page.goto("/");
  await expect(page.getByText("暂无商品", { exact: true })).toBeVisible();
  await page.getByLabel("订单状态").selectOption("CONFIRMED");
  await expect(page.getByText("暂无符合条件的订单")).toBeVisible();
});

test("真实服务下单、取消和库存联动", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByText("机械键盘", { exact: true }).first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "确认创建订单" }).click();
  await expect(page.getByRole("status")).toContainText("订单已确认");
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await expect(page.locator(".product").first()).toContainText("19");
  await page.getByRole("button", { name: "取消订单并释放库存" }).click();
  await expect(page.getByRole("status")).toContainText(
    "订单已取消，库存已释放",
  );
  await expect(page.locator(".product").first()).toContainText("20");
  await expect(page.locator("tbody tr")).toContainText("已取消");
  await expect(
    page.getByRole("button", { name: "取消订单并释放库存" }),
  ).toHaveCount(0);
  await page.getByLabel("订单状态").selectOption("CANCELLED");
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await page.screenshot({ path: "test-results/workspace.png", fullPage: true });
});
