"""Store-scoped checkout, order operations, analytics, and public FAQ routes."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import secrets
import sqlite3
import base64
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

if __package__:
    from . import config as _config  # noqa: F401 - loads JWT_SECRET for lookup-code HMAC
    from . import auth
    from .database import get_connection
else:
    import config as _config  # noqa: F401 - loads JWT_SECRET for lookup-code HMAC
    import auth
    from database import get_connection

router = APIRouter()
STATUSES = ("placed", "packed", "shipped", "delivered", "cancelled")
TRANSITIONS = {
    "placed": {"packed", "cancelled"},
    "packed": {"shipped", "cancelled"},
    "shipped": {"delivered"},
    "delivered": set(),
    "cancelled": set(),
}


class CheckoutItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: int = Field(gt=0)
    quantity: int = Field(ge=1, le=100)
    variant_name: str | None = Field(default=None, min_length=1, max_length=50)
    variant_value: str | None = Field(default=None, min_length=1, max_length=100)


class CheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[CheckoutItem] = Field(min_length=1, max_length=50)
    customer_name: str = Field(min_length=1, max_length=120)
    customer_email: str = Field(min_length=3, max_length=254)
    customer_phone: str = Field(min_length=5, max_length=40)
    address_line1: str = Field(min_length=1, max_length=200)
    address_line2: str = Field(default="", max_length=200)
    city: str = Field(min_length=1, max_length=100)
    region: str = Field(default="", max_length=100)
    postal_code: str = Field(min_length=1, max_length=30)
    country: str = Field(min_length=2, max_length=80)
    delivery_notes: str = Field(default="", max_length=500)

    @field_validator("customer_name", "customer_phone", "address_line1", "address_line2", "city", "region", "postal_code", "country", "delivery_notes")
    @classmethod
    def trim_fields(cls, value: str) -> str:
        return value.strip()

    @field_validator("customer_email")
    @classmethod
    def check_email(cls, value: str) -> str:
        return auth.normalize_email(value)

    @field_validator("country")
    @classmethod
    def nonempty_country(cls, value: str) -> str:
        if not value:
            raise ValueError("Country is required")
        return value

    @field_validator("customer_name", "address_line1", "city", "postal_code")
    @classmethod
    def required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("This field must not be empty")
        return normalized

    @field_validator("customer_phone")
    @classmethod
    def valid_phone(cls, value: str) -> str:
        if sum(character.isdigit() for character in value) < 5:
            raise ValueError("Enter a valid phone number")
        return value


class OrderStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["placed", "packed", "shipped", "delivered", "cancelled"]


class TrackOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_ref: str = Field(min_length=12, max_length=100)
    lookup_code: str = Field(min_length=20, max_length=100)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=500)

    @field_validator("message")
    @classmethod
    def trim_message(cls, value: str) -> str:
        return value.strip()


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _hash_lookup(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _lookup_code_for_ref(public_ref: str) -> str:
    secret = os.environ["JWT_SECRET"].encode("utf-8")
    digest = hmac.new(secret, b"store-order-lookup\0" + public_ref.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _hash_request(request: CheckoutRequest) -> str:
    payload = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _published_store(connection: sqlite3.Connection, slug: str) -> sqlite3.Row:
    store = connection.execute(
        "SELECT id, slug, name, description FROM stores WHERE slug = ? AND is_published = 1",
        (slug,),
    ).fetchone()
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")
    return store


def _variants(row: sqlite3.Row) -> list[dict[str, Any]]:
    try:
        values = json.loads(row["variants_json"] or "[]")
        return values if isinstance(values, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


@router.post("/api/stores/{slug}/checkout", status_code=status.HTTP_201_CREATED)
def create_order(
    slug: str,
    request: CheckoutRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=16, max_length=128),
):
    if not idempotency_key.strip() or len(idempotency_key.strip()) != len(idempotency_key):
        raise HTTPException(status_code=422, detail="Idempotency-Key must be a non-empty opaque value")
    try:
        auth.validate_jwt_configuration()
    except auth.AuthConfigurationError as error:
        raise HTTPException(status_code=503, detail="Order lookup is not configured") from error
    seen: set[tuple[int, str | None, str | None]] = set()
    for item in request.items:
        key = (item.product_id, item.variant_name, item.variant_value)
        if key in seen:
            raise HTTPException(status_code=422, detail="Combine duplicate product and variant lines")
        seen.add(key)

    order_ref = secrets.token_urlsafe(24)
    lookup_code = _lookup_code_for_ref(order_ref)
    request_hash = _hash_request(request)
    try:
        with get_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            store = _published_store(connection, slug)
            prior = connection.execute(
                "SELECT public_ref, status, subtotal, request_hash FROM orders WHERE store_id = ? AND idempotency_key = ?",
                (store["id"], idempotency_key),
            ).fetchone()
            if prior:
                if prior["request_hash"] and not hmac.compare_digest(prior["request_hash"], request_hash):
                    raise HTTPException(status_code=409, detail="This checkout key was already used for a different request")
                return {
                    "order_ref": prior["public_ref"], "status": prior["status"],
                    "subtotal": prior["subtotal"], "lookup_code": _lookup_code_for_ref(prior["public_ref"]),
                    "payment": "Demo checkout; no payment was processed.", "replayed": True,
                }

            resolved: list[dict[str, Any]] = []
            subtotal = Decimal("0.00")
            for item in request.items:
                product = connection.execute(
                    """SELECT id, name, category, sku, price, discount_percent, stock,
                              variants_json FROM products WHERE id = ? AND store_id = ?""",
                    (item.product_id, store["id"]),
                ).fetchone()
                if product is None:
                    raise HTTPException(status_code=422, detail="A product is unavailable")
                variants = _variants(product)
                selected_variant = None
                if variants:
                    if not item.variant_name or not item.variant_value:
                        raise HTTPException(status_code=422, detail=f"Choose a variant for {product['name']}")
                    selected_variant = next((variant for variant in variants if
                        str(variant.get("name")) == item.variant_name and
                        str(variant.get("value")) == item.variant_value), None)
                    if selected_variant is None:
                        raise HTTPException(status_code=422, detail="A selected product variant is unavailable")
                    variant_stock = int(selected_variant.get("stock", 0))
                    if variant_stock < item.quantity:
                        raise HTTPException(status_code=409, detail=f"Insufficient stock for {product['name']}")
                elif item.variant_name or item.variant_value:
                    raise HTTPException(status_code=422, detail="This product has no selectable variant")
                if int(product["stock"]) < item.quantity:
                    raise HTTPException(status_code=409, detail=f"Insufficient stock for {product['name']}")

                base_price = float(product["price"])
                discount_value = float(product["discount_percent"] or 0)
                adjustment = float(selected_variant.get("price_adjustment", 0)) if selected_variant else 0.0
                if not math.isfinite(base_price) or base_price <= 0 or not math.isfinite(discount_value) or not 0 <= discount_value <= 90 or not math.isfinite(adjustment):
                    raise HTTPException(status_code=422, detail=f"Invalid price or discount for {product['name']}")
                list_price = Decimal(str(base_price))
                if selected_variant:
                    list_price += Decimal(str(adjustment))
                if list_price <= 0:
                    raise HTTPException(status_code=422, detail=f"Invalid price for {product['name']}")
                discount = Decimal(str(discount_value))
                unit_price = _money(list_price * (Decimal("1") - discount / Decimal("100")))
                line_total = _money(unit_price * item.quantity)
                subtotal += line_total
                resolved.append({
                    "request": item, "product": product, "variant": selected_variant,
                    "unit_price": unit_price, "line_total": line_total, "discount": discount,
                })

            cursor = connection.execute(
                """INSERT INTO orders
                   (store_id, public_ref, lookup_hash, request_hash, idempotency_key, customer_name, customer_email,
                    customer_phone, address_line1, address_line2, city, region, postal_code, country,
                    delivery_notes, status, subtotal)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'placed', ?)""",
                (store["id"], order_ref, _hash_lookup(lookup_code), request_hash, idempotency_key,
                 request.customer_name, request.customer_email, request.customer_phone,
                 request.address_line1, request.address_line2, request.city, request.region,
                 request.postal_code, request.country, request.delivery_notes, float(_money(subtotal))),
            )
            order_id = cursor.lastrowid
            for item in resolved:
                product = item["product"]
                line = item["request"]
                update = connection.execute(
                    "UPDATE products SET stock = stock - ? WHERE id = ? AND store_id = ? AND stock >= ?",
                    (line.quantity, product["id"], store["id"], line.quantity),
                )
                if update.rowcount != 1:
                    raise HTTPException(status_code=409, detail=f"Insufficient stock for {product['name']}")
                variant_json = None
                if item["variant"]:
                    variant_json = json.dumps({
                        "name": item["variant"]["name"], "value": item["variant"]["value"],
                        "price_adjustment": item["variant"].get("price_adjustment", 0),
                    })
                    variants = _variants(product)
                    for variant in variants:
                        if variant.get("name") == line.variant_name and variant.get("value") == line.variant_value:
                            variant["stock"] = int(variant.get("stock", 0)) - line.quantity
                            break
                    connection.execute(
                        "UPDATE products SET variants_json = ? WHERE id = ? AND store_id = ?",
                        (json.dumps(variants), product["id"], store["id"]),
                    )
                connection.execute(
                    """INSERT INTO order_items
                       (order_id, product_id, product_name, category, sku, variant_json, quantity,
                        unit_price, discount_percent, line_total)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (order_id, product["id"], product["name"], product["category"], product["sku"],
                     variant_json, line.quantity, float(item["unit_price"]), float(item["discount"]),
                     float(item["line_total"])),
                )
            connection.execute(
                "INSERT INTO order_events (order_id, from_status, to_status) VALUES (?, NULL, 'placed')",
                (order_id,),
            )
    except sqlite3.IntegrityError as error:
        # A concurrent replay can win the unique idempotency key after our read.
        with get_connection() as connection:
            prior = connection.execute(
                "SELECT public_ref, status, subtotal, request_hash FROM orders WHERE store_id = "
                "(SELECT id FROM stores WHERE slug = ?) AND idempotency_key = ?",
                (slug, idempotency_key),
            ).fetchone()
        if prior:
            if prior["request_hash"] and not hmac.compare_digest(prior["request_hash"], request_hash):
                raise HTTPException(status_code=409, detail="This checkout key was already used for a different request") from error
            return {
                "order_ref": prior["public_ref"], "status": prior["status"],
                "subtotal": prior["subtotal"], "lookup_code": _lookup_code_for_ref(prior["public_ref"]),
                "payment": "Demo checkout; no payment was processed.", "replayed": True,
            }
        raise HTTPException(status_code=409, detail="Checkout could not be completed") from error
    return {
        "order_ref": order_ref, "status": "placed", "subtotal": float(_money(subtotal)),
        "lookup_code": lookup_code, "payment": "Demo checkout; no payment was processed.",
        "replayed": False,
    }


