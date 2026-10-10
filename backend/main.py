from __future__ import annotations

import sqlite3
import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, field_validator

if __package__:
    from . import auth
    from .catalog import router as catalog_router
    from .orders import router as orders_router
    from .database import PREDEFINED_CATEGORIES, get_connection, initialize_database
else:
    import auth
    from catalog import router as catalog_router
    from orders import router as orders_router
    from database import PREDEFINED_CATEGORIES, get_connection, initialize_database


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Initialization happens only when the service starts, never on module import.
    initialize_database()
    yield


app = FastAPI(title="Hackathon Backend", version="1.0.0", lifespan=lifespan)

# Allow requests from the Next.js frontend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(catalog_router)
app.include_router(orders_router)


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    password: str = Field(min_length=auth.PASSWORD_MINIMUM_LENGTH, max_length=auth.PASSWORD_MAXIMUM_LENGTH)
    store_name: str = Field(min_length=1, max_length=120)
    store_slug: str = Field(min_length=1, max_length=80)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return auth.normalize_email(value)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return auth.validate_password(value)

    @field_validator("store_name")
    @classmethod
    def normalize_store_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Store name must not be empty")
        return value

    @field_validator("store_slug")
    @classmethod
    def normalize_store_slug(cls, value: str) -> str:
        return auth.validate_store_slug(value)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    password: str = Field(min_length=1, max_length=auth.PASSWORD_MAXIMUM_LENGTH)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return auth.normalize_email(value)


class StoreUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    logo_url: str | None = Field(default=None, max_length=2048)
    is_published: bool | None = None


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


@app.post("/api/auth/register", status_code=status.HTTP_201_CREATED)
def register_owner(request: RegisterRequest):
    # Validate before the transaction so missing/weak JWT configuration cannot
    # create an account that the caller cannot authenticate into.
    try:
        auth.validate_jwt_configuration()
    except auth.AuthConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=auth.AUTH_CONFIGURATION_DETAIL,
        ) from error

    password_hash = auth.hash_password(request.password)
    try:
        with get_connection() as connection:
            existing = connection.execute(
                "SELECT 1 FROM users WHERE email = ?", (request.email,)
            ).fetchone()
            if existing:
                raise HTTPException(status_code=409, detail="Email or store slug already exists")
            existing = connection.execute(
                "SELECT 1 FROM stores WHERE slug = ?", (request.store_slug,)
            ).fetchone()
            if existing:
                raise HTTPException(status_code=409, detail="Email or store slug already exists")

            cursor = connection.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (request.email, password_hash),
            )
            user_id = cursor.lastrowid
            if user_id is None:
                raise RuntimeError("User registration did not return an ID")

            token = auth.create_access_token(user_id)
            connection.execute(
                """
                INSERT INTO stores (slug, name, description, owner_user_id, is_published)
                VALUES (?, ?, '', ?, 0)
                """,
                (request.store_slug, request.store_name, user_id),
            )
            new_store = connection.execute(
                "SELECT id FROM stores WHERE slug = ? AND owner_user_id = ?",
                (request.store_slug, user_id),
            ).fetchone()
            for category in PREDEFINED_CATEGORIES:
                connection.execute(
                    "INSERT OR IGNORE INTO categories (store_id, name, is_predefined) VALUES (?, ?, 1)",
                    (new_store["id"], category),
                )
            connection.execute(
                "INSERT OR IGNORE INTO store_customizations (store_id) VALUES (?)",
                (new_store["id"],),
            )
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="Email or store slug already exists") from error

    return {
        "access_token": token,
        "token_type": "bearer",
        "store": {
            "slug": request.store_slug,
            "name": request.store_name,
            "is_published": False,
        },
    }


