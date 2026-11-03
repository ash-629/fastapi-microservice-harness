# 覆盖 F01/F02/R01/R02：事务、幂等、真实结果丢失后的恢复。
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from inventory_service import service as stock
from inventory_service.main import create_app as inventory_app
from inventory_service.schemas import Request as StockRequest
from order_service import service as orders
from order_service.main import create_app as order_app
from order_service.schemas import Request


def test_stock_concurrency(tmp_path):
    path = tmp_path / "stock.db"
    stock.init(path)

    def reserve(_):
        return stock.reserve(
            path, str(uuid4()), StockRequest(product_id="sku-demo-001", quantity=1)
        )["status"]

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(reserve, range(30)))
    assert results.count("RESERVED") == 20
    with stock.connect(path) as db:
        assert (
            db.execute(
                "SELECT available_qty FROM products WHERE product_id=?", ("sku-demo-001",)
            ).fetchone()[0]
            == 0
        )


def test_order_idempotency_and_loss(tmp_path):
    sp = tmp_path / "stock.db"
    op = tmp_path / "orders.db"
    stock.init(sp)
    orders.init(op)
    req = Request(product_id="sku-demo-001", quantity=2)
    key = str(uuid4())
    row, fresh = orders.create(op, key, req)
    assert fresh

    def lost(request):
        stock.reserve(sp, row["order_id"], StockRequest.model_validate_json(request.content))
        raise httpx.ReadTimeout("response lost")

    with httpx.Client(transport=httpx.MockTransport(lost)) as client:
        pending = orders.advance(op, row, "http://stock", client=client)
    assert pending["status"] == "PENDING_INVENTORY"

    def restored(request):
        return httpx.Response(
            200,
            json=stock.reserve(
                sp, row["order_id"], StockRequest.model_validate_json(request.content)
            ),
        )

    with httpx.Client(transport=httpx.MockTransport(restored)) as client:
        result = orders.advance(op, pending, "http://stock", client=client, recovery=True)
    assert result["status"] == "CONFIRMED"
    same, fresh = orders.create(op, key, req)
    assert not fresh and same["order_id"] == row["order_id"]
    with pytest.raises(ValueError):
        orders.create(op, key, Request(product_id="sku-demo-001", quantity=3))
    with stock.connect(sp) as db:
        assert (
            db.execute(
                "SELECT available_qty FROM products WHERE product_id=?", ("sku-demo-001",)
            ).fetchone()[0]
            == 18
        )


def test_rejected_replay(tmp_path):
    path = tmp_path / "db"
    stock.init(path)
    oid = str(uuid4())
    req = StockRequest(product_id="sku-demo-001", quantity=99)
    assert stock.reserve(path, oid, req)["rejection_code"] == "INSUFFICIENT_STOCK"
    assert stock.reserve(path, oid, req)["status"] == "REJECTED"
    with pytest.raises(ValueError):
        stock.reserve(path, oid, StockRequest(product_id="sku-demo-001", quantity=1))


def test_api_validation_and_filter(tmp_path):
    with TestClient(order_app(tmp_path / "orders", recovery=False)) as client:
        assert client.get("/api/v1/orders?status=INVALID").status_code == 422
        assert client.get("/api/v1/orders?status=CONFIRMED").json()["total"] == 0
        res = client.post(
            "/api/v1/orders",
            json={"product_id": "a", "quantity": True},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert res.status_code == 422 and res.json()["error"]["code"] == "VALIDATION_ERROR"
    with TestClient(inventory_app(tmp_path / "stock")) as client:
        assert client.get("/api/v1/products").json()["total"] == 3
        assert client.get("/api/v1/products/missing").json()["error"]["code"] == "PRODUCT_NOT_FOUND"


def test_import_no_side_effect(tmp_path, monkeypatch):
    path = tmp_path / "no-db"
    monkeypatch.setenv("DB_PATH", str(path))
    order_app().openapi()
    inventory_app().openapi()
    assert not path.exists()