@router.get("/api/stores/{slug}/products/{product_id}")
def get_public_product(slug: str, product_id: int):
    with get_connection() as connection:
        store = _published_store(connection, slug)
        row = connection.execute(
            """SELECT id, name, category, price, original_price, discount_percent, stock,
                      image_url, images_json, variants_json, description
               FROM products WHERE id = ? AND store_id = ?""",
            (product_id, store["id"]),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Product not found")
    product = dict(row)
    product["images"] = json.loads(product.pop("images_json") or "[]")
    product["variants"] = json.loads(product.pop("variants_json") or "[]")
    return product


@router.post("/api/orders/track")
def track_order(request: TrackOrderRequest):
    with get_connection() as connection:
        order = connection.execute(
            "SELECT id, public_ref, status, created_at, updated_at, lookup_hash "
            "FROM orders WHERE public_ref = ?", (request.order_ref,),
        ).fetchone()
        candidate = _hash_lookup(request.lookup_code)
        if order is None or not hmac.compare_digest(order["lookup_hash"] if order else "0" * 64, candidate):
            raise HTTPException(status_code=404, detail="Order not found")
        items = connection.execute(
            "SELECT product_name, quantity, variant_json FROM order_items WHERE order_id = ? ORDER BY id",
            (order["id"],),
        ).fetchall()
        events = connection.execute(
            "SELECT to_status AS status, created_at FROM order_events WHERE order_id = ? ORDER BY id",
            (order["id"],),
        ).fetchall()
    return {
        "order_ref": order["public_ref"], "status": order["status"],
        "created_at": order["created_at"], "updated_at": order["updated_at"],
        "items": [{"name": row["product_name"], "quantity": row["quantity"],
                   "variant": json.loads(row["variant_json"]) if row["variant_json"] else None} for row in items],
        "events": [dict(row) for row in events],
    }


def _owner_order(row: sqlite3.Row, items: list[sqlite3.Row] | None = None) -> dict[str, Any]:
    result = dict(row)
    if items is not None:
        result["items"] = [{
            "product_id": item["product_id"], "name": item["product_name"], "category": item["category"],
            "sku": item["sku"], "variant": json.loads(item["variant_json"]) if item["variant_json"] else None,
            "quantity": item["quantity"], "unit_price": item["unit_price"],
            "discount_percent": item["discount_percent"], "line_total": item["line_total"],
        } for item in items]
    return result


@router.get("/api/owner/stores/{slug}/orders")
def list_owner_orders(
    slug: str,
    order_status: Literal["placed", "packed", "shipped", "delivered", "cancelled"] | None = Query(default=None, alias="status"),
    search: str = Query(default="", max_length=100),
    limit: int = Query(default=50, ge=1, le=100),
    store: dict[str, Any] = Depends(auth.require_store_owner),
):
    if store["slug"] != slug:
        raise HTTPException(status_code=404, detail="Store not found")
    clauses = ["store_id = ?"]
    params: list[Any] = [store["id"]]
    if order_status:
        clauses.append("status = ?")
        params.append(order_status)
    if search.strip():
        term = f"%{search.strip()}%"
        clauses.append("(public_ref LIKE ? OR customer_name LIKE ? OR customer_email LIKE ?)")
        params.extend([term] * 3)
    params.append(limit)
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT id, public_ref, customer_name, customer_email, customer_phone, address_line1, "
            "address_line2, city, region, postal_code, country, delivery_notes, status, subtotal, "
            "payment_method, payment_status, created_at, updated_at FROM orders WHERE "
            + " AND ".join(clauses) + " ORDER BY created_at DESC, id DESC LIMIT ?", params,
        ).fetchall()
        result = []
        for row in rows:
            items = connection.execute(
                "SELECT * FROM order_items WHERE order_id = ? ORDER BY id", (row["id"],)
            ).fetchall()
            result.append(_owner_order(row, items))
    return result


