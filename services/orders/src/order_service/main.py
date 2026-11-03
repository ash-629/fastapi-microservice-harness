# 应用工厂无导入副作用，统一错误与请求关联。
import logging
import os
import json
import time
import sqlite3
import threading
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, Query
from fastapi import Request as HTTPRequest
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from . import service
from .repository import connect
from .schemas import Error, Order, OrderPage, Request, OrderState


def create_app(db_path=None, inventory_url=None, recovery=True):
    path = str(db_path or os.environ.get("DB_PATH", ".runtime/orders.sqlite3"))
    url = inventory_url or os.environ.get("INVENTORY_URL", "http://127.0.0.1:8002")
    stop = threading.Event()

    def worker():
        while not stop.wait(1):
            try:
                service.reconcile(path, url, stop_event=stop)
            except Exception:
                logging.exception("recovery_failed")

    @asynccontextmanager
    async def lifespan(app):
        stop.clear()
        service.init(path)
        thread = None
        if recovery:
            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
        try:
            yield
        finally:
            stop.set()
            if thread:
                thread.join(timeout=3)

    app = FastAPI(
        title="orders Service",
        lifespan=lifespan,
        responses={c: {"model": Error} for c in [404, 409, 422, 500, 503]},
    )

    @app.middleware("http")
    async def trace(request, call_next):
        try:
            rid = str(UUID(request.headers.get("X-Request-ID", "")))
        except ValueError:
            rid = str(uuid4())
        request.state.rid = rid
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logging.getLogger("uvicorn.error").exception("unhandled_request_error")
            response = err(request, "INTERNAL_ERROR", 500)
        logging.getLogger("uvicorn.error").info(
            json.dumps(
                {
                    "service": app.title,
                    "request_id": rid,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                }
            )
        )
        response.headers["X-Request-ID"] = rid
        return response

    def err(request, code, status, details=None):
        return JSONResponse(
            status_code=status,
            content={
                "error": {"code": code, "message": code, "details": details or {}},
                "request_id": getattr(request.state, "rid", ""),
            },
        )

    @app.exception_handler(service.IdempotencyConflict)
    async def conflict(request, exc):
        return err(request, "IDEMPOTENCY_CONFLICT", 409)

    @app.exception_handler(RequestValidationError)
    async def validation(request, exc):
        return err(
            request,
            "VALIDATION_ERROR",
            422,
            {"fields": [{"loc": list(e["loc"]), "message": e["msg"]} for e in exc.errors()]},
        )

    @app.exception_handler(HTTPException)
    async def missing(request, exc):
        return err(request, str(exc.detail), exc.status_code)

    @app.exception_handler(sqlite3.Error)
    async def storage(request, exc):
        return err(request, "STORAGE_UNAVAILABLE", 503)

    @app.exception_handler(Exception)
    async def internal(request, exc):
        return err(request, "INTERNAL_ERROR", 500)

    @app.get("/health/live", operation_id="live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready", operation_id="ready")
    def ready():
        with connect(path) as db:
            db.execute("SELECT 1 FROM orders LIMIT 1")
        return {"status": "ready"}

    @app.post(
        "/api/v1/orders",
        response_model=Order,
        status_code=201,
        responses={200: {"model": Order}, 202: {"model": Order}},
        operation_id="create_order",
    )
    def create(req: Request, request: HTTPRequest, idempotency_key: UUID = Header()):
        row, fresh = service.create(path, str(idempotency_key), req)
        row = service.advance(path, row, url, request.state.rid)
        if row["status"] == "REJECTED":
            return err(
                request,
                row["rejection_code"],
                404 if row["rejection_code"] == "PRODUCT_NOT_FOUND" else 409,
                {"order_id": row["order_id"]},
            )
        status = (
            202
            if row["status"] in ("PENDING_INVENTORY", "CANCEL_PENDING")
            else (201 if fresh else 200)
        )
        return JSONResponse(
            status_code=status,
            content=Order.model_validate(row).model_dump(),
            headers={"Location": f"/api/v1/orders/{row['order_id']}", "Retry-After": "1"},
        )

    @app.post(
        "/api/v1/orders/{order_id}/cancel",
        response_model=Order,
        responses={202: {"model": Order}},
        operation_id="cancel_order",
    )
    def cancel(order_id: UUID, request: HTTPRequest):
        try:
            row = service.request_cancel(path, str(order_id))
        except KeyError:
            raise HTTPException(404, "ORDER_NOT_FOUND") from None
        except service.OrderNotCancellable:
            raise HTTPException(409, "ORDER_NOT_CANCELLABLE") from None
        row = service.advance_cancel(path, row, url, request.state.rid)
        code = 202 if row["status"] == "CANCEL_PENDING" else 200
        headers = {"Location": f"/api/v1/orders/{order_id}"}
        if code == 202:
            headers["Retry-After"] = "1"
        return JSONResponse(
            status_code=code, content=Order.model_validate(row).model_dump(), headers=headers
        )

    @app.get("/api/v1/orders", response_model=OrderPage, operation_id="list_orders")
    def orders(
        status: OrderState | None = None,
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        where = " WHERE status=?" if status else ""
        args = [status] if status else []
        with connect(path) as db:
            db.execute("BEGIN")
            rows = db.execute(
                "SELECT * FROM orders"
                + where
                + " ORDER BY created_at DESC,order_id DESC LIMIT ? OFFSET ?",
                args + [limit, offset],
            ).fetchall()
            return {
                "items": [dict(x) for x in rows],
                "total": db.execute("SELECT COUNT(*) FROM orders" + where, args).fetchone()[0],
                "limit": limit,
                "offset": offset,
            }

    @app.get("/api/v1/orders/{order_id}", response_model=Order, operation_id="get_order")
    def order(order_id: UUID):
        with connect(path) as db:
            row = db.execute("SELECT * FROM orders WHERE order_id=?", (str(order_id),)).fetchone()
        if row is None:
            raise HTTPException(404, "ORDER_NOT_FOUND")
        return dict(row)

    return app
