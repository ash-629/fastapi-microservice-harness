package dev.orderstudio.orders;

import static dev.orderstudio.common.Database.*;
import static dev.orderstudio.orders.Models.*;

import com.fasterxml.jackson.databind.*;
import dev.orderstudio.common.*;
import dev.orderstudio.common.Api.*;
import java.time.Instant;
import java.util.*;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.*;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

@Service
public class OrderService {
  final Database db;
  private final ObjectMapper mapper;
  private final InventoryGateway gateway;
  private final boolean recovery;

  @Autowired
  public OrderService(
      @Value("${studio.db-path}") String path,
      @Value("${studio.inventory-url}") String url,
      ObjectMapper mapper,
      @Value("${studio.recovery:true}") boolean recovery) {
    this(path, mapper, InventoryGateway.http(url, mapper), recovery);
  }

  public OrderService(
      String path, ObjectMapper mapper, InventoryGateway gateway, boolean recovery) {
    db = new Database(path);
    this.mapper = mapper;
    this.gateway = gateway;
    this.recovery = recovery;
    db.initialize(
        "CREATE TABLE IF NOT EXISTS orders(order_id TEXT PRIMARY KEY,idempotency_key TEXT UNIQUE,request_hash TEXT,product_id TEXT,quantity INTEGER,status TEXT,rejection_code TEXT,retry_count INTEGER DEFAULT 0,next_retry_at REAL DEFAULT 0,needs_attention INTEGER DEFAULT 0,last_error_code TEXT,created_at TEXT,updated_at TEXT)",
        "CREATE INDEX IF NOT EXISTS recovery ON orders(status,next_retry_at)");
    db.write(
        c -> {
          int version = ((Number) one(c, "PRAGMA user_version").get("user_version")).intValue();
          if (version > 1) throw new IllegalStateException("Unsupported orders schema version");
          if (version == 0) {
            Set<String> columns = new HashSet<>();
            for (var r : rows(c, "PRAGMA table_info(orders)")) columns.add((String) r.get("name"));
            for (String name : List.of("cancel_requested_at", "cancelled_at"))
              if (!columns.contains(name))
                update(c, "ALTER TABLE orders ADD COLUMN " + name + " TEXT");
            update(c, "PRAGMA user_version=1");
          }
          return null;
        });
  }

  public record Created(Map<String, Object> row, boolean fresh) {}

  public Created create(String key, StockRequest req) {
    String digest = Api.digest(req, mapper);
    return db.write(
        c -> {
          var row = one(c, "SELECT * FROM orders WHERE idempotency_key=?", key);
          if (row != null) {
            if (!digest.equals(row.get("request_hash")))
              throw new Failure(409, "IDEMPOTENCY_CONFLICT");
            return new Created(row, false);
          }
          String id = UUID.randomUUID().toString(), now = Instant.now().toString();
          update(
              c,
              "INSERT INTO orders(order_id,idempotency_key,request_hash,product_id,quantity,status,created_at,updated_at) VALUES(?,?,?,?,?,'PENDING_INVENTORY',?,?)",
              id,
              key,
              digest,
              req.product_id(),
              req.quantity(),
              now,
              now);
          return new Created(one(c, "SELECT * FROM orders WHERE order_id=?", id), true);
        });
  }

  public Map<String, Object> get(String id) {
    return db.read(
        c -> {
          var row = one(c, "SELECT * FROM orders WHERE order_id=?", id);
          if (row == null) throw new Failure(404, "ORDER_NOT_FOUND");
          return row;
        });
  }

  public OrderPage list(OrderState state, int limit, int offset) {
    return db.read(
        c -> {
          String where = state == null ? "" : " WHERE status=?";
          List<Object> args = new ArrayList<>();
          if (state != null) args.add(state.name());
          int total =
              ((Number) one(c, "SELECT COUNT(*) AS n FROM orders" + where, args.toArray()).get("n"))
                  .intValue();
          args.add(limit);
          args.add(offset);
          return new OrderPage(
              rows(
                      c,
                      "SELECT * FROM orders"
                          + where
                          + " ORDER BY created_at DESC,order_id DESC LIMIT ? OFFSET ?",
                      args.toArray())
                  .stream()
                  .map(Order::from)
                  .toList(),
              total,
              limit,
              offset);
        });
  }

  public Map<String, Object> requestCancel(String id) {
    return db.write(
        c -> {
          var row = one(c, "SELECT * FROM orders WHERE order_id=?", id);
          if (row == null) throw new Failure(404, "ORDER_NOT_FOUND");
          String state = (String) row.get("status");
          if (state.equals("CONFIRMED")) {
            String now = Instant.now().toString();
            update(
                c,
                "UPDATE orders SET status='CANCEL_PENDING',retry_count=0,next_retry_at=0,needs_attention=0,last_error_code=NULL,cancel_requested_at=?,updated_at=? WHERE order_id=? AND status='CONFIRMED'",
                now,
                now,
                id);
          } else if (!Set.of("CANCEL_PENDING", "CANCELLED").contains(state))
            throw new Failure(409, "ORDER_NOT_CANCELLABLE");
          return one(c, "SELECT * FROM orders WHERE order_id=?", id);
        });
  }

