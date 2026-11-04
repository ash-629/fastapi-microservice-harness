package dev.orderstudio.orders;

import static dev.orderstudio.common.Database.*;
import static org.junit.jupiter.api.Assertions.*;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.orderstudio.common.*;
import dev.orderstudio.common.Api.*;
import java.nio.file.Path;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class OrderServiceTest {
  @TempDir Path temp;
  ObjectMapper mapper = new ObjectMapper();

  StockRequest req() {
    return new StockRequest("sku-demo-001", 2);
  }

  OrderService service(InventoryGateway gateway) {
    return new OrderService(temp.resolve("orders.db").toString(), mapper, gateway, false);
  }

  InventoryGateway.Reply result(String id, String state) {
    return new InventoryGateway.Reply(
        200,
        "{\"order_id\":\""
            + id
            + "\",\"product_id\":\"sku-demo-001\",\"quantity\":2,\"status\":\""
            + state
            + "\",\"rejection_code\":null}");
  }

  OrderService normal() {
    return service((id, release, r, rid) -> result(id, release ? "RELEASED" : "RESERVED"));
  }

  Map<String, Object> create(OrderService s) {
    return s.create(UUID.randomUUID().toString(), req()).row();
  }

  @Test
  void sameKeyCreatesOneOrderEvenConcurrently() throws Exception {
    var s = normal();
    String key = UUID.randomUUID().toString();
    try (var pool = Executors.newFixedThreadPool(8)) {
      var work = new ArrayList<Callable<OrderService.Created>>();
      for (int i = 0; i < 16; i++) work.add(() -> s.create(key, req()));
      Set<Object> ids = new HashSet<>();
      int fresh = 0;
      for (var result : pool.invokeAll(work)) {
        var item = result.get();
        ids.add(item.row().get("order_id"));
        if (item.fresh()) fresh++;
      }
      assertEquals(1, ids.size());
      assertEquals(1, fresh);
    }
    assertThrows(Failure.class, () -> s.create(key, new StockRequest("sku-demo-001", 3)));
  }

  @Test
  void cancellationIsIdempotentAndKeepsIntentAndTerminalTimes() {
    var s = normal();
    var order = s.advance(create(s), "", false);
    String id = (String) order.get("order_id");
    var intent = s.requestCancel(id);
    var cancelled = s.advance(intent, "", false);
    assertEquals("CANCELLED", cancelled.get("status"));
    assertEquals(intent.get("cancel_requested_at"), cancelled.get("cancel_requested_at"));
    assertEquals(cancelled, s.advance(s.requestCancel(id), "", false));
  }

  @Test
  void concurrentCancelPreservesOneIntent() throws Exception {
    var s = normal();
    String id = (String) s.advance(create(s), "", false).get("order_id");
    try (var pool = Executors.newFixedThreadPool(8)) {
      List<Callable<Map<String, Object>>> work = new ArrayList<>();
      for (int i = 0; i < 16; i++) work.add(() -> s.requestCancel(id));
      Set<Object> times = new HashSet<>();
      for (var result : pool.invokeAll(work)) times.add(result.get().get("cancel_requested_at"));
      assertEquals(1, times.size());
    }
  }

  @ParameterizedTest
  @ValueSource(strings = {"PENDING_INVENTORY", "REJECTED"})
  void invalidStateCannotCancel(String state) {
    var s = normal();
    String id = (String) create(s).get("order_id");
    s.db.write(
        c -> {
          update(c, "UPDATE orders SET status=? WHERE order_id=?", state, id);
          return null;
        });
    assertEquals(
        "ORDER_NOT_CANCELLABLE",
        assertThrows(Failure.class, () -> s.requestCancel(id)).getMessage());
  }

  @Test
  void missingOrderIs404() {
    assertEquals(
        404,
        assertThrows(Failure.class, () -> normal().requestCancel(UUID.randomUUID().toString()))
            .status);
  }

  @ParameterizedTest
  @ValueSource(
      strings = {
        "invalid-json",
        "string-quantity",
        "unknown-error",
        "wrong-order",
        "wrong-product",
        "wrong-quantity",
        "released",
        "missing-code",
        "http-503"
      })
  void untrustedReservationNeverConfirms(String bad) {
    var s =
        service(
            (id, release, req, rid) -> {
              String json = result(id, "RESERVED").body();
              return switch (bad) {
                case "invalid-json" -> new InventoryGateway.Reply(200, "not-json");
                case "http-503" -> new InventoryGateway.Reply(503, "{}");
                case "string-quantity" ->
                    new InventoryGateway.Reply(
                        200, json.replace("\"quantity\":2", "\"quantity\":\"2\""));
                case "unknown-error" ->
                    new InventoryGateway.Reply(
                        200, json.replace("RESERVED", "REJECTED").replace("null", "\"UNKNOWN\""));
                case "wrong-order" -> result(UUID.randomUUID().toString(), "RESERVED");
                case "wrong-product" ->
                    new InventoryGateway.Reply(200, json.replace("sku-demo-001", "other"));
                case "wrong-quantity" ->
                    new InventoryGateway.Reply(
                        200, json.replace("\"quantity\":2", "\"quantity\":3"));
                case "released" -> result(id, "RELEASED");
                default ->
                    new InventoryGateway.Reply(200, json.replace(",\"rejection_code\":null", ""));
              };
            });
    var row = s.advance(create(s), "", true);
    assertEquals("PENDING_INVENTORY", row.get("status"));
    assertEquals(
        bad.equals("http-503") ? "DOWNSTREAM_UNAVAILABLE" : "DOWNSTREAM_CONTRACT_ERROR",
        row.get("last_error_code"));
  }

  @ParameterizedTest
  @ValueSource(
      strings = {
        "wrong-order",
        "wrong-product",
        "wrong-quantity",
        "reserved",
        "code",
        "http-503",
        "invalid-json"
      })
  void untrustedReleaseNeverCompletesCancellation(String bad) {
    var s =
        service(
            (id, release, req, rid) -> {
              if (!release) return result(id, "RESERVED");
              String json = result(id, "RELEASED").body();
              return switch (bad) {
                case "wrong-order" -> result(UUID.randomUUID().toString(), "RELEASED");
                case "wrong-product" ->
                    new InventoryGateway.Reply(200, json.replace("sku-demo-001", "other"));
                case "wrong-quantity" ->
                    new InventoryGateway.Reply(
                        200, json.replace("\"quantity\":2", "\"quantity\":3"));
                case "reserved" -> result(id, "RESERVED");
                case "code" ->
                    new InventoryGateway.Reply(200, json.replace("null", "\"INSUFFICIENT_STOCK\""));
                case "http-503" -> new InventoryGateway.Reply(503, "{}");
                default -> new InventoryGateway.Reply(200, "invalid-json");
              };
            });
    String id = (String) s.advance(create(s), "", false).get("order_id");
    assertEquals("CANCEL_PENDING", s.advance(s.requestCancel(id), "", true).get("status"));
  }

  @Test
  void exhaustedRetriesStayPendingAndExplicitRecoverySurvivesRestart() {
    var mode = new AtomicReference<>(false);
    var s =
        service(
            (id, release, r, rid) -> {
              if (!mode.get()) throw new java.io.IOException("lost response");
              return result(id, release ? "RELEASED" : "RESERVED");
            });
    var row = create(s);
    for (int i = 0; i < 5; i++) row = s.advance(row, "", true);
    assertEquals(5, ((Number) row.get("retry_count")).intValue());
    assertEquals(1, ((Number) row.get("needs_attention")).intValue());
    assertEquals("PENDING_INVENTORY", row.get("status"));
    assertEquals(0, s.reconcile(null));
    mode.set(true);
    var restarted = service((id, release, r, rid) -> result(id, release ? "RELEASED" : "RESERVED"));
    String id = (String) row.get("order_id");
    assertEquals(1, restarted.reconcile(id));
    assertEquals("CONFIRMED", restarted.get(id).get("status"));
  }

  @Test
  void releaseResponseLossReplaysOnceAfterRestart() {
    var released = new HashSet<String>();
    var mode = new AtomicReference<>(false);
    var s =
        service(
            (id, release, r, rid) -> {
              if (release) {
                released.add(id);
                if (!mode.get()) throw new java.io.IOException("response lost");
              }
              return result(id, release ? "RELEASED" : "RESERVED");
            });
    String id = (String) s.advance(create(s), "", false).get("order_id");
    assertEquals("CANCEL_PENDING", s.advance(s.requestCancel(id), "", true).get("status"));
    mode.set(true);
    s.reconcile(id);
    assertEquals("CANCELLED", s.get(id).get("status"));
    assertEquals(1, released.size());
  }

  @Test
  void lateReplyCannotRegressTerminalState() {
    final OrderService[] ref = new OrderService[1];
    var s =
        service(
            (id, release, r, rid) -> {
              ref[0].db.write(
                  c -> {
                    update(c, "UPDATE orders SET status='CANCELLED' WHERE order_id=?", id);
                    return null;
                  });
              return result(id, "RESERVED");
            });
    ref[0] = s;
    var result = s.advance(create(s), "", false);
    assertEquals("CANCELLED", result.get("status"));
  }

  @Test
  void legacySchemaAndDigestRemainCompatible() {
    String path = temp.resolve("orders.db").toString();
    var db = new Database(path);
    db.initialize(
        "CREATE TABLE orders(order_id TEXT PRIMARY KEY,idempotency_key TEXT UNIQUE,request_hash TEXT,product_id TEXT,quantity INTEGER,status TEXT,rejection_code TEXT,retry_count INTEGER DEFAULT 0,next_retry_at REAL DEFAULT 0,needs_attention INTEGER DEFAULT 0,last_error_code TEXT,created_at TEXT,updated_at TEXT)");
    String key = UUID.randomUUID().toString(), id = UUID.randomUUID().toString();
    String digest = "";
    try {
      digest =
          java.util.HexFormat.of()
              .formatHex(
                  java.security.MessageDigest.getInstance("SHA-256")
                      .digest(
                          "{\"product_id\":\"sku-demo-001\",\"quantity\":2}"
                              .getBytes(java.nio.charset.StandardCharsets.UTF_8)));
    } catch (Exception e) {
      fail(e);
    }
    String hash = digest;
    db.write(
        c -> {
          update(
              c,
              "INSERT INTO orders(order_id,idempotency_key,request_hash,product_id,quantity,status,created_at,updated_at) VALUES(?,?,?,?,?,'CONFIRMED','old','old')",
              id,
              key,
              hash,
              "sku-demo-001",
              2);
          return null;
        });
    var s = normal();
    assertEquals(id, s.create(key, req()).row().get("order_id"));
    assertFalse(s.create(key, req()).fresh());
    assertNull(s.get(id).get("cancelled_at"));
    assertEquals("old", s.get(id).get("created_at"));
    assertEquals(id, normal().get(id).get("order_id"));
  }

  @Test
  void unknownSchemaRefusesToStart() {
    normal()
        .db
        .write(
            c -> {
              update(c, "PRAGMA user_version=99");
              return null;
            });
    assertThrows(IllegalStateException.class, this::normal);
  }

  @Test
  void paginationAndStatusHaveConsistentTotal() {
    var s = normal();
    s.advance(create(s), "", false);
    create(s);
    create(s);
    assertEquals(3, s.list(null, 1, 1).total());
    assertEquals(1, s.list(Models.OrderState.CONFIRMED, 10, 0).items().size());
    assertEquals(0, s.list(Models.OrderState.CANCELLED, 10, 0).total());
  }
}
