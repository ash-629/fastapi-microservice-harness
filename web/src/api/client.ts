import { listProducts } from "./generated/inventory/sdk.gen";
import { listOrders, getOrder, createOrder } from "./generated/orders/sdk.gen";
import type { Order } from "./generated/orders/types.gen";
export type { Order };
export class ApiError extends Error {
  constructor(
    message: string,
    public code?: string,
  ) {
    super(message);
  }
}
const messages: Record<string, string> = {
  INSUFFICIENT_STOCK: "库存不足，请调整数量",
  PRODUCT_NOT_FOUND: "商品不存在，请刷新商品列表",
  ORDER_NOT_FOUND: "订单不存在",
  IDEMPOTENCY_CONFLICT: "操作内容与原请求不一致，请重新提交",
  VALIDATION_ERROR: "输入不符合要求，请检查商品和数量",
  STORAGE_UNAVAILABLE: "服务暂时不可用，请稍后使用相同操作重试",
};
async function call<T>(
  op: (signal: AbortSignal) => Promise<{ data?: T }>,
): Promise<T> {
  try {
    const result = await op(AbortSignal.timeout(8000));
    if (result.data === undefined)
      throw new ApiError("服务返回了无法识别的数据");
    return result.data;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    const envelope = e as { error?: { message?: string; code?: string } };
    const code = envelope?.error?.code;
    throw new ApiError(
      (code && messages[code]) ||
        envelope?.error?.message ||
        "网络请求失败，请稍后重试",
      code,
    );
  }
}
export const products = () =>
  call((signal) => listProducts({ throwOnError: true, signal }));
export const orders = (status: Order["status"] | "", offset = 0) =>
  call((signal) =>
    listOrders({
      throwOnError: true,
      signal,
      query: { limit: 10, offset, status: status || undefined },
    }),
  );
export const detail = (id: string) =>
  call((signal) =>
    getOrder({ throwOnError: true, signal, path: { order_id: id } }),
  );
export const create = (product_id: string, quantity: number, key: string) =>
  call((signal) =>
    createOrder({
      throwOnError: true,
      signal,
      headers: { "idempotency-key": key },
      body: { product_id, quantity },
    }),
  );
