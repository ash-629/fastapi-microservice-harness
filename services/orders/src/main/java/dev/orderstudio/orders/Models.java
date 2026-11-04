package dev.orderstudio.orders;

import io.swagger.v3.oas.annotations.media.Schema;
import java.util.*;

public final class Models {
  private Models() {}

  public enum OrderState {
    PENDING_INVENTORY,
    CONFIRMED,
    REJECTED,
    CANCEL_PENDING,
    CANCELLED
  }

  @Schema(
      name = "Order",
      requiredProperties = {
        "order_id",
        "product_id",
        "quantity",
        "status",
        "rejection_code",
        "needs_attention",
        "created_at",
        "updated_at"
      })
  public record Order(
      String order_id,
      String product_id,
      int quantity,
      OrderState status,
      @Schema(nullable = true) String rejection_code,
      boolean needs_attention,
      @Schema(nullable = true) String cancel_requested_at,
      @Schema(nullable = true) String cancelled_at,
      String created_at,
      String updated_at) {
    static Order from(Map<String, Object> row) {
      return new Order(
          (String) row.get("order_id"),
          (String) row.get("product_id"),
          ((Number) row.get("quantity")).intValue(),
          OrderState.valueOf((String) row.get("status")),
          (String) row.get("rejection_code"),
          ((Number) row.get("needs_attention")).intValue() != 0,
          (String) row.get("cancel_requested_at"),
          (String) row.get("cancelled_at"),
          (String) row.get("created_at"),
          (String) row.get("updated_at"));
    }
  }

  @Schema(
      name = "OrderPage",
      requiredProperties = {"items", "total", "limit", "offset"})
  public record OrderPage(List<Order> items, int total, int limit, int offset) {}
}
