import logging

# 应用工厂无导入副作用，统一错误与请求关联。
import os
import json
import time
import sqlite3
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from . import service
from .repository import connect
from .schemas import Error, Product, ProductPage, Request, Reservation, ReleaseResult


def create_app(db_path=None, inventory_url=None, recovery=True):
    path = str(db_path or os.environ.get("DB_PATH", ".runtime/inventory.sqlite3"))

    @asynccontextmanager
    async def lifespan(app):
        service.init(path)
        yield

    app = FastAPI(
        title="inventory Service",
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
            db.execute("SELECT 1 FROM products LIMIT 1")
        return {"status": "ready"}

    @app.get("/api/v1/products", response_model=ProductPage, operation_id="list_products")
    def products(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        with connect(path) as db:
            db.execute("BEGIN")
            return {
                "items": [
                    dict(x)
                    for x in db.execute(
                        "SELECT * FROM products ORDER BY product_id LIMIT ? OFFSET ?",
                        (limit, offset),
                    )
                ],
                "total": db.execute("SELECT COUNT(*) FROM products").fetchone()[0],
                "limit": limit,
                "offset": offset,
            }

    @app.get("/api/v1/products/{product_id}", response_model=Product, operation_id="get_product")
    def product(product_id: str):
        with connect(path) as db:
            row = db.execute("SELECT * FROM products WHERE product_id=?", (product_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "PRODUCT_NOT_FOUND")
        return dict(row)

    @app.put(
        "/internal/v1/reservations/{order_id}",
        response_model=Reservation,
        operation_id="put_reservation",
    )
    def reserve(order_id: UUID, req: Request):
        return service.reserve(path, str(order_id), req)

    @app.put(
        "/internal/v1/reservations/{order_id}/release",
        response_model=ReleaseResult,
        operation_id="release_reservation",
    )
    def release(order_id: UUID, req: Request):
        try:
            return service.release(path, str(order_id), req)
        except service.ReservationNotFound:
            raise HTTPException(404, "RESERVATION_NOT_FOUND") from None
        except service.ReservationNotReleasable:
            raise HTTPException(409, "RESERVATION_NOT_RELEASABLE") from None

    @app.get(
        "/internal/v1/reservations/{order_id}",
        response_model=Reservation,
        operation_id="get_reservation",
    )
    def reservation(order_id: UUID):
        with connect(path) as db:
            row = db.execute(
                "SELECT * FROM reservations WHERE order_id=?", (str(order_id),)
            ).fetchone()
        if row is None:
            raise HTTPException(404, "RESERVATION_NOT_FOUND")
        return dict(row)

    return app