@router.patch("/api/owner/stores/{slug}/orders/{order_id}")
def update_owner_order_status(
    slug: str,
    order_id: int,
    request: OrderStatusUpdate,
    store: dict[str, Any] = Depends(auth.require_store_owner),
):
    if store["slug"] != slug:
        raise HTTPException(status_code=404, detail="Store not found")
    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        order = connection.execute(
            "SELECT id, status FROM orders WHERE id = ? AND store_id = ?",
            (order_id, store["id"]),
        ).fetchone()
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        previous = order["status"]
        if request.status not in TRANSITIONS[previous]:
            raise HTTPException(status_code=409, detail=f"Cannot change order from {previous} to {request.status}")
        if request.status == "cancelled":
            items = connection.execute(
                "SELECT product_id, quantity, variant_json FROM order_items WHERE order_id = ?",
                (order_id,),
            ).fetchall()
            for item in items:
                if item["product_id"] is None:
                    continue
                connection.execute(
                    "UPDATE products SET stock = stock + ? WHERE id = ? AND store_id = ?",
                    (item["quantity"], item["product_id"], store["id"]),
                )
                if item["variant_json"]:
                    selected = json.loads(item["variant_json"])
                    product = connection.execute(
                        "SELECT variants_json FROM products WHERE id = ? AND store_id = ?",
                        (item["product_id"], store["id"]),
                    ).fetchone()
                    if product:
                        variants = json.loads(product["variants_json"] or "[]")
                        for variant in variants:
                            if variant.get("name") == selected["name"] and variant.get("value") == selected["value"]:
                                variant["stock"] = int(variant.get("stock", 0)) + item["quantity"]
                                break
                        connection.execute(
                            "UPDATE products SET variants_json = ? WHERE id = ? AND store_id = ?",
                            (json.dumps(variants), item["product_id"], store["id"]),
                        )
        connection.execute(
            "UPDATE orders SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND store_id = ? AND status = ?",
            (request.status, order_id, store["id"], previous),
        )
        connection.execute(
            "INSERT INTO order_events (order_id, from_status, to_status) VALUES (?, ?, ?)",
            (order_id, previous, request.status),
        )
        row = connection.execute(
            "SELECT id, public_ref, status, subtotal, created_at, updated_at FROM orders WHERE id = ? AND store_id = ?",
            (order_id, store["id"]),
        ).fetchone()
    return dict(row)


