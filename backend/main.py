import json
import secrets
from pydantic import BaseModel, Field
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field
from pwdlib import PasswordHash

from database import get_db, init_db

app = FastAPI(title="Hackathon Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

password_hash = PasswordHash.recommended()
bearer = HTTPBearer()


def get_secret():
    secret = os.environ.get("JWT_SECRET_KEY")
    if not secret:
        raise HTTPException(
            status_code=500,
            detail="JWT_SECRET_KEY is not configured",
        )
    return secret


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


def create_token(user_id: int, email: str, role: str):
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "iat": now,
        "exp": now + timedelta(hours=12),
    }
    return jwt.encode(payload, get_secret(), algorithm="HS256")


def current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
):
    try:
        payload = jwt.decode(
            credentials.credentials,
            get_secret(),
            algorithms=["HS256"],
        )
        user_id = int(payload["sub"])
    except HTTPException:
        raise
    except (jwt.InvalidTokenError, KeyError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    with get_db() as connection:
        user = connection.execute(
            """
            SELECT id, email, role, store_id
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()

    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists")

    return dict(user)


@app.on_event("startup")
def startup():
    init_db()


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


@app.post("/api/auth/register", status_code=201)
def register(data: RegisterRequest):
    email = str(data.email).strip().lower()
    hashed_password = password_hash.hash(data.password)

    try:
        with get_db() as connection:
            cursor = connection.execute(
                """
                INSERT INTO users (email, password_hash, role)
                VALUES (?, ?, 'owner')
                """,
                (email, hashed_password),
            )
            user_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists",
        )

    return {
        "message": "Account created",
        "user_id": user_id,
        "email": email,
    }


@app.post("/api/auth/login")
def login(data: LoginRequest):
    email = str(data.email).strip().lower()

    with get_db() as connection:
        user = connection.execute(
            """
            SELECT id, email, password_hash, role, store_id
            FROM users
            WHERE email = ?
            """,
            (email,),
        ).fetchone()

    if user is None or not password_hash.verify(
        data.password, user["password_hash"]
    ):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_token(user["id"], user["email"], user["role"])

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "email": user["email"],
            "role": user["role"],
            "store_id": user["store_id"],
        },
    }


@app.get("/api/auth/me")
def get_me(user: dict = Depends(current_user)):
    return user

from pydantic import BaseModel, Field
from fastapi import Depends, HTTPException


class StoreCreateRequest(BaseModel):
    store_name: str = Field(min_length=2, max_length=100)
    slug: str = Field(min_length=2, max_length=60, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    business_type: str | None = None
    phone: str | None = None
    address: str | None = None
    logo_url: str | None = None
    theme: str = "minimal_luxe"


@app.post("/api/stores", status_code=201)
def create_store(
    data: StoreCreateRequest,
    user: dict = Depends(current_user),
):
    if user["role"] != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")

    with get_db() as connection:
        existing = connection.execute(
            "SELECT id FROM users WHERE id = ?",
            (user["id"],),
        ).fetchone()

        if existing is None:
            raise HTTPException(status_code=401, detail="User not found")

        if connection.execute(
            "SELECT id FROM stores WHERE slug = ?",
            (data.slug,),
        ).fetchone():
            raise HTTPException(status_code=409, detail="Store slug already exists")

        cursor = connection.execute(
            """
            INSERT INTO stores (
                store_name, slug, owner_email, logo_url,
                business_type, phone, address, theme, published
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                data.store_name.strip(),
                data.slug,
                user["email"],
                data.logo_url,
                data.business_type,
                data.phone,
                data.address,
                data.theme,
            ),
        )
        store_id = cursor.lastrowid

        connection.execute(
            "UPDATE users SET store_id = ? WHERE id = ?",
            (store_id, user["id"]),
        )

    return {
        "id": store_id,
        "store_name": data.store_name.strip(),
        "slug": data.slug,
        "owner_email": user["email"],
        "published": False,
        "message": "Store created successfully",
    }


@app.get("/api/stores/{slug}")
def get_public_store(slug: str):
    with get_db() as connection:
        store = connection.execute(
            """
            SELECT id, store_name, slug, logo_url, business_type,
                   phone, address, theme
            FROM stores
            WHERE slug = ? AND published = 1
            """,
            (slug,),
        ).fetchone()

    if store is None:
        raise HTTPException(status_code=404, detail="Published store not found")

    return dict(store)


@app.get("/api/stores/{slug}/products")
def get_public_products(slug: str, q: str | None = None, category: str | None = None):
    with get_db() as connection:
        store = connection.execute(
            "SELECT id FROM stores WHERE slug = ? AND published = 1",
            (slug,),
        ).fetchone()

        if store is None:
            raise HTTPException(status_code=404, detail="Published store not found")

        sql = """
            SELECT id, sku, name, description, price, original_price,
                   category, image_url, stock
            FROM products
            WHERE store_id = ? AND status = 'published'
        """
        params = [store["id"]]

        if q:
            sql += " AND (name LIKE ? OR description LIKE ?)"
            params.extend([f"%{q}%", f"%{q}%"])

        if category:
            sql += " AND category = ?"
            params.append(category)

        sql += " ORDER BY id DESC"

        products = connection.execute(sql, params).fetchall()

    return [dict(product) for product in products]

@app.post("/api/stores/{slug}/publish")
def publish_store(
    slug: str,
    user: dict = Depends(current_user),
):
    with get_db() as connection:
        store = connection.execute(
            """
            SELECT id FROM stores
            WHERE slug = ? AND owner_email = ?
            """,
            (slug, user["email"]),
        ).fetchone()

        if store is None:
            raise HTTPException(
                status_code=404,
                detail="Store not found for this owner",
            )

        connection.execute(
            "UPDATE stores SET published = 1 WHERE id = ?",
            (store["id"],),
        )

    return {
        "message": "Store published successfully",
        "slug": slug,
        "published": True,
    }

# ---------- REQUEST MODELS ----------

class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    price: float = Field(ge=0)
    stock: int = Field(default=0, ge=0)
    category: str | None = None
    description: str | None = None
    image_url: str | None = None
    original_price: float | None = Field(default=None, ge=0)
    status: str = "published"


class CheckoutItem(BaseModel):
    product_id: int
    quantity: int = Field(gt=0, le=100)


class CheckoutRequest(BaseModel):
    customer_name: str = Field(min_length=1, max_length=120)
    customer_email: str
    customer_phone: str | None = None
    delivery_address: str = Field(min_length=5, max_length=500)
    items: list[CheckoutItem] = Field(min_length=1, max_length=50)


class StatusUpdate(BaseModel):
    status: str


# ---------- OWNER STORE HELPERS ----------

def require_owner_store(user):
    if user["role"] != "owner" or not user.get("store_id"):
        raise HTTPException(
            status_code=403,
            detail="An owner account with a store is required",
        )
    return user["store_id"]


# ---------- CATEGORY MANAGEMENT ----------

@app.get("/api/admin/categories")
def list_categories(user: dict = Depends(current_user)):
    store_id = require_owner_store(user)
    with get_db() as db:
        rows = db.execute(
            """
            SELECT id, name, is_custom, sort_order
            FROM categories
            WHERE store_id = ?
            ORDER BY sort_order, name
            """,
            (store_id,),
        ).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/admin/categories", status_code=201)
def create_category(
    data: CategoryCreate,
    user: dict = Depends(current_user),
):
    store_id = require_owner_store(user)
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Category name is required")

    try:
        with get_db() as db:
            cursor = db.execute(
                """
                INSERT INTO categories (store_id, name)
                VALUES (?, ?)
                """,
                (store_id, name),
            )
            category_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Category already exists")

    return {"id": category_id, "name": name}


# ---------- PRODUCT MANAGEMENT ----------

@app.get("/api/admin/products")
def list_admin_products(user: dict = Depends(current_user)):
    store_id = require_owner_store(user)
    with get_db() as db:
        rows = db.execute(
            """
            SELECT id, sku, name, description, price, original_price,
                   category, image_url, stock, low_stock_threshold, status
            FROM products
            WHERE store_id = ?
            ORDER BY id DESC
            """,
            (store_id,),
        ).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/admin/products", status_code=201)
def create_product(
    data: ProductCreate,
    user: dict = Depends(current_user),
):
    store_id = require_owner_store(user)

    if data.status not in ("published", "draft"):
        raise HTTPException(status_code=422, detail="Invalid product status")

    with get_db() as db:
        category = data.category.strip() if data.category else None

        if category:
            found = db.execute(
                """
                SELECT id FROM categories
                WHERE store_id = ? AND name = ?
                """,
                (store_id, category),
            ).fetchone()
            if not found:
                raise HTTPException(
                    status_code=422,
                    detail="Create this category for your store first",
                )

        cursor = db.execute(
            """
            INSERT INTO products (
                store_id, name, description, price, original_price,
                category, image_url, stock, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                store_id,
                data.name.strip(),
                data.description,
                data.price,
                data.original_price,
                category,
                data.image_url,
                data.stock,
                data.status,
            ),
        )
        product_id = cursor.lastrowid

        row = db.execute(
            """
            SELECT id, name, price, stock, category, status
            FROM products WHERE id = ? AND store_id = ?
            """,
            (product_id, store_id),
        ).fetchone()

    return dict(row)


@app.patch("/api/admin/products/{product_id}")
def update_product(
    product_id: int,
    data: ProductCreate,
    user: dict = Depends(current_user),
):
    store_id = require_owner_store(user)

    if data.status not in ("published", "draft"):
        raise HTTPException(status_code=422, detail="Invalid product status")

    with get_db() as db:
        result = db.execute(
            """
            UPDATE products
            SET name = ?, description = ?, price = ?, original_price = ?,
                category = ?, image_url = ?, stock = ?, status = ?
            WHERE id = ? AND store_id = ?
            """,
            (
                data.name.strip(),
                data.description,
                data.price,
                data.original_price,
                data.category,
                data.image_url,
                data.stock,
                data.status,
                product_id,
                store_id,
            ),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Product not found")

    return {"message": "Product updated", "id": product_id}


@app.delete("/api/admin/products/{product_id}")
def delete_product(
    product_id: int,
    user: dict = Depends(current_user),
):
    store_id = require_owner_store(user)
    with get_db() as db:
        result = db.execute(
            "DELETE FROM products WHERE id = ? AND store_id = ?",
            (product_id, store_id),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Product not found")
    return {"message": "Product deleted"}


# ---------- CHECKOUT / INVENTORY ----------

@app.post("/api/stores/{slug}/checkout", status_code=201)
def checkout(slug: str, data: CheckoutRequest):
    receipt = secrets.token_hex(6).upper()

    try:
        with get_db() as db:
            store = db.execute(
                "SELECT id FROM stores WHERE slug = ? AND published = 1",
                (slug,),
            ).fetchone()

            if not store:
                raise HTTPException(status_code=404, detail="Store not found")

            store_id = store["id"]
            order_items = []
            subtotal = 0.0

            # Reject duplicate product IDs to keep stock calculations clear.
            ids = [item.product_id for item in data.items]
            if len(ids) != len(set(ids)):
                raise HTTPException(
                    status_code=422,
                    detail="Each product should appear only once",
                )

            for item in data.items:
                product = db.execute(
                    """
                    SELECT id, name, price, stock, status
                    FROM products
                    WHERE id = ? AND store_id = ?
                    """,
                    (item.product_id, store_id),
                ).fetchone()

                if not product or product["status"] != "published":
                    raise HTTPException(
                        status_code=400,
                        detail=f"Product {item.product_id} is unavailable",
                    )

                if product["stock"] < item.quantity:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Insufficient stock for {product['name']}",
                    )

                line_total = round(product["price"] * item.quantity, 2)
                subtotal += line_total
                order_items.append({
                    "productId": product["id"],
                    "name": product["name"],
                    "unitPrice": product["price"],
                    "quantity": item.quantity,
                    "lineTotal": line_total,
                })

            # Deduct inventory only after all items have passed validation.
            for item in data.items:
                result = db.execute(
                    """
                    UPDATE products SET stock = stock - ?
                    WHERE id = ? AND store_id = ? AND stock >= ?
                    """,
                    (
                        item.quantity,
                        item.product_id,
                        store_id,
                        item.quantity,
                    ),
                )
                if result.rowcount != 1:
                    raise HTTPException(
                        status_code=409,
                        detail="Stock changed; please retry checkout",
                    )

            subtotal = round(subtotal, 2)
            history = [{
                "status": "Placed",
                "at": datetime.now(timezone.utc).isoformat(),
                "note": "Order created",
            }]

            cursor = db.execute(
                """
                INSERT INTO orders (
                    store_id, receipt_code, customer_name, customer_email,
                    customer_phone, delivery_address, items_json, item_count,
                    subtotal, total, status, status_history_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Placed', ?)
                """,
                (
                    store_id,
                    receipt,
                    data.customer_name.strip(),
                    data.customer_email.strip().lower(),
                    data.customer_phone,
                    data.delivery_address.strip(),
                    json.dumps(order_items),
                    sum(item.quantity for item in data.items),
                    subtotal,
                    subtotal,
                    json.dumps(history),
                ),
            )
            order_id = cursor.lastrowid

    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Could not create order")

    return {
        "order_id": order_id,
        "receipt_code": receipt,
        "status": "Placed",
        "total": subtotal,
        "message": "Test order created; no payment was processed",
    }


# ---------- ORDER MANAGEMENT ----------

@app.get("/api/admin/orders")
def list_orders(user: dict = Depends(current_user)):
    store_id = require_owner_store(user)
    with get_db() as db:
        rows = db.execute(
            """
            SELECT id, receipt_code, customer_name, customer_email,
                   items_json, item_count, subtotal, total, status,
                   payment_status, created_at
            FROM orders
            WHERE store_id = ?
            ORDER BY id DESC
            """,
            (store_id,),
        ).fetchall()

    result = []
    for row in rows:
        order = dict(row)
        order["items"] = json.loads(order.pop("items_json"))
        result.append(order)
    return result


@app.patch("/api/admin/orders/{order_id}/status")
def update_order_status(
    order_id: int,
    data: StatusUpdate,
    user: dict = Depends(current_user),
):
    store_id = require_owner_store(user)
    allowed = {"Placed", "Packed", "Shipped", "Delivered", "Cancelled"}

    if data.status not in allowed:
        raise HTTPException(status_code=422, detail="Invalid order status")

    with get_db() as db:
        order = db.execute(
            """
            SELECT status, status_history_json
            FROM orders WHERE id = ? AND store_id = ?
            """,
            (order_id, store_id),
        ).fetchone()

        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        if order["status"] == "Cancelled" or order["status"] == "Delivered":
            raise HTTPException(
                status_code=409,
                detail="This order is already in a final state",
            )

        if data.status == "Cancelled":
            items = json.loads(
                db.execute(
                    "SELECT items_json FROM orders WHERE id = ? AND store_id = ?",
                    (order_id, store_id),
                ).fetchone()["items_json"]
            )
            for item in items:
                db.execute(
                    """
                    UPDATE products SET stock = stock + ?
                    WHERE id = ? AND store_id = ?
                    """,
                    (item["quantity"], item["productId"], store_id),
                )

        history = json.loads(order["status_history_json"] or "[]")
        history.append({
            "status": data.status,
            "at": datetime.now(timezone.utc).isoformat(),
            "note": "Status updated by store owner",
        })

        db.execute(
            """
            UPDATE orders SET status = ?, status_history_json = ?
            WHERE id = ? AND store_id = ?
            """,
            (data.status, json.dumps(history), order_id, store_id),
        )

    return {"order_id": order_id, "status": data.status}


# ---------- DASHBOARD ANALYTICS ----------

@app.get("/api/admin/analytics")
def get_analytics(user: dict = Depends(current_user)):
    store_id = require_owner_store(user)
    with get_db() as db:
        totals = db.execute(
            """
            SELECT COUNT(*) AS order_count,
                   COALESCE(SUM(
                       CASE WHEN status != 'Cancelled' THEN total ELSE 0 END
                   ), 0) AS revenue
            FROM orders
            WHERE store_id = ?
            """,
            (store_id,),
        ).fetchone()

        low_stock = db.execute(
            """
            SELECT id, name, stock, low_stock_threshold
            FROM products
            WHERE store_id = ? AND stock <= low_stock_threshold
            ORDER BY stock ASC
            """,
            (store_id,),
        ).fetchall()

        recent = db.execute(
            """
            SELECT id, receipt_code, customer_name, total, status, created_at
            FROM orders WHERE store_id = ?
            ORDER BY id DESC LIMIT 10
            """,
            (store_id,),
        ).fetchall()

    return {
        "order_count": totals["order_count"],
        "revenue": round(totals["revenue"], 2),
        "low_stock_products": [dict(row) for row in low_stock],
        "recent_orders": [dict(row) for row in recent],
    }