@app.post("/api/auth/login")
def login_owner(request: LoginRequest):
    try:
        auth.validate_jwt_configuration()
    except auth.AuthConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=auth.AUTH_CONFIGURATION_DETAIL,
        ) from error

    with get_connection() as connection:
        user = connection.execute(
            "SELECT id, email, password_hash FROM users WHERE email = ?",
            (request.email,),
        ).fetchone()

    if user is None:
        # Spend comparable Argon2 work for unknown emails without retaining input.
        auth.password_hasher.hash(request.password)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not auth.verify_password(request.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    return {
        "access_token": auth.create_access_token(user["id"]),
        "token_type": "bearer",
    }


@app.get("/api/stores/{slug}")
def get_store(slug: str):
    with get_connection() as connection:
        store = connection.execute(
            """
            SELECT slug, name, description, logo_url
            FROM stores
            WHERE slug = ? AND is_published = 1
            """,
            (slug,),
        ).fetchone()
        customization = None
        if store is not None:
            customization = connection.execute(
                """SELECT theme_id, primary_color, accent_color, background_color, font_family,
                          banner_url, homepage_sections_json, footer_text, contact_email, contact_phone,
                          shipping_policy, returns_policy
                   FROM store_customizations
                   WHERE store_id = (SELECT id FROM stores WHERE slug = ?)""",
                (slug,),
            ).fetchone()

    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")
    result = dict(store)
    if customization is not None:
        result["customization"] = dict(customization)
        result["customization"]["homepage_sections"] = json.loads(
            result["customization"].pop("homepage_sections_json")
        )
    return result


@app.get("/api/stores/{slug}/products")
def get_store_products(slug: str):
    with get_connection() as connection:
        store = connection.execute(
            "SELECT id FROM stores WHERE slug = ? AND is_published = 1", (slug,)
        ).fetchone()
        if store is None:
            raise HTTPException(status_code=404, detail="Store not found")

        products = connection.execute(
            """
            SELECT id, name, category, price, original_price, discount_percent, stock,
                   image_url, images_json, variants_json, description
            FROM products
            WHERE store_id = ?
            ORDER BY id
            """,
            (store["id"],),
        ).fetchall()

    results = []
    for product in products:
        item = dict(product)
        item["images"] = json.loads(item.pop("images_json") or "[]")
        item["variants"] = json.loads(item.pop("variants_json") or "[]")
        results.append(item)
    return results


@app.get("/api/owner/stores")
def list_owned_stores(current_user: dict[str, Any] = Depends(auth.get_current_user)):
    with get_connection() as connection:
        stores = connection.execute(
            """
            SELECT slug, name, description, logo_url, is_published
            FROM stores
            WHERE owner_user_id = ?
            ORDER BY id
            """,
            (current_user["id"],),
        ).fetchall()
    return [
        {**dict(store), "is_published": bool(store["is_published"])}
        for store in stores
    ]


@app.get("/api/owner/stores/{slug}")
def get_owned_store(
    store: dict[str, Any] = Depends(auth.require_store_owner),
):
    return store


@app.patch("/api/owner/stores/{slug}")
def update_owned_store(
    request: StoreUpdateRequest,
    store: dict[str, Any] = Depends(auth.require_store_owner),
    current_user: dict[str, Any] = Depends(auth.get_current_user),
):
    changes = request.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="At least one store field is required")
    for field in ("name", "description", "is_published"):
        if field in changes and changes[field] is None:
            raise HTTPException(status_code=422, detail=f"{field} cannot be null")

    # Column names come only from this fixed allowlist; values remain parameterized.
    assignments = ", ".join(f"{field} = ?" for field in changes)
    values = list(changes.values()) + [store["id"], current_user["id"]]
    with get_connection() as connection:
        cursor = connection.execute(
            f"UPDATE stores SET {assignments} "
            "WHERE id = ? AND owner_user_id = ?",
            values,
        )
        if cursor.rowcount != 1:
            raise HTTPException(status_code=404, detail="Store not found")
        updated = connection.execute(
            """
            SELECT id, slug, name, description, logo_url, is_published
            FROM stores
            WHERE id = ? AND owner_user_id = ?
            """,
            (store["id"], current_user["id"]),
        ).fetchone()

    if updated is None:
        raise HTTPException(status_code=404, detail="Store not found")
    result = dict(updated)
    result["is_published"] = bool(result["is_published"])
    return result
