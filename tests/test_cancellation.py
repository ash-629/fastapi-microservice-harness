"""C01-C05：取消、库存守恒、结果未知和旧数据升级。"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from inventory_service import service as stock
from inventory_service.schemas import Request as StockRequest
from order_service import service as orders
from order_service.main import create_app
from order_service.schemas import Request


def confirmed(tmp_path):
    sp, op = tmp_path / "inventory", tmp_path / "orders"
    stock.init(sp)
    orders.init(op)
    row, _ = orders.create(op, str(uuid4()), Request(product_id="sku-demo-001", quantity=2))

    def respond(request):
        value = StockRequest.model_validate_json(request.content)
        result = (
            stock.release(sp, row["order_id"], value)
            if request.url.path.endswith("/release")
            else stock.reserve(sp, row["order_id"], value)
        )
        return httpx.Response(200, json=result)

    client = httpx.Client(transport=httpx.MockTransport(respond))
    row = orders.advance(op, row, "http://inventory", client=client)
    return sp, op, row, client


def available(path):
    with stock.connect(path) as db:
        return db.execute(
            "SELECT available_qty FROM products WHERE product_id='sku-demo-001'"
        ).fetchone()[0]


def test_cancel_repeated_and_late_reserve_preserve_stock(tmp_path):
    sp, op, row, client = confirmed(tmp_path)
    with closing(client):
        assert available(sp) == 18
        pending = orders.request_cancel(op, row["order_id"])
        assert pending["status"] == "CANCEL_PENDING"
        result = orders.advance_cancel(op, pending, "http://inventory", client=client)
        assert (
            result["status"] == "CANCELLED"
            and result["cancel_requested_at"]
            and result["cancelled_at"]
        )
        again = orders.request_cancel(op, row["order_id"])
        assert again["status"] == "CANCELLED"
        assert (
            orders.advance_cancel(op, again, "http://inventory", client=client)["cancelled_at"]
            == result["cancelled_at"]
        )
        req = StockRequest(product_id=row["product_id"], quantity=2)
        assert stock.release(sp, row["order_id"], req)["status"] == "RELEASED"
        assert stock.reserve(sp, row["order_id"], req)["status"] == "RELEASED"
        assert available(sp) == 20


def test_release_response_loss_then_recovery_is_once(tmp_path):
    sp, op, row, client = confirmed(tmp_path)
    client.close()
    pending = orders.request_cancel(op, row["order_id"])

    def lost(request):
        stock.release(sp, row["order_id"], StockRequest.model_validate_json(request.content))
        raise httpx.ReadTimeout("release committed but response lost")

    with httpx.Client(transport=httpx.MockTransport(lost)) as transport:
        result = orders.advance_cancel(
            op, pending, "http://inventory", client=transport, recovery=True
        )
    assert result["status"] == "CANCEL_PENDING" and result["cancelled_at"] is None
    assert available(sp) == 20

    def replay(request):
        return httpx.Response(
            200,
            json=stock.release(
                sp, row["order_id"], StockRequest.model_validate_json(request.content)
            ),
        )

    with httpx.Client(transport=httpx.MockTransport(replay)) as transport:
        result = orders.advance_cancel(
            op, result, "http://inventory", client=transport, recovery=True
        )
    assert result["status"] == "CANCELLED" and available(sp) == 20


def test_concurrent_release_and_late_reserve_do_not_reoccupy(tmp_path):
    sp, op, row, client = confirmed(tmp_path)
    client.close()
    req = StockRequest(product_id=row["product_id"], quantity=2)
    with ThreadPoolExecutor(8) as pool:
        results = list(
            pool.map(
                lambda i: (
                    stock.release(sp, row["order_id"], req)
                    if i % 2
                    else stock.reserve(sp, row["order_id"], req)
                ),
                range(24),
            )
        )
    assert any(r["status"] == "RELEASED" for r in results)
    assert available(sp) == 20


@pytest.mark.parametrize("state", ["PENDING_INVENTORY", "REJECTED"])
def test_invalid_order_state_cannot_cancel(tmp_path, state):
    op = tmp_path / "orders"
    orders.init(op)
    row, _ = orders.create(op, str(uuid4()), Request(product_id="sku-demo-001", quantity=1))
    with orders.connect(op) as db:
        db.execute("UPDATE orders SET status=? WHERE order_id=?", (state, row["order_id"]))
    with pytest.raises(orders.OrderNotCancellable):
        orders.request_cancel(op, row["order_id"])


def test_unknown_order_cancel_is_404(tmp_path):
    with TestClient(create_app(tmp_path / "orders", recovery=False)) as client:
        result = client.post("/api/v1/orders/" + str(uuid4()) + "/cancel")
        assert result.status_code == 404 and result.json()["error"]["code"] == "ORDER_NOT_FOUND"


def test_release_validates_original_request(tmp_path):
    sp, op, row, client = confirmed(tmp_path)
    client.close()
    with pytest.raises(stock.IdempotencyConflict):
        stock.release(sp, row["order_id"], StockRequest(product_id="sku-demo-001", quantity=1))
    assert available(sp) == 18


def test_legacy_database_upgrade_is_non_destructive(tmp_path):
    import sqlite3

    op = tmp_path / "legacy"
    with sqlite3.connect(op) as db:
        db.executescript("""CREATE TABLE orders(order_id TEXT PRIMARY KEY,idempotency_key TEXT UNIQUE,
 request_hash TEXT,product_id TEXT,quantity INTEGER,status TEXT,rejection_code TEXT,
 retry_count INTEGER DEFAULT 0,next_retry_at REAL DEFAULT 0,needs_attention INTEGER DEFAULT 0,
 last_error_code TEXT,created_at TEXT,updated_at TEXT);""")
        db.execute("INSERT INTO orders(order_id,status,quantity) VALUES('legacy','CONFIRMED',2)")
    orders.init(op)
    orders.init(op)
    with orders.connect(op) as db:
        row = dict(db.execute("SELECT * FROM orders WHERE order_id='legacy'").fetchone())
        assert row["quantity"] == 2 and row["status"] == "CONFIRMED"
        assert row["cancel_requested_at"] is None and row["cancelled_at"] is None
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1


@pytest.mark.parametrize("bad", ["wrong-id", "string-quantity", "not-released", "http-503"])
def test_untrusted_release_cannot_complete_cancel(tmp_path, bad):
    sp, op, row, client = confirmed(tmp_path)
    client.close()
    pending = orders.request_cancel(op, row["order_id"])

    def respond(request):
        if bad == "http-503":
            return httpx.Response(503, json={})
        return httpx.Response(
            200,
            json={
                "order_id": str(uuid4()) if bad == "wrong-id" else row["order_id"],
                "product_id": row["product_id"],
                "quantity": "2" if bad == "string-quantity" else 2,
                "status": "RESERVED" if bad == "not-released" else "RELEASED",
                "rejection_code": None,
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = orders.advance_cancel(
            op, pending, "http://inventory", client=client, recovery=True
        )
    assert result["status"] == "CANCEL_PENDING" and result["cancelled_at"] is None
    assert available(sp) == 18


def test_cancel_retry_exhaustion_stays_pending_and_manual_retry_recovers(tmp_path):
    sp, op, row, client = confirmed(tmp_path)
    client.close()
    row = orders.request_cancel(op, row["order_id"])

    def unavailable(request):
        raise httpx.ReadTimeout("unknown release result")

    with httpx.Client(transport=httpx.MockTransport(unavailable)) as client:
        for _ in range(5):
            row = orders.advance_cancel(op, row, "http://inventory", client=client, recovery=True)
    assert (
        row["status"] == "CANCEL_PENDING"
        and row["needs_attention"] == 1
        and row["retry_count"] == 5
    )

    def released(request):
        return httpx.Response(
            200,
            json=stock.release(
                sp, row["order_id"], StockRequest.model_validate_json(request.content)
            ),
        )

    with httpx.Client(transport=httpx.MockTransport(released)) as client:
        result = orders.advance_cancel(
            op, orders.request_cancel(op, row["order_id"]), "http://inventory", client=client
        )
    assert result["status"] == "CANCELLED" and not result["needs_attention"] and available(sp) == 20


def test_release_missing_or_rejected_reservation_is_not_stock_credit(tmp_path):
    sp = tmp_path / "stock"
    stock.init(sp)
    oid = str(uuid4())
    req = StockRequest(product_id="sku-demo-001", quantity=99)
    with pytest.raises(stock.ReservationNotFound):
        stock.release(sp, oid, req)
    assert stock.reserve(sp, oid, req)["status"] == "REJECTED"
    with pytest.raises(stock.ReservationNotReleasable):
        stock.release(sp, oid, req)
    assert available(sp) == 20


def test_concurrent_cancel_preserves_first_intent_and_terminal_time(tmp_path):
    sp, op, row, client = confirmed(tmp_path)
    client.close()

    def cancel(_):
        return orders.request_cancel(op, row["order_id"])

    with ThreadPoolExecutor(8) as pool:
        requests = list(pool.map(cancel, range(16)))
    assert len({r["cancel_requested_at"] for r in requests}) == 1

    def respond(request):
        return httpx.Response(
            200,
            json=stock.release(
                sp, row["order_id"], StockRequest.model_validate_json(request.content)
            ),
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with ThreadPoolExecutor(8) as pool:
            results = list(
                pool.map(
                    lambda r: orders.advance_cancel(op, r, "http://inventory", client=client),
                    requests,
                )
            )
    assert {r["status"] for r in results} == {"CANCELLED"}
    assert len({r["cancelled_at"] for r in results}) == 1 and available(sp) == 20
