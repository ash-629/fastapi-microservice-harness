# 覆盖 F01/F03/R01：原子占用、拒绝持久化、幂等重放。
import hashlib

from .repository import connect, initialize, now
from .schemas import Request


class IdempotencyConflict(ValueError):
    """同一操作标识被用于不同业务输入。"""


class ReservationNotFound(LookupError):
    pass


class ReservationNotReleasable(ValueError):
    pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS products(product_id TEXT PRIMARY KEY, sku TEXT UNIQUE, name TEXT,
 available_qty INTEGER NOT NULL CHECK(available_qty>=0), updated_at TEXT);
CREATE TABLE IF NOT EXISTS reservations(order_id TEXT PRIMARY KEY, product_id TEXT, quantity INTEGER,
 request_hash TEXT, status TEXT, rejection_code TEXT, created_at TEXT);
"""


def init(path):
    initialize(path, SCHEMA)
    with connect(path) as db:
        for i, name in enumerate(["机械键盘", "无线鼠标", "显示器支架"], 1):
            db.execute(
                "INSERT OR IGNORE INTO products VALUES(?,?,?,?,?)",
                (f"sku-demo-{i:03}", f"DEMO-{i}", name, 20, now()),
            )


def reserve(path, oid, req: Request):
    digest = hashlib.sha256(req.model_dump_json().encode()).hexdigest()
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM reservations WHERE order_id=?", (oid,)).fetchone()
        if row:
            if row["request_hash"] != digest:
                raise IdempotencyConflict("IDEMPOTENCY_CONFLICT")
            return dict(row)
        p = db.execute("SELECT * FROM products WHERE product_id=?", (req.product_id,)).fetchone()
        code = None
        if p is None:
            code = "PRODUCT_NOT_FOUND"
        elif (
            db.execute(
                "UPDATE products SET available_qty=available_qty-?,updated_at=? WHERE product_id=? AND available_qty>=?",
                (req.quantity, now(), req.product_id, req.quantity),
            ).rowcount
            != 1
        ):
            code = "INSUFFICIENT_STOCK"
        status = "REJECTED" if code else "RESERVED"
        db.execute(
            "INSERT INTO reservations VALUES(?,?,?,?,?,?,?)",
            (oid, req.product_id, req.quantity, digest, status, code, now()),
        )
        return dict(db.execute("SELECT * FROM reservations WHERE order_id=?", (oid,)).fetchone())


def release(path, oid, req: Request):
    """C03/C04：同一事务内加回库存并写终态，迟到reserve不能重新占用。"""
    digest = hashlib.sha256(req.model_dump_json().encode()).hexdigest()
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM reservations WHERE order_id=?", (oid,)).fetchone()
        if row is None:
            raise ReservationNotFound(oid)
        if row["request_hash"] != digest:
            raise IdempotencyConflict("IDEMPOTENCY_CONFLICT")
        if row["status"] == "RELEASED":
            return dict(row)
        if row["status"] != "RESERVED":
            raise ReservationNotReleasable("RESERVATION_NOT_RELEASABLE")
        if (
            db.execute(
                "UPDATE products SET available_qty=available_qty+?,updated_at=? WHERE product_id=?",
                (row["quantity"], now(), row["product_id"]),
            ).rowcount
            != 1
        ):
            raise RuntimeError("Reservation product missing")
        db.execute("UPDATE reservations SET status='RELEASED' WHERE order_id=?", (oid,))
        return dict(db.execute("SELECT * FROM reservations WHERE order_id=?", (oid,)).fetchone())
