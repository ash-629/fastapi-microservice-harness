import { http, HttpResponse } from "msw";
import type {
  Order,
  OrderPage,
  Error as ApiError,
} from "../api/generated/orders/types.gen";
import type { ProductPage } from "../api/generated/inventory/types.gen";
export function createHandlers(origin = "", pending = false) {
  const product: ProductPage = {
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
  };
  const rows: Order[] = [];
  const keys = new Map<string, { body: string; row: Order }>();
  const error = (
    code: string,
    status: number,
    details: Record<string, unknown> = {},
  ) =>
    HttpResponse.json(
      {
        error: { code, message: code, details },
        request_id: crypto.randomUUID(),
      } satisfies ApiError,
      { status },
    );
  const result = (row: Order, fresh: boolean) =>
    row.status === "REJECTED"
      ? error(
          row.rejection_code!,
          row.rejection_code === "PRODUCT_NOT_FOUND" ? 404 : 409,
          { order_id: row.order_id },
        )
      : HttpResponse.json(row, {
          status: row.status === "PENDING_INVENTORY" ? 202 : fresh ? 201 : 200,
        });
  return [
    http.get(origin + "/api/v1/products", () => HttpResponse.json(product)),
    http.get(origin + "/api/v1/orders", ({ request }) => {
      const q = new URL(request.url).searchParams,
        status = q.get("status"),
        limit = Number(q.get("limit") ?? 20),
        offset = Number(q.get("offset") ?? 0);
      if (
        (status &&
          !["CONFIRMED", "REJECTED", "PENDING_INVENTORY"].includes(status)) ||
        !Number.isInteger(limit) ||
        limit < 1 ||
        limit > 100 ||
        !Number.isInteger(offset) ||
        offset < 0
      )
        return error("VALIDATION_ERROR", 422);
      const filtered = rows.filter((x) => !status || x.status === status);
      const data: OrderPage = {
        items: filtered.slice(offset, offset + limit),
        total: filtered.length,
        limit,
        offset,
      };
      return HttpResponse.json(data);
    }),
    http.post(origin + "/api/v1/orders", async ({ request }) => {
      let raw: unknown;
      try {
        raw = await request.json();
      } catch {
        return error("VALIDATION_ERROR", 422);
      }
      const b = raw as { product_id?: unknown; quantity?: unknown };
      const key = request.headers.get("idempotency-key");
      if (
        !b ||
        typeof b.product_id !== "string" ||
        !b.product_id.trim() ||
        b.product_id.trim().length > 80 ||
        typeof b.quantity !== "number" ||
        !Number.isInteger(b.quantity) ||
        b.quantity < 1 ||
        b.quantity > 99 ||
        Object.keys(b).some((k) => !["product_id", "quantity"].includes(k)) ||
        !key ||
        !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
          key,
        )
      )
        return error("VALIDATION_ERROR", 422);
      const body = JSON.stringify({
        product_id: b.product_id.trim(),
        quantity: b.quantity,
      });
      const previous = keys.get(key.toLowerCase());
      if (previous)
        return previous.body !== body
          ? error("IDEMPOTENCY_CONFLICT", 409)
          : result(previous.row, false);
      const code =
        b.product_id.trim() !== "sku-demo-001"
          ? "PRODUCT_NOT_FOUND"
          : b.quantity > product.items[0].available_qty
            ? "INSUFFICIENT_STOCK"
            : null;
      const row: Order = {
        order_id: crypto.randomUUID(),
        product_id: b.product_id.trim(),
        quantity: b.quantity,
        status: code ? "REJECTED" : pending ? "PENDING_INVENTORY" : "CONFIRMED",
        rejection_code: code,
        needs_attention: false,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      if (row.status === "CONFIRMED")
        product.items[0].available_qty -= b.quantity;
      keys.set(key.toLowerCase(), { body, row });
      rows.unshift(row);
      return result(row, true);
    }),
    http.get(origin + "/api/v1/orders/:id", ({ params }) => {
      const row = rows.find((x) => x.order_id === params.id);
      return row ? HttpResponse.json(row) : error("ORDER_NOT_FOUND", 404);
    }),
  ];
}
export const handlers = createHandlers();
