package dev.orderstudio.orders;

import static dev.orderstudio.orders.Models.*;

import dev.orderstudio.common.Api;
import dev.orderstudio.common.Api.*;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.media.*;
import io.swagger.v3.oas.annotations.responses.*;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.util.*;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@ApiResponses({
  @ApiResponse(
      responseCode = "405",
      content = @Content(schema = @Schema(implementation = ErrorEnvelope.class))),
  @ApiResponse(
      responseCode = "406",
      content = @Content(schema = @Schema(implementation = ErrorEnvelope.class))),
  @ApiResponse(
      responseCode = "415",
      content = @Content(schema = @Schema(implementation = ErrorEnvelope.class))),
  @ApiResponse(
      responseCode = "404",
      content = @Content(schema = @Schema(implementation = ErrorEnvelope.class))),
  @ApiResponse(
      responseCode = "409",
      content = @Content(schema = @Schema(implementation = ErrorEnvelope.class))),
  @ApiResponse(
      responseCode = "422",
      content = @Content(schema = @Schema(implementation = ErrorEnvelope.class))),
  @ApiResponse(
      responseCode = "500",
      content = @Content(schema = @Schema(implementation = ErrorEnvelope.class))),
  @ApiResponse(
      responseCode = "503",
      content = @Content(schema = @Schema(implementation = ErrorEnvelope.class)))
})
public class OrderController {
  private final OrderService service;

  public OrderController(OrderService service) {
    this.service = service;
  }

  @GetMapping("/health/live")
  @Operation(operationId = "live")
  @ApiResponse(
      responseCode = "200",
      content = @Content(schema = @Schema(implementation = Api.Health.class)))
  public Api.Health live() {
    return new Api.Health("ok");
  }

  @GetMapping("/health/ready")
  @Operation(operationId = "ready")
  @ApiResponse(
      responseCode = "200",
      content = @Content(schema = @Schema(implementation = Api.Health.class)))
  public Api.Health ready() {
    service.ready();
    return new Api.Health("ready");
  }

  @PostMapping("/api/v1/orders")
  @Operation(operationId = "create_order")
  @ApiResponses({
    @ApiResponse(
        responseCode = "201",
        content = @Content(schema = @Schema(implementation = Order.class))),
    @ApiResponse(
        responseCode = "200",
        content = @Content(schema = @Schema(implementation = Order.class))),
    @ApiResponse(
        responseCode = "202",
        content = @Content(schema = @Schema(implementation = Order.class)))
  })
  public ResponseEntity<Order> create(
      @Valid @RequestBody StockRequest req,
      @RequestHeader("idempotency-key") String key,
      HttpServletRequest request) {
    var created = service.create(Api.uuid(key), req);
    var row = service.advance(created.row(), (String) request.getAttribute("request_id"), false);
    var order = Order.from(row);
    if (order.status() == OrderState.REJECTED)
      throw new Failure(
          order.rejection_code().equals("PRODUCT_NOT_FOUND") ? 404 : 409,
          order.rejection_code(),
          Map.of("order_id", order.order_id()));
    int status =
        Set.of(OrderState.PENDING_INVENTORY, OrderState.CANCEL_PENDING).contains(order.status())
            ? 202
            : created.fresh() ? 201 : 200;
    return ResponseEntity.status(status)
        .header("Location", "/api/v1/orders/" + order.order_id())
        .header("Retry-After", "1")
        .body(order);
  }

  @PostMapping("/api/v1/orders/{order_id}/cancel")
  @Operation(operationId = "cancel_order")
  @ApiResponses({
    @ApiResponse(
        responseCode = "200",
        content = @Content(schema = @Schema(implementation = Order.class))),
    @ApiResponse(
        responseCode = "202",
        content = @Content(schema = @Schema(implementation = Order.class)))
  })
  public ResponseEntity<Order> cancel(@PathVariable String order_id, HttpServletRequest request) {
    var row =
        service.advance(
            service.requestCancel(Api.uuid(order_id)),
            (String) request.getAttribute("request_id"),
            false);
    var order = Order.from(row);
    var response =
        ResponseEntity.status(order.status() == OrderState.CANCEL_PENDING ? 202 : 200)
            .header("Location", "/api/v1/orders/" + order.order_id());
    if (order.status() == OrderState.CANCEL_PENDING) response.header("Retry-After", "1");
    return response.body(order);
  }

  @GetMapping("/api/v1/orders")
  @Operation(operationId = "list_orders")
  @ApiResponse(
      responseCode = "200",
      content = @Content(schema = @Schema(implementation = OrderPage.class)))
  public OrderPage list(
      @RequestParam(required = false) OrderState status,
      @RequestParam(defaultValue = "20") @Min(1) @Max(100) int limit,
      @RequestParam(defaultValue = "0") @Min(0) int offset) {
    return service.list(status, limit, offset);
  }

  @GetMapping("/api/v1/orders/{order_id}")
  @Operation(operationId = "get_order")
  @ApiResponse(
      responseCode = "200",
      content = @Content(schema = @Schema(implementation = Order.class)))
  public Order get(@PathVariable String order_id) {
    return Order.from(service.get(Api.uuid(order_id)));
  }
}
