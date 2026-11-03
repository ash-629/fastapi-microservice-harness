# 持久化订单、幂等请求、未知结果恢复。
import hashlib
import time
from uuid import uuid4

import httpx

from .repository import connect, initialize, now
from .schemas import Reservation, ReleaseResult


class IdempotencyConflict(ValueError):
    """同一操作标识被用于不同业务输入。"""


class OrderNotCancellable(ValueError):
    pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS orders(order_id TEXT PRIMARY KEY,idempotency_key TEXT UNIQUE,
 request_hash TEXT,product_id TEXT,quantity INTEGER,status TEXT,rejection_code TEXT,
 retry_count INTEGER DEFAULT 0,next_retry_at REAL DEFAULT 0,needs_attention INTEGER DEFAULT 0,
 last_error_code TEXT,created_at TEXT,updated_at TEXT);
CREATE INDEX IF NOT EXISTS recovery ON orders(status,next_retry_at);
"""


def init(path):
    initialize(path, SCHEMA)
    # C05：兼容已有演示库，写入schema版本与新增字段在同一事务提交。
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version > 1:
            raise RuntimeError("Unsupported orders schema version")
        if version == 0:
            columns = {c["name"] for c in db.execute("PRAGMA table_info(orders)")}
            for column in ["cancel_requested_at", "cancelled_at"]:
                if column not in columns:
                    db.execute(f"ALTER TABLE orders ADD COLUMN {column} TEXT")
            db.execute("PRAGMA user_version=1")


def create(path, key, req):
    digest = hashlib.sha256(req.model_dump_json().encode()).hexdigest()
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM orders WHERE idempotency_key=?", (key,)).fetchone()
        if row:
            if row["request_hash"] != digest:
                raise IdempotencyConflict("IDEMPOTENCY_CONFLICT")
            return dict(row), False
        oid = str(uuid4())
        ts = now()
        db.execute(
            "INSERT INTO orders(order_id,idempotency_key,request_hash,product_id,quantity,status,created_at,updated_at) VALUES(?,?,?,?,?,'PENDING_INVENTORY',?,?)",
            (oid, key, digest, req.product_id, req.quantity, ts, ts),
        )
        return dict(db.execute("SELECT * FROM orders WHERE order_id=?", (oid,)).fetchone()), True


def advance(path, row, url, request_id="", client=None, recovery=False):
    if row["status"] != "PENDING_INVENTORY":
        return row
    owned = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(2, connect=0.5))
    error = None
    try:
        res = client.put(
            f"{url}/internal/v1/reservations/{row['order_id']}",
            json={"product_id": row["product_id"], "quantity": row["quantity"]},
            headers={"X-Request-ID": request_id},
        )
        if res.status_code != 200:
            raise httpx.HTTPStatusError("downstream unavailable", request=res.request, response=res)
        result = Reservation.model_validate(res.json())
        if result.status == "RELEASED":
            raise ValueError("Reservation is already released")
        if (result.order_id, result.product_id, result.quantity) != (
            row["order_id"],
            row["product_id"],
            row["quantity"],
        ):
            raise ValueError("DOWNSTREAM_CONTRACT_ERROR")
        if result.status == "REJECTED" and result.rejection_code not in (
            "INSUFFICIENT_STOCK",
            "PRODUCT_NOT_FOUND",
        ):
            raise ValueError("DOWNSTREAM_CONTRACT_ERROR")
        if result.status == "RESERVED" and result.rejection_code is not None:
            raise ValueError("DOWNSTREAM_CONTRACT_ERROR")
        with connect(path) as db:
            db.execute(
                "UPDATE orders SET status=?,rejection_code=?,needs_attention=0,last_error_code=NULL,updated_at=? WHERE order_id=? AND status='PENDING_INVENTORY'",
                (
                    "CONFIRMED" if result.status == "RESERVED" else "REJECTED",
                    result.rejection_code,
                    now(),
                    row["order_id"],
                ),
            )
    except httpx.HTTPError:
        error = "DOWNSTREAM_UNAVAILABLE"
    except ValueError:
        error = "DOWNSTREAM_CONTRACT_ERROR"
    finally:
        if owned:
            client.close()
    if error and recovery:
        with connect(path) as db:
            db.execute(
                "UPDATE orders SET retry_count=retry_count+1,next_retry_at=?,needs_attention=CASE WHEN retry_count>=4 THEN 1 ELSE 0 END,last_error_code=?,updated_at=? WHERE order_id=? AND status='PENDING_INVENTORY'",
                (
                    time.time() + min(16, 2 ** min(row["retry_count"], 4)),
                    error,
                    now(),
                    row["order_id"],
                ),
            )
    with connect(path) as db:
        return dict(
            db.execute("SELECT * FROM orders WHERE order_id=?", (row["order_id"],)).fetchone()
        )


def request_cancel(path, oid):
    """C01/C02：仅确认订单能首次申请取消；重复申请保留原请求时间和进度。"""
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM orders WHERE order_id=?", (oid,)).fetchone()
        if row is None:
            raise KeyError(oid)
        if row["status"] == "CONFIRMED":
            ts = now()
            db.execute(
                "UPDATE orders SET status='CANCEL_PENDING',retry_count=0,next_retry_at=0,needs_attention=0,last_error_code=NULL,cancel_requested_at=?,updated_at=? WHERE order_id=? AND status='CONFIRMED'",
                (ts, ts, oid),
            )
        elif row["status"] not in ("CANCEL_PENDING", "CANCELLED"):
            raise OrderNotCancellable("ORDER_NOT_CANCELLABLE")
        return dict(db.execute("SELECT * FROM orders WHERE order_id=?", (oid,)).fetchone())


def advance_cancel(path, row, url, request_id="", client=None, recovery=False):
    """C02/C03：结果未知保持取消中，以订单ID重放release来收敛状态。"""
    if row["status"] != "CANCEL_PENDING":
        return row
    owned = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(2, connect=0.5))
    error = None
    try:
        response = client.put(
            f"{url}/internal/v1/reservations/{row['order_id']}/release",
            json={"product_id": row["product_id"], "quantity": row["quantity"]},
            headers={"X-Request-ID": request_id},
        )
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError("Unexpected release status")
        result = ReleaseResult.model_validate(response.json())
        if (result.order_id, result.product_id, result.quantity) != (
            row["order_id"],
            row["product_id"],
            row["quantity"],
        ):
            raise ValueError("Release does not match order")
        with connect(path) as db:
            ts = now()
            db.execute(
                "UPDATE orders SET status='CANCELLED',cancelled_at=?,needs_attention=0,last_error_code=NULL,updated_at=? WHERE order_id=? AND status='CANCEL_PENDING'",
                (ts, ts, row["order_id"]),
            )
    except httpx.HTTPError:
        error = "DOWNSTREAM_UNAVAILABLE"
    except ValueError:
        error = "DOWNSTREAM_CONTRACT_ERROR"
    finally:
        if owned:
            client.close()
    if error and recovery:
        with connect(path) as db:
            db.execute(
                "UPDATE orders SET retry_count=retry_count+1,next_retry_at=?,needs_attention=CASE WHEN retry_count>=4 THEN 1 ELSE 0 END,last_error_code=?,updated_at=? WHERE order_id=? AND status='CANCEL_PENDING'",
                (
                    time.time() + min(16, 2 ** min(row["retry_count"], 4)),
                    error,
                    now(),
                    row["order_id"],
                ),
            )
    with connect(path) as db:
        return dict(
            db.execute("SELECT * FROM orders WHERE order_id=?", (row["order_id"],)).fetchone()
        )


def reconcile(path, url, oid=None, stop_event=None):
    with connect(path) as db:
        if oid:
            rows = db.execute(
                "SELECT * FROM orders WHERE order_id=? AND status IN ('PENDING_INVENTORY','CANCEL_PENDING')",
                (oid,),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM orders WHERE status IN ('PENDING_INVENTORY','CANCEL_PENDING') AND needs_attention=0 AND next_retry_at<=? ORDER BY next_retry_at,created_at LIMIT 20",
                (time.time(),),
            ).fetchall()
    for row in rows:
        if stop_event is not None and stop_event.is_set():
            break
        handler = advance_cancel if row["status"] == "CANCEL_PENDING" else advance
        handler(path, dict(row), url, recovery=True)
    return len(rows)