@router.get("/api/owner/stores/{slug}/analytics")
def get_store_analytics(
    slug: str,
    from_date: date | None = None,
    to_date: date | None = None,
    store: dict[str, Any] = Depends(auth.require_store_owner),
):
    if store["slug"] != slug:
        raise HTTPException(status_code=404, detail="Store not found")
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=422, detail="from_date must be before to_date")
    clauses = ["store_id = ?"]
    params: list[Any] = [store["id"]]
    if from_date:
        clauses.append("date(created_at) >= ?")
        params.append(from_date.isoformat())
    if to_date:
        clauses.append("date(created_at) <= ?")
        params.append(to_date.isoformat())
    where = " AND ".join(clauses)
    with get_connection() as connection:
        summary = connection.execute(
            f"""SELECT COUNT(*) AS total_orders,
                       COALESCE(SUM(CASE WHEN status = 'delivered' THEN subtotal ELSE 0 END), 0) AS delivered_revenue,
                       SUM(CASE WHEN status = 'placed' THEN 1 ELSE 0 END) AS placed,
                       SUM(CASE WHEN status = 'packed' THEN 1 ELSE 0 END) AS packed,
                       SUM(CASE WHEN status = 'shipped' THEN 1 ELSE 0 END) AS shipped,
                       SUM(CASE WHEN status = 'delivered' THEN 1 ELSE 0 END) AS delivered,
                       SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled
                FROM orders WHERE {where}""", params,
        ).fetchone()
        recent = connection.execute(
            f"SELECT public_ref, customer_name, status, subtotal, created_at FROM orders WHERE {where} ORDER BY created_at DESC, id DESC LIMIT 8",
            params,
        ).fetchall()
        low_stock = connection.execute(
            "SELECT id, name, category, stock, sku FROM products WHERE store_id = ? AND stock <= 5 ORDER BY stock, name COLLATE NOCASE LIMIT 20",
            (store["id"],),
        ).fetchall()
    return {
        "total_orders": summary["total_orders"],
        "delivered_revenue": round(float(summary["delivered_revenue"] or 0), 2),
        "revenue_definition": "Order value for delivered orders only; checkout is demo-only and no payment is processed.",
        "orders_by_status": {name: summary[name] or 0 for name in STATUSES},
        "recent_orders": [dict(row) for row in recent],
        "low_stock_products": [dict(row) for row in low_stock],
        "date_range": {"from": from_date.isoformat() if from_date else None, "to": to_date.isoformat() if to_date else None},
    }


