import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from uuid import uuid4
import httpx


@contextmanager
def server(module, path, inventory_url=""):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = dict(os.environ, DB_PATH=str(path), INVENTORY_URL=inventory_url)
    p = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            module + ":create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(timeout=0.5) as c:
            for _ in range(100):
                try:
                    if c.get(url + "/health/ready").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if p.poll() is not None:
                    raise RuntimeError("service exited")
                time.sleep(0.1)
            else:
                raise RuntimeError("service not ready")
        yield url
    finally:
        p.terminate()
        p.wait(10)


def test_real_http(tmp_path):
    with server("inventory_service.main", tmp_path / "stock") as inventory:
        with server("order_service.main", tmp_path / "orders", inventory) as orders:
            key = str(uuid4())
            body = {"product_id": "sku-demo-001", "quantity": 2}
            headers = {"Idempotency-Key": key}
            with httpx.Client(timeout=5) as c:
                a = c.post(orders + "/api/v1/orders", json=body, headers=headers)
                assert a.status_code == 201 and a.json()["status"] == "CONFIRMED"
                b = c.post(orders + "/api/v1/orders", json=body, headers=headers)
                assert b.status_code == 200 and b.json()["order_id"] == a.json()["order_id"]
                assert (
                    c.get(inventory + "/api/v1/products/sku-demo-001").json()["available_qty"] == 18
                )
                assert c.get(orders + "/api/v1/orders?status=CONFIRMED").json()["total"] == 1
                bad = c.post(
                    orders + "/api/v1/orders",
                    json={**body, "quantity": 99},
                    headers={"Idempotency-Key": str(uuid4())},
                )
                assert (
                    bad.status_code == 409 and bad.json()["error"]["code"] == "INSUFFICIENT_STOCK"
                )


def test_restart_recovers(tmp_path):
    from order_service import service
    from order_service.schemas import Request

    op = tmp_path / "orders"
    service.init(op)
    row, _ = service.create(op, str(uuid4()), Request(product_id="sku-demo-001", quantity=2))
    with server("inventory_service.main", tmp_path / "stock") as inventory:
        with server("order_service.main", op, inventory) as orders:
            with httpx.Client() as c:
                for _ in range(50):
                    result = c.get(orders + "/api/v1/orders/" + row["order_id"]).json()
                    if result["status"] == "CONFIRMED":
                        break
                    time.sleep(0.1)
                assert result["status"] == "CONFIRMED"


def test_real_http_cancel_and_create_replay(tmp_path):
    with server("inventory_service.main", tmp_path / "stock") as inventory:
        with server("order_service.main", tmp_path / "orders", inventory) as orders:
            with httpx.Client(timeout=5) as c:
                key = str(uuid4())
                body = {"product_id": "sku-demo-001", "quantity": 2}
                headers = {"Idempotency-Key": key}
                created = c.post(orders + "/api/v1/orders", json=body, headers=headers).json()
                url = orders + "/api/v1/orders/" + created["order_id"] + "/cancel"
                cancelled = c.post(url)
                assert cancelled.status_code == 200
                assert cancelled.json()["status"] == "CANCELLED"
                assert c.post(url).json()["cancelled_at"] == cancelled.json()["cancelled_at"]
                assert (
                    c.get(inventory + "/api/v1/products/sku-demo-001").json()["available_qty"] == 20
                )
                replay = c.post(orders + "/api/v1/orders", json=body, headers=headers)
                assert replay.status_code == 200 and replay.json()["status"] == "CANCELLED"
                assert c.get(orders + "/api/v1/orders?status=CANCELLED").json()["total"] == 1
                released = c.get(
                    inventory + "/internal/v1/reservations/" + created["order_id"]
                ).json()
                assert released["status"] == "RELEASED"


def test_real_pending_cancel_survives_restart(tmp_path):
    from order_service import service
    from order_service.schemas import Request

    op = tmp_path / "orders"
    sp = tmp_path / "stock"
    service.init(op)
    row, _ = service.create(op, str(uuid4()), Request(product_id="sku-demo-001", quantity=2))
    with server("inventory_service.main", sp) as inventory:
        row = service.advance(op, row, inventory)
        assert row["status"] == "CONFIRMED"
    # 库存服务已停止，HTTP取消必须返回处理中；订单进程随后也停止。
    with server("order_service.main", op, inventory) as order_url:
        result = httpx.post(order_url + "/api/v1/orders/" + row["order_id"] + "/cancel", timeout=5)
        assert result.status_code == 202 and result.json()["status"] == "CANCEL_PENDING"
    with server("inventory_service.main", sp) as inventory:
        with server("order_service.main", op, inventory) as order_url:
            with httpx.Client() as c:
                for _ in range(60):
                    current = c.get(order_url + "/api/v1/orders/" + row["order_id"]).json()
                    if current["status"] == "CANCELLED":
                        break
                    time.sleep(0.1)
                assert current["status"] == "CANCELLED"
                assert (
                    c.get(inventory + "/api/v1/products/sku-demo-001").json()["available_qty"] == 20
                )