  public Map<String, Object> advance(Map<String, Object> row, String requestId, boolean retry) {
    String state = (String) row.get("status"), id = (String) row.get("order_id");
    boolean release = state.equals("CANCEL_PENDING");
    if (!release && !state.equals("PENDING_INVENTORY")) return get(id);
    String error = null;
    InventoryGateway.Reply reply = null;
    try {
      reply =
          gateway.put(
              id,
              release,
              new StockRequest(
                  (String) row.get("product_id"), ((Number) row.get("quantity")).intValue()),
              requestId);
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
      error = "DOWNSTREAM_UNAVAILABLE";
    } catch (Exception e) {
      error = "DOWNSTREAM_UNAVAILABLE";
    }
    if (reply != null) {
      if (reply.status() != 200) error = "DOWNSTREAM_UNAVAILABLE";
      else
        try {
          JsonNode result = mapper.readTree(reply.body());
          if (result == null
              || !result.isObject()
              || !result.path("order_id").isTextual()
              || !id.equals(result.path("order_id").textValue())
              || !result.path("product_id").isTextual()
              || !row.get("product_id").equals(result.path("product_id").textValue())
              || !result.path("quantity").isInt()
              || result.path("quantity").intValue() != ((Number) row.get("quantity")).intValue()
              || !result.has("rejection_code"))
            throw new IllegalArgumentException("Mismatched result");
          String resultState = result.path("status").asText(),
              code =
                  result.path("rejection_code").isNull()
                      ? null
                      : result.path("rejection_code").textValue();
          if (release) {
            if (!resultState.equals("RELEASED") || !result.path("rejection_code").isNull())
              throw new IllegalArgumentException("Invalid release");
          } else if (!(resultState.equals("RESERVED") && result.path("rejection_code").isNull())
              && !(resultState.equals("REJECTED")
                  && Set.of("INSUFFICIENT_STOCK", "PRODUCT_NOT_FOUND")
                      .contains(code == null ? "" : code)))
            throw new IllegalArgumentException("Invalid reservation");
          db.write(
              c -> {
                String now = Instant.now().toString();
                if (release)
                  update(
                      c,
                      "UPDATE orders SET status='CANCELLED',cancelled_at=?,needs_attention=0,last_error_code=NULL,updated_at=? WHERE order_id=? AND status='CANCEL_PENDING'",
                      now,
                      now,
                      id);
                else
                  update(
                      c,
                      "UPDATE orders SET status=?,rejection_code=?,needs_attention=0,last_error_code=NULL,updated_at=? WHERE order_id=? AND status='PENDING_INVENTORY'",
                      resultState.equals("RESERVED") ? "CONFIRMED" : "REJECTED",
                      code,
                      now,
                      id);
                return null;
              });
        } catch (com.fasterxml.jackson.core.JsonProcessingException | IllegalArgumentException e) {
          error = "DOWNSTREAM_CONTRACT_ERROR";
        }
    }
    if (error != null && retry) {
      String failure = error;
      double next =
          System.currentTimeMillis() / 1000.0
              + Math.min(
                  16, Math.pow(2, Math.min(4, ((Number) row.get("retry_count")).intValue())));
      db.write(
          c -> {
            update(
                c,
                "UPDATE orders SET retry_count=retry_count+1,next_retry_at=?,needs_attention=CASE WHEN retry_count>=4 THEN 1 ELSE 0 END,last_error_code=?,updated_at=? WHERE order_id=? AND status=?",
                next,
                failure,
                Instant.now().toString(),
                id,
                state);
            return null;
          });
    }
    return get(id);
  }

  public int reconcile(String id) {
    var pending =
        db.read(
            c ->
                id == null
                    ? rows(
                        c,
                        "SELECT * FROM orders WHERE status IN ('PENDING_INVENTORY','CANCEL_PENDING') AND needs_attention=0 AND next_retry_at<=? ORDER BY next_retry_at,created_at LIMIT 20",
                        System.currentTimeMillis() / 1000.0)
                    : rows(
                        c,
                        "SELECT * FROM orders WHERE order_id=? AND status IN ('PENDING_INVENTORY','CANCEL_PENDING')",
                        id));
    for (var row : pending) {
      if (Thread.currentThread().isInterrupted()) break;
      advance(row, UUID.randomUUID().toString(), true);
    }
    return pending.size();
  }

  @Scheduled(fixedDelay = 1000)
  public void recover() {
    if (recovery)
      try {
        reconcile(null);
      } catch (Exception e) {
        LoggerFactory.getLogger(OrderService.class).error("Recovery failed", e);
      }
  }

  public void ready() {
    db.read(c -> one(c, "SELECT 1 FROM orders LIMIT 1"));
  }
}
