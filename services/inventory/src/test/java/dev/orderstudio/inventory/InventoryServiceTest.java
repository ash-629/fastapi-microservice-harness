package dev.orderstudio.inventory;

import static dev.orderstudio.common.Database.*;
import static dev.orderstudio.inventory.Models.ReservationState.*;
import static org.junit.jupiter.api.Assertions.*;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.orderstudio.common.Api.*;
import java.nio.file.Path;
import java.util.*;
import java.util.concurrent.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;

class InventoryServiceTest {
  @TempDir Path temp;
  InventoryService service;

  @BeforeEach
  void setup() {
    service = new InventoryService(temp.resolve("stock.db").toString(), new ObjectMapper());
  }

  StockRequest req(int qty) {
    return new StockRequest("sku-demo-001", qty);
  }

  @Test
  void stockNeverOversellsUnderConcurrentWriters() throws Exception {
    try (var pool = Executors.newFixedThreadPool(8)) {
      var work = new ArrayList<Callable<Models.Reservation>>();
      for (int i = 0; i < 30; i++)
        work.add(() -> service.reserve(UUID.randomUUID().toString(), req(1)));
      var results = pool.invokeAll(work);
      int reserved = 0;
      for (var result : results) if (result.get().status() == RESERVED) reserved++;
      assertEquals(20, reserved);
      assertEquals(0, service.product("sku-demo-001").available_qty());
    }
  }

  @Test
  void repeatedReservationIsIdempotentAndConflictsOnChangedInput() {
    String id = UUID.randomUUID().toString();
    var first = service.reserve(id, req(2));
    assertEquals(first, service.reserve(id, req(2)));
    assertEquals(
        "IDEMPOTENCY_CONFLICT",
        assertThrows(Failure.class, () -> service.reserve(id, req(3))).getMessage());
    assertEquals(18, service.product("sku-demo-001").available_qty());
  }

  @Test
  void businessRejectionIsPersisted() {
    String id = UUID.randomUUID().toString();
    var first = service.reserve(id, req(99));
    assertEquals(REJECTED, first.status());
    assertEquals("INSUFFICIENT_STOCK", first.rejection_code());
    assertEquals(first, service.reserve(id, req(99)));
  }

  @Test
  void missingProductReplaysRejection() {
    String id = UUID.randomUUID().toString();
    var req = new StockRequest("missing", 1);
    assertEquals("PRODUCT_NOT_FOUND", service.reserve(id, req).rejection_code());
    assertEquals(service.reserve(id, req), service.reservation(id));
  }

  @Test
  void releaseAndLateReserveCannotCreditOrDebitAgain() throws Exception {
    String id = UUID.randomUUID().toString();
    service.reserve(id, req(2));
    try (var pool = Executors.newFixedThreadPool(8)) {
      var work = new ArrayList<Callable<Models.Reservation>>();
      for (int i = 0; i < 20; i++) work.add(() -> service.release(id, req(2)));
      for (var result : pool.invokeAll(work)) assertEquals(RELEASED, result.get().status());
    }
    assertEquals(RELEASED, service.reserve(id, req(2)).status());
    assertEquals(20, service.product("sku-demo-001").available_qty());
  }

  @Test
  void releaseValidatesOriginalRequestAndState() {
    String id = UUID.randomUUID().toString();
    assertEquals(404, assertThrows(Failure.class, () -> service.release(id, req(1))).status);
    service.reserve(id, req(99));
    assertEquals(
        "RESERVATION_NOT_RELEASABLE",
        assertThrows(Failure.class, () -> service.release(id, req(99))).getMessage());
    String second = UUID.randomUUID().toString();
    service.reserve(second, req(1));
    assertEquals(
        "IDEMPOTENCY_CONFLICT",
        assertThrows(Failure.class, () -> service.release(second, req(2))).getMessage());
    assertEquals(19, service.product("sku-demo-001").available_qty());
  }

  @Test
  void initializationDoesNotResetExistingData() {
    service.reserve(UUID.randomUUID().toString(), req(4));
    var restarted = new InventoryService(temp.resolve("stock.db").toString(), new ObjectMapper());
    assertEquals(16, restarted.product("sku-demo-001").available_qty());
  }

  @Test
  void pageAndTotalUseSameSnapshot() {
    var page = service.products(1, 1);
    assertEquals(1, page.items().size());
    assertEquals(3, page.total());
    assertEquals("sku-demo-002", page.items().getFirst().product_id());
  }
}