def _public_faq_answer(message: str, store: sqlite3.Row, products: list[sqlite3.Row], customization: sqlite3.Row | None) -> tuple[str, list[dict[str, Any]]]:
    text = message.casefold()
    product_facts = [
        {"name": row["name"], "category": row["category"], "price": row["price"],
         "discount_percent": row["discount_percent"], "stock": row["stock"]}
        for row in products
    ]
    if any(word in text for word in ("shipping policy", "shipping", "delivery policy")):
        value = customization["shipping_policy"] if customization else ""
        return (value.strip(), [{"shipping_policy": value}]) if value and value.strip() else ("I don't have that data.", [])
    if any(word in text for word in ("return policy", "returns", "refund policy", "refund")):
        value = customization["returns_policy"] if customization else ""
        return (value.strip(), [{"returns_policy": value}]) if value and value.strip() else ("I don't have that data.", [])
    if any(word in text for word in ("contact", "email", "phone", "telephone")):
        contacts = {}
        if customization:
            if customization["contact_email"]:
                contacts["email"] = customization["contact_email"]
            if customization["contact_phone"]:
                contacts["phone"] = customization["contact_phone"]
        if not contacts:
            return "I don't have that data.", []
        return "Store contact: " + ", ".join(f"{key}: {value}" for key, value in contacts.items()), [contacts]
    if any(word in text for word in ("about", "description", "store name", "who are you")):
        description = store["description"].strip()
        if not description and not store["name"]:
            return "I don't have that data.", []
        answer = store["name"] + (f": {description}" if description else "")
        return answer, [{"name": store["name"], "description": description}]
    if any(word in text for word in ("category", "categories")):
        categories = sorted({row["category"] for row in products}, key=str.casefold)
        return ("Categories: " + ", ".join(categories), [{"categories": categories}]) if categories else ("I don't have that data.", [])
    if any(word in text for word in ("products", "catalog", "what do you sell", "list items")):
        if not products:
            return "I don't have that data.", []
        lines = [f"{p['name']} ({p['category']}): ₹{p['price']:.2f}, stock {p['stock']}" for p in products]
        return "Products: " + "; ".join(lines), product_facts
    matches = [row for row in products if row["name"].casefold() in text]
    if not matches:
        # Name tokens are matched against rows already scoped to this published store.
        tokens = {token for token in text.replace("?", " ").replace(",", " ").split() if len(token) > 3}
        matches = [row for row in products if tokens & set(row["name"].casefold().split())]
    if matches and any(word in text for word in ("price", "cost", "stock", "available", "availability", "in stock", "sold out")):
        item = matches[0]
        effective = float(item["price"])
        if item["discount_percent"]:
            effective = round(effective * (1 - float(item["discount_percent"]) / 100), 2)
        if any(word in text for word in ("stock", "available", "availability", "in stock", "sold out")):
            answer = f"{item['name']} has {item['stock']} in stock." if item["stock"] else f"{item['name']} is currently out of stock."
        else:
            answer = f"{item['name']} costs ₹{effective:.2f}."
        return answer, [next(fact for fact in product_facts if fact["name"] == item["name"])]
    return "I don't have that data.", []


@router.post("/api/stores/{slug}/chat")
def store_chat(slug: str, request: ChatRequest):
    # Fixed, deterministic intent handling: no model receives customer prompts or
    # database text, and every query is scoped using the published store slug.
    with get_connection() as connection:
        store = _published_store(connection, slug)
        products = connection.execute(
            "SELECT name, category, price, discount_percent, stock FROM products WHERE store_id = ? ORDER BY name COLLATE NOCASE LIMIT 100",
            (store["id"],),
        ).fetchall()
        customization = connection.execute(
            "SELECT contact_email, contact_phone, shipping_policy, returns_policy FROM store_customizations WHERE store_id = ?",
            (store["id"],),
        ).fetchone()
    answer, evidence = _public_faq_answer(request.message, store, products, customization)
    return {"answer": answer, "supporting_data": evidence}
