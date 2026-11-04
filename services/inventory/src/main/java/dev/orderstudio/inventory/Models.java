package dev.orderstudio.inventory;

import io.swagger.v3.oas.annotations.media.Schema;
import java.util.*;

public final class Models {
  private Models() {}

  public enum ReservationState {
    RESERVED,
    REJECTED,
    RELEASED
  }

  @Schema(
      name = "Product",
      requiredProperties = {"product_id", "sku", "name", "available_qty", "updated_at"})
  public record Product(
      String product_id, String sku, String name, int available_qty, String updated_at) {
    static Product from(Map<String, Object> row) {
      return new Product(
          (String) row.get("product_id"),
          (String) row.get("sku"),
          (String) row.get("name"),
          ((Number) row.get("available_qty")).intValue(),
          (String) row.get("updated_at"));
    }
  }

  @Schema(
      name = "ProductPage",
      requiredProperties = {"items", "total", "limit", "offset"})
  public record ProductPage(List<Product> items, int total, int limit, int offset) {}

  @Schema(
      name = "Reservation",
      requiredProperties = {"order_id", "product_id", "quantity", "status", "rejection_code"})
  public record Reservation(
      String order_id,
      String product_id,
      int quantity,
      ReservationState status,
      @Schema(nullable = true) String rejection_code) {
    static Reservation from(Map<String, Object> row) {
      return new Reservation(
          (String) row.get("order_id"),
          (String) row.get("product_id"),
          ((Number) row.get("quantity")).intValue(),
          ReservationState.valueOf((String) row.get("status")),
          (String) row.get("rejection_code"));
    }
  }
}
