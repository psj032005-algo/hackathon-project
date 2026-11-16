from __future__ import annotations

import sqlite3
import json
import os
import re
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_PHONE_PATTERN = re.compile(r"^[+0-9() .-]{5,40}$")


def _validate_optional_phone(value: str) -> str:
    value = value.strip()
    if value and not _PHONE_PATTERN.fullmatch(value):
        raise ValueError("Phone number contains unsupported characters or is too short")
    return value


def _validate_optional_http_url(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    value = value.strip()
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Logo URL must be an absolute HTTP or HTTPS URL")
    return value

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


def get_cors_allowed_origins() -> list[str]:
    """Read explicit browser origins, defaulting to the local frontend."""
    configured_origins = os.environ.get("CORS_ALLOWED_ORIGINS", "")
    origins = [origin.strip() for origin in configured_origins.split(",") if origin.strip()]
    if not origins:
        return ["http://localhost:3000"]
    if "*" in origins:
        raise ValueError("CORS_ALLOWED_ORIGINS cannot contain '*' when credentials are enabled")
    return origins


# Allow requests from the Next.js frontend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_allowed_origins(),
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
    business_type: str = Field(default="Other", min_length=1, max_length=60)
    address_line1: str = Field(default="", max_length=200)
    address_line2: str = Field(default="", max_length=200)
    city: str = Field(default="", max_length=120)
    region: str = Field(default="", max_length=120)
    postal_code: str = Field(default="", max_length=32)
    country: str = Field(default="", max_length=120)
    contact_email: str = Field(default="", max_length=254)
    contact_phone: str = Field(default="", max_length=40)

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

    @field_validator("business_type", "address_line1", "address_line2", "city", "region", "postal_code", "country", "contact_phone")
    @classmethod
    def trim_profile_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("contact_email")
    @classmethod
    def normalize_contact_email(cls, value: str) -> str:
        return auth.normalize_email(value) if value.strip() else ""

    @field_validator("contact_phone")
    @classmethod
    def validate_contact_phone(cls, value: str) -> str:
        return _validate_optional_phone(value)

    @model_validator(mode="after")
    def validate_store_profile(self) -> RegisterRequest:
        profile_fields = {"business_type", "address_line1", "address_line2", "city", "region", "postal_code", "country", "contact_email", "contact_phone"}
        if profile_fields & self.model_fields_set:
            required = ("business_type", "address_line1", "city", "region", "postal_code", "country")
            if any(not getattr(self, field).strip() for field in required):
                raise ValueError("Business type, street address, city, region, postal code, and country are required")
        return self


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
    business_type: str | None = Field(default=None, min_length=1, max_length=60)
    address_line1: str | None = Field(default=None, max_length=200)
    address_line2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, max_length=32)
    country: str | None = Field(default=None, max_length=120)
    contact_email: str | None = Field(default=None, max_length=254)
    contact_phone: str | None = Field(default=None, max_length=40)

    @field_validator("logo_url")
    @classmethod
    def validate_logo_url(cls, value: str | None) -> str | None:
        return _validate_optional_http_url(value)

    @field_validator("business_type", "address_line1", "address_line2", "city", "region", "postal_code", "country", "contact_phone")
    @classmethod
    def trim_profile_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("contact_email")
    @classmethod
    def normalize_contact_email(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return ""
        return auth.normalize_email(value)

    @field_validator("contact_phone")
    @classmethod
    def validate_contact_phone(cls, value: str | None) -> str | None:
        return _validate_optional_phone(value) if value is not None else None

    @model_validator(mode="after")
    def validate_business_type(self) -> StoreUpdateRequest:
        if self.business_type is not None and not self.business_type.strip():
            raise ValueError("Business type must not be empty")
        return self


class StaffInviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str

    @field_validator("email")
    @classmethod
    def normalize_staff_email(cls, value: str) -> str:
        return auth.normalize_email(value)


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
                INSERT INTO stores (slug, name, description, owner_user_id, is_published,
                    business_type, address_line1, address_line2, city, region, postal_code,
                    country, contact_email, contact_phone)
                VALUES (?, ?, '', ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (request.store_slug, request.store_name, user_id, request.business_type,
                 request.address_line1, request.address_line2, request.city, request.region,
                 request.postal_code, request.country, request.contact_email, request.contact_phone),
            )
            new_store = connection.execute(
                "SELECT id FROM stores WHERE slug = ? AND owner_user_id = ?",
                (request.store_slug, user_id),
            ).fetchone()
            connection.execute(
                "INSERT INTO store_memberships (store_id, user_id, role) VALUES (?, ?, 'owner')",
                (new_store["id"], user_id),
            )
            connection.execute(
                "INSERT INTO store_onboarding (store_id, product_setup_method, is_complete) VALUES (?, NULL, 0)",
                (new_store["id"],),
            )
            for category in PREDEFINED_CATEGORIES:
                connection.execute(
                    "INSERT OR IGNORE INTO categories (store_id, name, is_predefined) VALUES (?, ?, 1)",
                    (new_store["id"], category),
                )
            connection.execute(
                "INSERT OR IGNORE INTO store_customizations (store_id) VALUES (?)",
                (new_store["id"],),
            )
            connection.execute(
                "UPDATE store_customizations SET contact_email = ?, contact_phone = ? WHERE store_id = ?",
                (request.contact_email, request.contact_phone, new_store["id"]),
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
            FROM products AS p
            WHERE p.store_id = ? AND EXISTS (
                SELECT 1 FROM store_category_selections AS selected
                JOIN categories AS c ON c.id = selected.category_id
                WHERE selected.store_id = p.store_id AND c.name = p.category COLLATE NOCASE
            )
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
            SELECT s.slug, s.name, s.description, s.logo_url, s.is_published, s.business_type,
                   s.address_line1, s.address_line2, s.city, s.region, s.postal_code, s.country,
                   s.contact_email, s.contact_phone, m.role
            FROM stores AS s JOIN store_memberships AS m ON m.store_id = s.id
            WHERE m.user_id = ?
            ORDER BY s.id
            """,
            (current_user["id"],),
        ).fetchall()
    return [
        {**dict(store), "is_published": bool(store["is_published"])}
        for store in stores
    ]


@app.get("/api/owner/stores/{slug}")
def get_owned_store(
    store: dict[str, Any] = Depends(auth.require_store_member),
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
    for field, value in changes.items():
        if value is None and field != "logo_url":
            raise HTTPException(status_code=422, detail=f"{field} cannot be null")

    # Column names come only from fixed request fields; values remain parameterized.
    profile_changes = {field: changes.pop(field) for field in ("contact_email", "contact_phone") if field in changes}
    with get_connection() as connection:
        if changes:
            assignments = ", ".join(f"{field} = ?" for field in changes)
            cursor = connection.execute(
                f"UPDATE stores SET {assignments} WHERE id = ? AND owner_user_id = ?",
                [*changes.values(), store["id"], current_user["id"]],
            )
        else:
            cursor = connection.execute(
                "SELECT 1 FROM stores WHERE id = ? AND owner_user_id = ?",
                (store["id"], current_user["id"]),
            )
        if changes and cursor.rowcount != 1:
            raise HTTPException(status_code=404, detail="Store not found")
        if not changes and cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="Store not found")
        if profile_changes:
            assignments = ", ".join(f"{field} = ?" for field in profile_changes)
            connection.execute(
                f"UPDATE stores SET {assignments} WHERE id = ? AND owner_user_id = ?",
                [*profile_changes.values(), store["id"], current_user["id"]],
            )
            connection.execute(
                f"UPDATE store_customizations SET {assignments} WHERE store_id = ?",
                [*profile_changes.values(), store["id"]],
            )
        updated = connection.execute(
            """
            SELECT id, slug, name, description, logo_url, is_published, business_type,
                   address_line1, address_line2, city, region, postal_code, country,
                   contact_email, contact_phone
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


@app.get("/api/stores/{slug}/categories")
def get_store_categories(slug: str):
    with get_connection() as connection:
        store = connection.execute(
            "SELECT id FROM stores WHERE slug = ? AND is_published = 1", (slug,)
        ).fetchone()
        if store is None:
            raise HTTPException(status_code=404, detail="Store not found")
        rows = connection.execute(
            """SELECT c.name FROM store_category_selections AS selected
               JOIN categories AS c ON c.id = selected.category_id
               WHERE selected.store_id = ? ORDER BY c.name COLLATE NOCASE""",
            (store["id"],),
        ).fetchall()
    return [row["name"] for row in rows]


@app.get("/api/owner/stores/{slug}/staff")
def list_store_staff(store: dict[str, Any] = Depends(auth.require_store_owner)):
    with get_connection() as connection:
        rows = connection.execute(
            """SELECT u.id, u.email, m.role, m.created_at FROM store_memberships AS m
               JOIN users AS u ON u.id = m.user_id
               WHERE m.store_id = ? AND m.role = 'staff' ORDER BY u.email""",
            (store["id"],),
        ).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/owner/stores/{slug}/staff", status_code=status.HTTP_201_CREATED)
def add_store_staff(request: StaffInviteRequest, store: dict[str, Any] = Depends(auth.require_store_owner)):
    with get_connection() as connection:
        user = connection.execute("SELECT id FROM users WHERE email = ?", (request.email,)).fetchone()
        if user is None:
            raise HTTPException(status_code=404, detail="Create an owner account for this email before adding staff")
        try:
            connection.execute(
                "INSERT INTO store_memberships (store_id, user_id, role) VALUES (?, ?, 'staff')",
                (store["id"], user["id"]),
            )
        except sqlite3.IntegrityError as error:
            raise HTTPException(status_code=409, detail="This user already has a role in the store") from error
    return {"user_id": user["id"], "email": request.email, "role": "staff"}


@app.delete("/api/owner/stores/{slug}/staff/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_store_staff(user_id: int, store: dict[str, Any] = Depends(auth.require_store_owner)):
    with get_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM store_memberships WHERE store_id = ? AND user_id = ? AND role = 'staff'",
            (store["id"], user_id),
        )
        if cursor.rowcount != 1:
            raise HTTPException(status_code=404, detail="Staff member not found")
    return None
