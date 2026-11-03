# 覆盖 F01/F02：边界模型。
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    product_id: str = Field(min_length=1, max_length=80)
    quantity: int = Field(strict=True, ge=1, le=99)


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict = Field(default_factory=dict)


class Error(BaseModel):
    error: ErrorDetail
    request_id: str


class Product(BaseModel):
    product_id: str
    sku: str
    name: str
    available_qty: int
    updated_at: str


class Order(BaseModel):
    order_id: str
    product_id: str
    quantity: int
    status: Literal["PENDING_INVENTORY", "CONFIRMED", "REJECTED"]
    rejection_code: str | None
    needs_attention: bool
    created_at: str
    updated_at: str


class Reservation(BaseModel):
    model_config = ConfigDict(strict=True)
    order_id: str
    product_id: str
    quantity: int
    status: Literal["RESERVED", "REJECTED"]
    rejection_code: str | None


class ProductPage(BaseModel):
    items: list[Product]
    total: int
    limit: int
    offset: int


class OrderPage(BaseModel):
    items: list[Order]
    total: int
    limit: int
    offset: int
