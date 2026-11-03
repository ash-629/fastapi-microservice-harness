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
