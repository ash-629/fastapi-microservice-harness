package dev.orderstudio.inventory;

import static dev.orderstudio.common.Database.*;
import static dev.orderstudio.inventory.Models.*;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.orderstudio.common.*;
import dev.orderstudio.common.Api.*;
import java.time.Instant;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

@Service
public class InventoryService {
  final Database db;
  private final ObjectMapper mapper;

  public InventoryService(@Value("${studio.db-path}") String path, ObjectMapper mapper) {
    db = new Database(path);
    this.mapper = mapper;
    db.initialize(
        "CREATE TABLE IF NOT EXISTS products(product_id TEXT PRIMARY KEY,sku TEXT UNIQUE,name TEXT,available_qty INTEGER NOT NULL CHECK(available_qty>=0),updated_at TEXT)",
        "CREATE TABLE IF NOT EXISTS reservations(order_id TEXT PRIMARY KEY,product_id TEXT,quantity INTEGER,request_hash TEXT,status TEXT,rejection_code TEXT,created_at TEXT)");
    db.write(
        c -> {
          String[] names = {"机械键盘", "无线鼠标", "显示器支架"};
          for (int i = 1; i <= names.length; i++)
            update(
                c,
                "INSERT OR IGNORE INTO products VALUES(?,?,?,?,?)",
                "sku-demo-%03d".formatted(i),
                "DEMO-" + i,
                names[i - 1],
                20,
                Instant.now().toString());
          return null;
        });
  }

  public ProductPage products(int limit, int offset) {
    return db.read(
        c ->
            new ProductPage(
                rows(
                        c,
                        "SELECT * FROM products ORDER BY product_id LIMIT ? OFFSET ?",
                        limit,
                        offset)
                    .stream()
                    .map(Product::from)
                    .toList(),
                ((Number) one(c, "SELECT COUNT(*) AS n FROM products").get("n")).intValue(),
                limit,
                offset));
  }

  public Product product(String id) {
    return db.read(
        c -> {
          var row = one(c, "SELECT * FROM products WHERE product_id=?", id);
          if (row == null) throw new Failure(404, "PRODUCT_NOT_FOUND");
          return Product.from(row);
        });
  }

  public Reservation reservation(String id) {
    return db.read(
        c -> {
          var row = one(c, "SELECT * FROM reservations WHERE order_id=?", id);
          if (row == null) throw new Failure(404, "RESERVATION_NOT_FOUND");
          return Reservation.from(row);
        });
  }

  public Reservation reserve(String id, StockRequest req) {
    String digest = Api.digest(req, mapper);
    return db.write(
        c -> {
          var row = one(c, "SELECT * FROM reservations WHERE order_id=?", id);
          if (row != null) {
            if (!digest.equals(row.get("request_hash")))
              throw new Failure(409, "IDEMPOTENCY_CONFLICT");
            return Reservation.from(row);
          }
          var product = one(c, "SELECT * FROM products WHERE product_id=?", req.product_id());
          String code = null;
          if (product == null) code = "PRODUCT_NOT_FOUND";
          else if (update(
                  c,
                  "UPDATE products SET available_qty=available_qty-?,updated_at=? WHERE product_id=? AND available_qty>=?",
                  req.quantity(),
                  Instant.now().toString(),
                  req.product_id(),
                  req.quantity())
              != 1) code = "INSUFFICIENT_STOCK";
          update(
              c,
              "INSERT INTO reservations VALUES(?,?,?,?,?,?,?)",
              id,
              req.product_id(),
              req.quantity(),
              digest,
              code == null ? "RESERVED" : "REJECTED",
              code,
              Instant.now().toString());
          return Reservation.from(one(c, "SELECT * FROM reservations WHERE order_id=?", id));
        });
  }

  public Reservation release(String id, StockRequest req) {
    String digest = Api.digest(req, mapper);
    return db.write(
        c -> {
          var row = one(c, "SELECT * FROM reservations WHERE order_id=?", id);
          if (row == null) throw new Failure(404, "RESERVATION_NOT_FOUND");
          if (!digest.equals(row.get("request_hash")))
            throw new Failure(409, "IDEMPOTENCY_CONFLICT");
          if (row.get("status").equals("RELEASED")) return Reservation.from(row);
          if (!row.get("status").equals("RESERVED"))
            throw new Failure(409, "RESERVATION_NOT_RELEASABLE");
          if (update(
                  c,
                  "UPDATE products SET available_qty=available_qty+?,updated_at=? WHERE product_id=?",
                  row.get("quantity"),
                  Instant.now().toString(),
                  row.get("product_id"))
              != 1) throw new IllegalStateException("Reservation product missing");
          update(c, "UPDATE reservations SET status='RELEASED' WHERE order_id=?", id);
          return Reservation.from(one(c, "SELECT * FROM reservations WHERE order_id=?", id));
        });
  }

  public void ready() {
    db.read(c -> one(c, "SELECT 1 FROM products LIMIT 1"));
  }
}
