"""交付前回归：边界、终态、故障语义和客户端信任边界。"""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from order_service import service
from order_service.main import create_app
from order_service.schemas import Request


@pytest.mark.parametrize("quantity", [0, 100, -1, 1.5, True, "2", None])
def test_quantity_rejected(tmp_path, quantity):
    with TestClient(create_app(tmp_path / "orders", recovery=False)) as client:
        res = client.post(
            "/api/v1/orders",
            json={"product_id": "sku-demo-001", "quantity": quantity},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert res.status_code == 422
        assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_blank_product_rejected(tmp_path):
    with TestClient(create_app(tmp_path / "orders", recovery=False)) as client:
        res = client.post(
            "/api/v1/orders",
            json={"product_id": "   ", "quantity": 1},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert res.status_code == 422


def test_concurrent_same_key_is_one_order(tmp_path):
    path = tmp_path / "orders"
    service.init(path)
    key = str(uuid4())
    req = Request(product_id="sku-demo-001", quantity=1)
    with ThreadPoolExecutor(8) as pool:
        rows = list(pool.map(lambda _: service.create(path, key, req), range(16)))
    assert len({row[0]["order_id"] for row in rows}) == 1
    assert sum(fresh for _, fresh in rows) == 1


@pytest.mark.parametrize(
    "downstream", ["invalid-json", "string-quantity", "unknown-error", "http-503"]
)
def test_bad_downstream_does_not_confirm(tmp_path, downstream):
    path = tmp_path / "orders"
    service.init(path)
    row, _ = service.create(path, str(uuid4()), Request(product_id="sku-demo-001", quantity=2))

    def respond(request):
        if downstream == "invalid-json":
            return httpx.Response(200, text="not json")
        if downstream == "http-503":
            return httpx.Response(503, json={})
        return httpx.Response(
            200,
            json={
                "order_id": row["order_id"],
                "product_id": row["product_id"],
                "quantity": "2" if downstream == "string-quantity" else 2,
                "status": "REJECTED" if downstream == "unknown-error" else "RESERVED",
                "rejection_code": "UNRECOGNIZED" if downstream == "unknown-error" else None,
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = service.advance(path, row, "http://inventory", client=client, recovery=True)
    assert result["status"] == "PENDING_INVENTORY"
    expected = "DOWNSTREAM_UNAVAILABLE" if downstream == "http-503" else "DOWNSTREAM_CONTRACT_ERROR"
    assert result["last_error_code"] == expected


def test_retry_exhaustion_does_not_reject_order(tmp_path):
    path = tmp_path / "orders"
    service.init(path)
    row, _ = service.create(path, str(uuid4()), Request(product_id="sku-demo-001", quantity=2))

    def fail(request):
        raise httpx.ReadTimeout("lost result")

    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        for _ in range(5):
            row = service.advance(path, row, "http://inventory", client=client, recovery=True)
    assert row["status"] == "PENDING_INVENTORY" and row["needs_attention"] == 1
    assert row["retry_count"] == 5


def test_terminal_state_cannot_regress(tmp_path):
    path = tmp_path / "orders"
    service.init(path)
    old, _ = service.create(path, str(uuid4()), Request(product_id="sku-demo-001", quantity=2))
    with service.connect(path) as db:
        db.execute("UPDATE orders SET status='CONFIRMED' WHERE order_id=?", (old["order_id"],))

    def reject(request):
        return httpx.Response(
            200,
            json={
                "order_id": old["order_id"],
                "product_id": old["product_id"],
                "quantity": 2,
                "status": "REJECTED",
                "rejection_code": "INSUFFICIENT_STOCK",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(reject)) as client:
        result = service.advance(path, old, "http://inventory", client=client, recovery=True)
    assert result["status"] == "CONFIRMED"


def test_unexpected_value_error_is_not_a_business_conflict(tmp_path, monkeypatch):
    with TestClient(
        create_app(tmp_path / "orders", recovery=False), raise_server_exceptions=False
    ) as client:

        def broken(*args):
            raise ValueError("private implementation detail")

        monkeypatch.setattr(service, "create", broken)
        result = client.post(
            "/api/v1/orders",
            json={"product_id": "sku-demo-001", "quantity": 1},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert result.status_code == 500
        assert result.json()["error"]["code"] == "INTERNAL_ERROR"
        assert "private implementation detail" not in result.text
        assert result.headers["X-Request-ID"] == result.json()["request_id"]


def test_storage_error_has_uniform_503_without_exception_detail(tmp_path, monkeypatch):
    import sqlite3

    with TestClient(create_app(tmp_path / "orders", recovery=False)) as client:

        def unavailable(*args):
            raise sqlite3.OperationalError("private db path")

        monkeypatch.setattr(service, "create", unavailable)
        result = client.post(
            "/api/v1/orders",
            json={"product_id": "sku-demo-001", "quantity": 1},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert result.status_code == 503
        assert result.json()["error"]["code"] == "STORAGE_UNAVAILABLE"
        assert "private db path" not in result.text


def test_filter_pagination_total_and_boundary_consistency(tmp_path):
    path = tmp_path / "orders"
    with TestClient(create_app(path, recovery=False)) as client:
        for i in range(23):
            row, _ = service.create(
                path, str(uuid4()), Request(product_id="sku-demo-001", quantity=1)
            )
            with service.connect(path) as db:
                db.execute(
                    "UPDATE orders SET status=? WHERE order_id=?",
                    ("CONFIRMED" if i % 2 == 0 else "REJECTED", row["order_id"]),
                )
        first = client.get("/api/v1/orders?status=CONFIRMED&limit=10&offset=0").json()
        second = client.get("/api/v1/orders?status=CONFIRMED&limit=10&offset=10").json()
        assert first["total"] == second["total"] == 12
        assert len(first["items"]) == 10 and len(second["items"]) == 2
        assert not {x["order_id"] for x in first["items"]} & {
            x["order_id"] for x in second["items"]
        }
        assert client.get("/api/v1/orders?limit=0").status_code == 422
        assert client.get("/api/v1/orders?offset=-1").status_code == 422
        assert client.get("/api/v1/orders?limit=101").status_code == 422
