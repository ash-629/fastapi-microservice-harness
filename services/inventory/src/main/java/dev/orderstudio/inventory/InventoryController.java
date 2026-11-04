package dev.orderstudio.inventory;

import static dev.orderstudio.inventory.Models.*;

import dev.orderstudio.common.Api;
import dev.orderstudio.common.Api.StockRequest;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.media.*;
import io.swagger.v3.oas.annotations.responses.*;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.util.Map;
import org.springframework.web.bind.annotation.*;

@RestController
@ApiResponses({
  @ApiResponse(
      responseCode = "404",
      content = @Content(schema = @Schema(implementation = Api.ErrorEnvelope.class))),
  @ApiResponse(
      responseCode = "409",
      content = @Content(schema = @Schema(implementation = Api.ErrorEnvelope.class))),
  @ApiResponse(
      responseCode = "422",
      content = @Content(schema = @Schema(implementation = Api.ErrorEnvelope.class))),
  @ApiResponse(
      responseCode = "500",
      content = @Content(schema = @Schema(implementation = Api.ErrorEnvelope.class))),
  @ApiResponse(
      responseCode = "503",
      content = @Content(schema = @Schema(implementation = Api.ErrorEnvelope.class)))
})
public class InventoryController {
  private final InventoryService service;

  public InventoryController(InventoryService service) {
    this.service = service;
  }

  @GetMapping("/health/live")
  @Operation(operationId = "live")
  public Map<String, String> live() {
    return Map.of("status", "ok");
  }

  @GetMapping("/health/ready")
  @Operation(operationId = "ready")
  public Map<String, String> ready() {
    service.ready();
    return Map.of("status", "ready");
  }

  @GetMapping("/api/v1/products")
  @Operation(operationId = "list_products")
  @ApiResponse(
      responseCode = "200",
      content = @Content(schema = @Schema(implementation = ProductPage.class)))
  public ProductPage products(
      @RequestParam(defaultValue = "20") @Min(1) @Max(100) int limit,
      @RequestParam(defaultValue = "0") @Min(0) int offset) {
    return service.products(limit, offset);
  }

  @GetMapping("/api/v1/products/{product_id}")
  @Operation(operationId = "get_product")
  @ApiResponse(
      responseCode = "200",
      content = @Content(schema = @Schema(implementation = Product.class)))
  public Product product(@PathVariable String product_id) {
    return service.product(product_id);
  }

  @PutMapping("/internal/v1/reservations/{order_id}")
  @Operation(operationId = "put_reservation")
  @ApiResponse(
      responseCode = "200",
      content = @Content(schema = @Schema(implementation = Reservation.class)))
  public Reservation reserve(@PathVariable String order_id, @Valid @RequestBody StockRequest req) {
    return service.reserve(Api.uuid(order_id), req);
  }

  @PutMapping("/internal/v1/reservations/{order_id}/release")
  @Operation(operationId = "release_reservation")
  @ApiResponse(
      responseCode = "200",
      content = @Content(schema = @Schema(implementation = Reservation.class)))
  public Reservation release(@PathVariable String order_id, @Valid @RequestBody StockRequest req) {
    return service.release(Api.uuid(order_id), req);
  }

  @GetMapping("/internal/v1/reservations/{order_id}")
  @Operation(operationId = "get_reservation")
  @ApiResponse(
      responseCode = "200",
      content = @Content(schema = @Schema(implementation = Reservation.class)))
  public Reservation reservation(@PathVariable String order_id) {
    return service.reservation(Api.uuid(order_id));
  }
}
