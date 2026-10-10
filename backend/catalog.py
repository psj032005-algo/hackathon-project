"""Tenant-scoped product, category, import, and storefront customization APIs."""

from __future__ import annotations

import csv
import base64
import binascii
import io
import json
import re
import sqlite3
import zipfile
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from openpyxl import Workbook, load_workbook
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

if __package__:
    from . import auth
    from .database import get_connection
else:
    import auth
    from database import get_connection


router = APIRouter()
MAX_CSV_BYTES = 1_000_000
MAX_CSV_ROWS = 1000
MAX_XLSX_BYTES = 1_000_000
MAX_XLSX_EXPANDED_BYTES = 10_000_000
MAX_XLSX_COLUMNS = 40
CSV_FIELDS = {
    "name", "description", "category", "price", "original_price", "stock",
    "sku", "image_url", "discount_percent",
}
SECTIONS = {"hero", "featured", "categories", "newsletter"}
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _check_category(connection: sqlite3.Connection, store_id: int, name: str) -> str:
    category = name.strip()
    if not category or len(category) > 50:
        raise HTTPException(status_code=422, detail="Category must be between 1 and 50 characters")
    exists = connection.execute(
        "SELECT 1 FROM categories WHERE store_id = ? AND name = ? COLLATE NOCASE",
        (store_id, category),
    ).fetchone()
    if not exists:
        raise HTTPException(status_code=422, detail="Choose a category belonging to this store")
    return category


def _product(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["images"] = json.loads(result.pop("images_json") or "[]")
    result["variants"] = json.loads(result.pop("variants_json") or "[]")
    return result


class ProductVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=50)
    value: str = Field(min_length=1, max_length=100)
    price_adjustment: float = Field(default=0, allow_inf_nan=False, ge=-1_000_000, le=1_000_000)
    stock: int = Field(default=0, ge=0, le=1_000_000)


class ProductWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    category: str = Field(min_length=1, max_length=50)
    price: float = Field(gt=0, le=100_000_000, allow_inf_nan=False)
    original_price: float | None = Field(default=None, gt=0, le=100_000_000, allow_inf_nan=False)
    discount_percent: float | None = Field(default=None, ge=0, le=90, allow_inf_nan=False)
    stock: int = Field(default=0, ge=0, le=1_000_000)
    sku: str | None = Field(default=None, max_length=80)
    images: list[str] = Field(default_factory=list, max_length=10)
    variants: list[ProductVariant] = Field(default_factory=list, max_length=50)

    @field_validator("name", "category", mode="before")
    @classmethod
    def trim_required_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("sku")
    @classmethod
    def normalize_sku(cls, value: str | None) -> str | None:
        normalized = value.strip().upper() if value else None
        return normalized or None

    @field_validator("images")
    @classmethod
    def validate_images(cls, values: list[str]) -> list[str]:
        for value in values:
            parsed = urlparse(value)
            if len(value) > 2048 or parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("Images must use publicly accessible HTTP or HTTPS URLs")
        return values

    @model_validator(mode="after")
    def validate_compare_price(self) -> ProductWrite:
        if self.original_price is not None and self.original_price <= self.price:
            raise ValueError("Original price must be greater than the current price")
        return self


class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=50)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        return value.strip()


class StoreSetupUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    categories: list[str] = Field(max_length=20)
    product_setup_method: Literal["demo", "spreadsheet"] | None = None

    @field_validator("categories")
    @classmethod
    def normalize_selected_categories(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            category = value.strip()
            if not category or len(category) > 50:
                raise ValueError("Choose valid categories")
            key = category.casefold()
            if key not in seen:
                normalized.append(category)
                seen.add(key)
        return normalized


class SampleImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    categories: list[str] = Field(min_length=1, max_length=20)

    @field_validator("categories")
    @classmethod
    def normalize_categories(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(value.strip() for value in values))
        if any(not value or len(value) > 50 for value in normalized):
            raise ValueError("Choose valid categories")
        return normalized


class BulkChanges(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price: float | None = Field(default=None, gt=0, le=100_000_000, allow_inf_nan=False)
    stock: int | None = Field(default=None, ge=0, le=1_000_000)
    category: str | None = Field(default=None, min_length=1, max_length=50)
    discount_percent: float | None = Field(default=None, ge=0, le=90, allow_inf_nan=False)

    @model_validator(mode="after")
    def require_update(self) -> BulkChanges:
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update")
        return self


class BulkProductUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_ids: list[int] = Field(min_length=1, max_length=100)
    changes: BulkChanges


class CSVImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Permit multibyte text to reach the byte-limit check below while still
    # bounding the JSON field before it is decoded and parsed.
    csv_text: str = Field(min_length=1, max_length=MAX_CSV_BYTES * 2)
    mapping: dict[str, str]
    confirmed: bool = False


class XLSXImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    xlsx_base64: str = Field(min_length=1, max_length=1_400_000)
    mapping: dict[str, str]
    confirmed: bool = False


class ThemeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme_id: Literal["market", "botanical", "studio", "midnight"] | None = None
    primary_color: str | None = None
    accent_color: str | None = None
    background_color: str | None = None
    font_family: Literal["sans", "serif", "mono"] | None = None
    banner_url: str | None = Field(default=None, max_length=2048)
    homepage_sections: list[str] | None = Field(default=None, min_length=1, max_length=4)
    footer_text: str | None = Field(default=None, max_length=1000)
    contact_email: str | None = Field(default=None, max_length=254)
    contact_phone: str | None = Field(default=None, max_length=40)
    shipping_policy: str | None = Field(default=None, max_length=2000)
    returns_policy: str | None = Field(default=None, max_length=2000)

    @field_validator("primary_color", "accent_color", "background_color")
    @classmethod
    def validate_color(cls, value: str | None) -> str | None:
        if value is not None and not COLOR_RE.fullmatch(value):
            raise ValueError("Colors must be six-digit hexadecimal values such as #243c30")
        return value.lower() if value else value

    @field_validator("banner_url")
    @classmethod
    def validate_banner(cls, value: str | None) -> str | None:
        if value:
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("Banner must use a publicly accessible HTTP or HTTPS URL")
        return value

    @field_validator("homepage_sections")
    @classmethod
    def validate_sections(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and (len(value) != len(set(value)) or set(value) - SECTIONS):
            raise ValueError("Homepage sections contain an unsupported or repeated section")
        return value

    @field_validator("contact_email")
    @classmethod
    def validate_contact_email(cls, value: str | None) -> str | None:
        if value and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid contact email address")
        return value

    @field_validator("contact_phone")
    @classmethod
    def validate_contact_phone(cls, value: str | None) -> str | None:
        if value and not re.fullmatch(r"[+0-9() .-]{5,40}", value):
            raise ValueError("Enter a valid contact phone number")
        return value

    @model_validator(mode="after")
    def require_update(self) -> ThemeUpdate:
        if not self.model_fields_set:
            raise ValueError("Provide at least one customization field")
        return self


def _theme_settings(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {
            "theme_id": "market", "primary_color": "#243c30", "accent_color": "#9b7753",
            "background_color": "#faf9f6", "font_family": "sans", "banner_url": None,
            "homepage_sections": ["hero", "featured", "categories"], "footer_text": "",
            "contact_email": "", "contact_phone": "", "shipping_policy": "", "returns_policy": "",
        }
    result = dict(row)
    # Store identity is derived from the authenticated route, never sent back
    # as a client-controlled customization field.
    result.pop("store_id", None)
    result["homepage_sections"] = json.loads(result.pop("homepage_sections_json"))
    return result


@router.get("/api/owner/stores/{slug}/categories")
def list_categories(
    store: dict[str, Any] = Depends(auth.require_store_member),
):
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT name, is_predefined FROM categories WHERE store_id = ? ORDER BY is_predefined DESC, name COLLATE NOCASE",
            (store["id"],),
        ).fetchall()
    return [{"name": row["name"], "is_predefined": bool(row["is_predefined"])} for row in rows]


@router.get("/api/owner/stores/{slug}/setup")
def get_store_setup(store: dict[str, Any] = Depends(auth.require_store_member)):
    with get_connection() as connection:
        selected = connection.execute(
            """SELECT c.name FROM store_category_selections AS s
               JOIN categories AS c ON c.id = s.category_id
               WHERE s.store_id = ? ORDER BY c.name COLLATE NOCASE""",
            (store["id"],),
        ).fetchall()
        setup = connection.execute(
            "SELECT product_setup_method, is_complete FROM store_onboarding WHERE store_id = ?",
            (store["id"],),
        ).fetchone()
    return {
        "categories": [row["name"] for row in selected],
        "product_setup_method": setup["product_setup_method"] if setup else None,
        "is_complete": bool(setup["is_complete"]) if setup else True,
    }


@router.put("/api/owner/stores/{slug}/setup")
def update_store_setup(
    request: StoreSetupUpdate,
    store: dict[str, Any] = Depends(auth.require_store_member),
):
    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        available: dict[str, tuple[int, str]] = {}
        for row in connection.execute(
            "SELECT id, name FROM categories WHERE store_id = ? ORDER BY id", (store["id"],)
        ).fetchall():
            available.setdefault(row["name"].casefold(), (row["id"], row["name"]))

        selected_by_id: dict[int, str] = {}
        for name in request.categories:
            category = available.get(name.casefold())
            if category is None:
                raise HTTPException(status_code=422, detail="Choose categories belonging to this store")
            # Keep the selection unique by database identity too. This protects
            # the composite primary key if names differ only by case or an older
            # client sends aliases that resolve to the same category row.
            selected_by_id.setdefault(category[0], category[1])

        connection.execute(
            "DELETE FROM store_category_selections WHERE store_id = ?", (store["id"],)
        )
        connection.executemany(
            "INSERT INTO store_category_selections (store_id, category_id) VALUES (?, ?)",
            [(store["id"], category_id) for category_id in selected_by_id],
        )
        connection.execute(
            """INSERT INTO store_onboarding (store_id, product_setup_method, is_complete)
               VALUES (?, ?, 0)
               ON CONFLICT(store_id) DO UPDATE SET
                   product_setup_method = COALESCE(excluded.product_setup_method, store_onboarding.product_setup_method),
                   is_complete = store_onboarding.is_complete""",
            (store["id"], request.product_setup_method),
        )
    return {
        "categories": list(selected_by_id.values()),
        "product_setup_method": request.product_setup_method,
        "is_complete": False,
    }


@router.post("/api/owner/stores/{slug}/setup/complete")
def complete_store_setup(store: dict[str, Any] = Depends(auth.require_store_member)):
    with get_connection() as connection:
        setup = connection.execute(
            "SELECT product_setup_method FROM store_onboarding WHERE store_id = ?",
            (store["id"],),
        ).fetchone()
        count = connection.execute(
            """SELECT COUNT(*) AS total FROM products AS p WHERE p.store_id = ? AND EXISTS (
                   SELECT 1 FROM store_category_selections AS selected
                   JOIN categories AS c ON c.id = selected.category_id
                   WHERE selected.store_id = p.store_id AND c.name = p.category COLLATE NOCASE
               )""",
            (store["id"],),
        ).fetchone()["total"]
        category_count = connection.execute(
            "SELECT COUNT(*) AS total FROM store_category_selections WHERE store_id = ?",
            (store["id"],),
        ).fetchone()["total"]
        if setup is None or setup["product_setup_method"] is None or category_count < 1 or count < 1:
            raise HTTPException(status_code=409, detail="Select a category and add a product in that category to finish store setup")
        connection.execute(
            "UPDATE store_onboarding SET is_complete = 1 WHERE store_id = ?", (store["id"],)
        )
    return {"is_complete": True}


@router.post("/api/owner/stores/{slug}/categories", status_code=status.HTTP_201_CREATED)
def create_category(
    request: CategoryCreate,
    store: dict[str, Any] = Depends(auth.require_store_member),
):
    if not request.name:
        raise HTTPException(status_code=422, detail="Category name must not be empty")
    try:
        with get_connection() as connection:
            duplicate = connection.execute(
                "SELECT 1 FROM categories WHERE store_id = ? AND name = ? COLLATE NOCASE",
                (store["id"], request.name),
            ).fetchone()
            if duplicate:
                raise HTTPException(status_code=409, detail="That category already exists")
            connection.execute(
                "INSERT INTO categories (store_id, name, is_predefined) VALUES (?, ?, 0)",
                (store["id"], request.name),
            )
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="That category already exists") from error
    return {"name": request.name, "is_predefined": False}


SAMPLE_PRODUCTS: dict[str, list[dict[str, Any]]] = {
    "Accessories": [
        {"name": "Canvas Weekend Tote", "description": "A sturdy cotton-canvas carryall with a roomy interior and reinforced handles.", "price": 1899, "stock": 16, "sku": "SAMPLE-ACC-001", "image": "https://images.unsplash.com/photo-1590874103328-eac38a683ce7?auto=format&fit=crop&w=900&q=85"},
        {"name": "Everyday Brass Hoops", "description": "Lightweight brushed-brass hoops made for everyday wear.", "price": 1299, "stock": 22, "sku": "SAMPLE-ACC-002", "image": "https://images.unsplash.com/photo-1535632066927-ab7c9ab60908?auto=format&fit=crop&w=900&q=85"},
    ],
    "Home": [
        {"name": "Speckled Stoneware Mug", "description": "A hand-finished stoneware mug with a comfortable curved handle.", "price": 899, "stock": 24, "sku": "SAMPLE-HOME-001", "image": "https://images.unsplash.com/photo-1514228742587-6b1558f89616?auto=format&fit=crop&w=900&q=85"},
        {"name": "Natural Linen Cushion Cover", "description": "A soft, breathable linen cover with a hidden zip closure.", "price": 1499, "stock": 12, "sku": "SAMPLE-HOME-002", "image": "https://images.unsplash.com/photo-1584100936595-c0654b55a2e2?auto=format&fit=crop&w=900&q=85"},
    ],
    "Wellness": [
        {"name": "Cedar & Sage Soy Candle", "description": "A small-batch soy candle with gentle cedarwood and sage notes.", "price": 1099, "stock": 14, "sku": "SAMPLE-WELL-001", "image": "https://images.unsplash.com/photo-1603006905003-be475563bc59?auto=format&fit=crop&w=900&q=85"},
        {"name": "Botanical Bath Salts", "description": "Mineral-rich bath salts blended with dried calendula and lavender.", "price": 749, "stock": 18, "sku": "SAMPLE-WELL-002", "image": "https://images.unsplash.com/photo-1608248543803-ba4f8c70ae0b?auto=format&fit=crop&w=900&q=85"},
    ],
    "Clothing": [
        {"name": "Relaxed Cotton Tee", "description": "A breathable midweight cotton tee with a relaxed everyday fit.", "price": 1599, "stock": 20, "sku": "SAMPLE-CLOTH-001", "image": "https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?auto=format&fit=crop&w=900&q=85"},
        {"name": "Linen Market Apron", "description": "A practical cross-back apron with two deep front pockets.", "price": 2199, "stock": 10, "sku": "SAMPLE-CLOTH-002", "image": "https://images.unsplash.com/photo-1543087903-1ac2ec7aa8c5?auto=format&fit=crop&w=900&q=85"},
    ],
    "Food": [
        {"name": "Small-Batch Wildflower Honey", "description": "Golden local honey gathered from seasonal wildflower blooms.", "price": 599, "stock": 30, "sku": "SAMPLE-FOOD-001", "image": "https://images.unsplash.com/photo-1587049352851-8d4e89133924?auto=format&fit=crop&w=900&q=85"},
        {"name": "Roasted Almond Granola", "description": "Crunchy oat granola with roasted almonds and a touch of maple.", "price": 449, "stock": 26, "sku": "SAMPLE-FOOD-002", "image": "https://images.unsplash.com/photo-1517093157656-b9eccef91cb1?auto=format&fit=crop&w=900&q=85"},
    ],
    "Other": [
        {"name": "Handmade Paper Gift Set", "description": "A set of textured artisan paper goods for notes and small gifts.", "price": 699, "stock": 15, "sku": "SAMPLE-OTHER-001", "image": "https://images.unsplash.com/photo-1455390582262-044cdead277a?auto=format&fit=crop&w=900&q=85"},
    ],
}


@router.post("/api/owner/stores/{slug}/products/import-samples/preview")
def preview_sample_products(
    request: SampleImportRequest,
    store: dict[str, Any] = Depends(auth.require_store_member),
):
    products: list[dict[str, Any]] = []
    with get_connection() as connection:
        _validate_setup_sample_categories(connection, store["id"], request.categories)
        for requested_category in request.categories:
            category = _check_category(connection, store["id"], requested_category)
            samples = SAMPLE_PRODUCTS.get(category)
            if samples is None:
                suffix = re.sub(r"[^A-Z0-9]+", "-", category.upper()).strip("-")[:16] or "CUSTOM"
                samples = [{
                    "name": f"Hand-finished {category} Gift Set",
                    "description": f"A thoughtfully assembled sample item for the {category} collection.",
                    "price": 1299, "stock": 12, "sku": f"SAMPLE-{suffix}-001",
                    "image": "https://images.unsplash.com/photo-1455390582262-044cdead277a?auto=format&fit=crop&w=900&q=85",
                }]
            for sample in samples:
                duplicate = connection.execute(
                    "SELECT 1 FROM products WHERE store_id = ? AND (name = ? COLLATE NOCASE OR sku = ? COLLATE NOCASE)",
                    (store["id"], sample["name"], sample["sku"]),
                ).fetchone()
                products.append({
                    "name": sample["name"], "category": category,
                    "description": sample["description"], "price": sample["price"],
                    "stock": sample["stock"], "image_url": sample["image"],
                    "already_exists": duplicate is not None,
                })
    return {
        "total_products": len(products),
        "importable_count": sum(not product["already_exists"] for product in products),
        "skipped_count": sum(product["already_exists"] for product in products),
        "products": products,
    }


@router.post("/api/owner/stores/{slug}/products/import-samples")
def import_sample_products(
    request: SampleImportRequest,
    store: dict[str, Any] = Depends(auth.require_store_member),
):
    imported: list[str] = []
    skipped: list[str] = []
    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        _validate_setup_sample_categories(connection, store["id"], request.categories)
        for requested_category in request.categories:
            category = _check_category(connection, store["id"], requested_category)
            samples = SAMPLE_PRODUCTS.get(category)
            if samples is None:
                suffix = re.sub(r"[^A-Z0-9]+", "-", category.upper()).strip("-")[:16] or "CUSTOM"
                samples = [{
                    "name": f"Hand-finished {category} Gift Set",
                    "description": f"A thoughtfully assembled sample item for the {category} collection.",
                    "price": 1299, "stock": 12, "sku": f"SAMPLE-{suffix}-001",
                    "image": "https://images.unsplash.com/photo-1455390582262-044cdead277a?auto=format&fit=crop&w=900&q=85",
                }]
            for sample in samples:
                data = ProductWrite.model_validate({
                    "name": sample["name"], "description": sample["description"],
                    "category": category, "price": sample["price"], "stock": sample["stock"],
                    "sku": sample["sku"], "images": [sample["image"]], "variants": [],
                })
                duplicate = connection.execute(
                    "SELECT 1 FROM products WHERE store_id = ? AND (name = ? COLLATE NOCASE OR sku = ? COLLATE NOCASE)",
                    (store["id"], data.name, data.sku),
                ).fetchone()
                if duplicate:
                    skipped.append(data.name)
                    continue
                connection.execute(
                    """INSERT INTO products
                       (store_id, name, description, category, price, stock, sku, image_url, images_json, variants_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (store["id"], data.name, data.description, category, data.price, data.stock,
                     data.sku, data.images[0], json.dumps(data.images), "[]"),
                )
                imported.append(data.name)
    return {"imported_count": len(imported), "skipped_count": len(skipped), "imported": imported, "skipped": skipped}


def _validate_setup_sample_categories(connection: sqlite3.Connection, store_id: int, requested: list[str]) -> None:
    setup = connection.execute(
        "SELECT product_setup_method, is_complete FROM store_onboarding WHERE store_id = ?",
        (store_id,),
    ).fetchone()
    if setup is None or setup["is_complete"] or setup["product_setup_method"] != "demo":
        return
    selected = {
        row["name"].casefold()
        for row in connection.execute(
            """SELECT c.name FROM store_category_selections AS selected
               JOIN categories AS c ON c.id = selected.category_id WHERE selected.store_id = ?""",
            (store_id,),
        ).fetchall()
    }
    if any(name.casefold() not in selected for name in requested):
        raise HTTPException(status_code=422, detail="Sample import categories must match the categories selected during setup")


@router.get("/api/owner/stores/{slug}/products")
def list_products(
    slug: str,
    search: str = Query(default="", max_length=160),
    category: str | None = Query(default=None, max_length=50),
    stock: Literal["all", "in_stock", "low_stock", "out_of_stock"] = "all",
    store: dict[str, Any] = Depends(auth.require_store_member),
):
    if store["slug"] != slug:
        raise HTTPException(status_code=404, detail="Store not found")
    clauses = ["store_id = ?"]
    params: list[Any] = [store["id"]]
    if search.strip():
        term = f"%{search.strip()}%"
        clauses.append("(name LIKE ? OR sku LIKE ? OR description LIKE ?)")
        params.extend((term, term, term))
    if category:
        clauses.append("category = ? COLLATE NOCASE")
        params.append(category)
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT id, name, description, category, price, original_price, discount_percent, stock, sku, image_url, images_json, variants_json "
            f"FROM products WHERE {' AND '.join(clauses)} ORDER BY id DESC",
            params,
        ).fetchall()
    products = [_product(row) for row in rows]
    if stock != "all":
        def matches_stock(product: dict[str, Any]) -> bool:
            quantities = [int(variant["stock"]) for variant in product["variants"]] if product["variants"] else [int(product["stock"])]
            if stock == "in_stock":
                return any(quantity > 0 for quantity in quantities)
            if stock == "low_stock":
                return any(1 <= quantity <= 5 for quantity in quantities)
            return all(quantity == 0 for quantity in quantities)
        products = [product for product in products if matches_stock(product)]
    return products


@router.post("/api/owner/stores/{slug}/products", status_code=status.HTTP_201_CREATED)
def create_product(
    request: ProductWrite,
    store: dict[str, Any] = Depends(auth.require_store_member),
):
    try:
        with get_connection() as connection:
            category = _check_category(connection, store["id"], request.category)
            if connection.execute(
                "SELECT 1 FROM products WHERE store_id = ? AND name = ? COLLATE NOCASE",
                (store["id"], request.name),
            ).fetchone():
                raise HTTPException(status_code=409, detail="A product with this name already exists in this store")
            cursor = connection.execute(
                """INSERT INTO products
                   (store_id, name, description, category, price, original_price, discount_percent,
                    stock, sku, image_url, images_json, variants_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (store["id"], request.name, request.description, category, request.price,
                 request.original_price, request.discount_percent, request.stock, request.sku,
                 request.images[0] if request.images else "", json.dumps(request.images),
                 json.dumps([variant.model_dump() for variant in request.variants])),
            )
            row = connection.execute(
                "SELECT id, name, description, category, price, original_price, discount_percent, stock, sku, image_url, images_json, variants_json FROM products WHERE id = ? AND store_id = ?",
                (cursor.lastrowid, store["id"]),
            ).fetchone()
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="Product name or SKU already exists in this store") from error
    return _product(row)


@router.put("/api/owner/stores/{slug}/products/{product_id}")
def update_product(
    product_id: int,
    request: ProductWrite,
    store: dict[str, Any] = Depends(auth.require_store_member),
):
    try:
        with get_connection() as connection:
            category = _check_category(connection, store["id"], request.category)
            current = connection.execute(
                "SELECT id FROM products WHERE id = ? AND store_id = ?", (product_id, store["id"])
            ).fetchone()
            if current is None:
                raise HTTPException(status_code=404, detail="Product not found")
            duplicate = connection.execute(
                "SELECT 1 FROM products WHERE store_id = ? AND lower(name) = lower(?) AND id <> ?",
                (store["id"], request.name, product_id),
            ).fetchone()
            if duplicate:
                raise HTTPException(status_code=409, detail="A product with this name already exists in this store")
            connection.execute(
                """UPDATE products SET name = ?, description = ?, category = ?, price = ?, original_price = ?,
                   discount_percent = ?, stock = ?, sku = ?, image_url = ?, images_json = ?, variants_json = ?
                   WHERE id = ? AND store_id = ?""",
                (request.name, request.description, category, request.price, request.original_price,
                 request.discount_percent, request.stock, request.sku,
                 request.images[0] if request.images else "", json.dumps(request.images),
                 json.dumps([variant.model_dump() for variant in request.variants]), product_id, store["id"]),
            )
            row = connection.execute(
                "SELECT id, name, description, category, price, original_price, discount_percent, stock, sku, image_url, images_json, variants_json FROM products WHERE id = ? AND store_id = ?",
                (product_id, store["id"]),
            ).fetchone()
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="Product name or SKU already exists in this store") from error
    return _product(row)


@router.delete("/api/owner/stores/{slug}/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: int,
    store: dict[str, Any] = Depends(auth.require_store_member),
):
    with get_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM products WHERE id = ? AND store_id = ?", (product_id, store["id"])
        )
        if cursor.rowcount != 1:
            raise HTTPException(status_code=404, detail="Product not found")
    return None


@router.patch("/api/owner/stores/{slug}/products/bulk")
def bulk_update_products(
    request: BulkProductUpdate,
    store: dict[str, Any] = Depends(auth.require_store_member),
):
    product_ids = list(dict.fromkeys(request.product_ids))
    changes = request.changes.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="At least one update field is required")
    if any(changes.get(key) is None for key in ("price", "stock", "category") if key in changes):
        raise HTTPException(status_code=422, detail="Stock, price, and category cannot be null")
    with get_connection() as connection:
        if "category" in changes:
            changes["category"] = _check_category(connection, store["id"], changes["category"])
        placeholders = ",".join("?" for _ in product_ids)
        count = connection.execute(
            f"SELECT COUNT(*) FROM products WHERE store_id = ? AND id IN ({placeholders})",
            [store["id"], *product_ids],
        ).fetchone()[0]
        if count != len(product_ids):
            raise HTTPException(status_code=404, detail="One or more products were not found in this store")
        if "price" in changes:
            invalid_compare_price = connection.execute(
                f"SELECT 1 FROM products WHERE store_id = ? AND id IN ({placeholders}) "
                "AND original_price IS NOT NULL AND original_price <= ? LIMIT 1",
                [store["id"], *product_ids, changes["price"]],
            ).fetchone()
            if invalid_compare_price:
                raise HTTPException(
                    status_code=422,
                    detail="Bulk price would make an existing original price invalid",
                )
        stock_value = changes.pop("stock", None)
        assignments = ", ".join(f"{field} = ?" for field in changes)
        if assignments:
            connection.execute(
                f"UPDATE products SET {assignments} WHERE store_id = ? AND id IN ({placeholders})",
                [*changes.values(), store["id"], *product_ids],
            )
        if stock_value is not None:
            # The bulk stock control means “set available stock”; keep variant
            # inventory in sync so owner filters and checkout agree afterward.
            rows = connection.execute(
                f"SELECT id, variants_json FROM products WHERE store_id = ? AND id IN ({placeholders})",
                [store["id"], *product_ids],
            ).fetchall()
            for row in rows:
                try:
                    variants = json.loads(row["variants_json"] or "[]")
                except (TypeError, json.JSONDecodeError):
                    variants = []
                if isinstance(variants, list):
                    for variant in variants:
                        if isinstance(variant, dict):
                            variant["stock"] = stock_value
                connection.execute(
                    "UPDATE products SET stock = ?, variants_json = ? WHERE id = ? AND store_id = ?",
                    (stock_value, json.dumps(variants), row["id"], store["id"]),
                )
    return {"updated_count": len(product_ids)}


def _preview_csv(connection: sqlite3.Connection, store_id: int, csv_text: str, mapping: dict[str, str]) -> dict[str, Any]:
    try:
        encoded_length = len(csv_text.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise HTTPException(status_code=422, detail="CSV contains invalid Unicode text") from error
    if encoded_length > MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail=f"CSV file exceeds the {MAX_CSV_BYTES}-byte limit")
    if not mapping or set(mapping) - CSV_FIELDS:
        raise HTTPException(status_code=422, detail="Column mapping contains unsupported product fields")
    if not {"name", "price", "category"}.issubset(mapping):
        raise HTTPException(status_code=422, detail="Map name, price, and category columns before previewing")
    try:
        reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff"), newline=""), strict=True)
        headers = [header.strip() if header else "" for header in (reader.fieldnames or [])]
        if not headers or any(not header for header in headers) or len(headers) != len(set(headers)):
            raise HTTPException(status_code=422, detail="CSV must have unique, non-empty column headers")
        missing_headers = set(mapping.values()) - set(headers)
        if missing_headers:
            raise HTTPException(status_code=422, detail=f"Mapped columns are missing: {', '.join(sorted(missing_headers))}")
        if any(header != raw for header, raw in zip(headers, reader.fieldnames or [])):
            reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff"), newline=""), strict=True)
            reader.fieldnames = headers
        source_rows = []
        for index, raw in enumerate(reader):
            if index >= MAX_CSV_ROWS:
                raise HTTPException(status_code=413, detail=f"CSV exceeds the {MAX_CSV_ROWS}-row limit")
            if None in raw:
                source_rows.append({"__row_error": "This row contains more values than the header"})
            elif not any((value or "").strip() for value in raw.values()):
                continue
            else:
                source_rows.append(raw)
    except csv.Error as error:
        raise HTTPException(status_code=422, detail="Malformed CSV file") from error
    if not source_rows:
        raise HTTPException(status_code=422, detail="CSV contains no product rows")

    existing = connection.execute(
        "SELECT lower(name) AS normalized_name, lower(sku) AS normalized_sku FROM products WHERE store_id = ?",
        (store_id,),
    ).fetchall()
    existing_names = {row["normalized_name"] for row in existing}
    existing_skus = {row["normalized_sku"] for row in existing if row["normalized_sku"]}
    onboarding = connection.execute(
        "SELECT product_setup_method, is_complete FROM store_onboarding WHERE store_id = ?",
        (store_id,),
    ).fetchone()
    selected_categories: set[str] = set()
    if onboarding is not None and not onboarding["is_complete"] and onboarding["product_setup_method"] == "spreadsheet":
        selected_categories = {
            row["name"].casefold()
            for row in connection.execute(
                """SELECT c.name FROM store_category_selections AS selected
                   JOIN categories AS c ON c.id = selected.category_id WHERE selected.store_id = ?""",
                (store_id,),
            ).fetchall()
        }
    seen_names: dict[str, int] = {}
    seen_skus: dict[str, int] = {}
    preview_rows = []
    for offset, raw in enumerate(source_rows, start=2):
        errors: list[str] = []
        if "__row_error" in raw:
            errors.append(raw["__row_error"])
            data: dict[str, Any] = {}
        else:
            data = {field: (raw.get(column, "") or "").strip() for field, column in mapping.items()}
            if not data.get("name"):
                errors.append("Name is required")
            if not data.get("category"):
                errors.append("Category is required")
            try:
                data["price"] = float(data["price"])
            except (TypeError, ValueError):
                errors.append("Price must be a valid number")
            if data.get("original_price"):
                try:
                    data["original_price"] = float(data["original_price"])
                except ValueError:
                    errors.append("Original price must be a valid number")
            else:
                data["original_price"] = None
            if data.get("discount_percent"):
                try:
                    data["discount_percent"] = float(data["discount_percent"])
                except ValueError:
                    errors.append("Discount must be a valid percentage")
            else:
                data["discount_percent"] = None
            if data.get("stock"):
                try:
                    data["stock"] = int(data["stock"])
                except ValueError:
                    errors.append("Stock must be a whole number")
            else:
                data["stock"] = 0
            if data.get("sku") == "":
                data["sku"] = None
            image_url = data.pop("image_url", "")
            data["images"] = [image_url] if image_url else []
            data["variants"] = []
            try:
                product = ProductWrite.model_validate(data)
                data = product.model_dump(mode="json")
            except ValidationError as error:
                errors.extend(f"{'.'.join(str(part) for part in issue['loc'])}: {issue['msg']}" for issue in error.errors())
            else:
                try:
                    _check_category(connection, store_id, product.category)
                except HTTPException:
                    errors.append(f"Category '{product.category}' is not available for this store")
                if selected_categories and product.category.casefold() not in selected_categories:
                    errors.append(f"Category '{product.category}' was not selected during setup")
                name_key = product.name.casefold()
                sku_key = product.sku.casefold() if product.sku else ""
                duplicate_of = None
                if name_key in existing_names or name_key in seen_names:
                    duplicate_of = seen_names.get(name_key, 0) or "existing product"
                elif sku_key and (sku_key in existing_skus or sku_key in seen_skus):
                    duplicate_of = seen_skus.get(sku_key, 0) or "existing SKU"
                if duplicate_of:
                    errors.append(f"Duplicate product ({duplicate_of})")
                seen_names.setdefault(name_key, offset)
                if sku_key:
                    seen_skus.setdefault(sku_key, offset)
        preview_rows.append({"row": offset, "data": data, "errors": errors, "valid": not errors})
    valid_count = sum(row["valid"] for row in preview_rows)
    return {
        "headers": headers,
        "rows": preview_rows,
        "total_rows": len(preview_rows),
        "valid_rows": valid_count,
        "error_rows": len(preview_rows) - valid_count,
        "can_import": valid_count == len(preview_rows),
    }


def _xlsx_to_csv(encoded: str) -> str:
    """Parse one bounded .xlsx sheet and reject formulas and malformed archives."""
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise HTTPException(status_code=422, detail="XLSX payload is not valid base64") from error
    if not content or len(content) > MAX_XLSX_BYTES:
        raise HTTPException(status_code=413, detail=f"XLSX file exceeds the {MAX_XLSX_BYTES}-byte limit")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) > 100 or any(member.filename.startswith(("/", "\\")) or ".." in member.filename.split("/") for member in members):
                raise HTTPException(status_code=422, detail="XLSX archive has an invalid structure")
            expanded = sum(member.file_size for member in members)
            if expanded > MAX_XLSX_EXPANDED_BYTES:
                raise HTTPException(status_code=413, detail="XLSX expands beyond the allowed size")
            if any(member.file_size > 100_000 and member.compress_size and member.file_size / member.compress_size > 100 for member in members):
                raise HTTPException(status_code=422, detail="XLSX compression ratio is unsafe")
            if "[Content_Types].xml" not in archive.namelist() or "xl/workbook.xml" not in archive.namelist():
                raise HTTPException(status_code=422, detail="File is not a valid XLSX workbook")
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=False, keep_links=False)
        worksheet = workbook.worksheets[0] if workbook.worksheets else None
        if worksheet is None:
            raise HTTPException(status_code=422, detail="XLSX workbook has no worksheets")
        if (worksheet.max_row or 0) > MAX_CSV_ROWS + 1:
            raise HTTPException(status_code=413, detail=f"XLSX exceeds the {MAX_CSV_ROWS}-row limit")
        if (worksheet.max_column or 0) > MAX_XLSX_COLUMNS:
            raise HTTPException(status_code=422, detail=f"XLSX may contain at most {MAX_XLSX_COLUMNS} columns")
        csv_buffer = io.StringIO(newline="")
        writer = csv.writer(csv_buffer)
        row_count = 0
        for row in worksheet.iter_rows():
            if len(row) > MAX_XLSX_COLUMNS:
                raise HTTPException(status_code=422, detail=f"XLSX may contain at most {MAX_XLSX_COLUMNS} columns")
            if any(cell.data_type == "f" for cell in row):
                raise HTTPException(status_code=422, detail="Formula cells are not accepted; replace formulas with reviewed values")
            values = [cell.value for cell in row]
            if not any(value is not None and str(value).strip() for value in values):
                continue
            row_count += 1
            if row_count > MAX_CSV_ROWS + 1:
                raise HTTPException(status_code=413, detail=f"XLSX exceeds the {MAX_CSV_ROWS}-row limit")
            writer.writerow([value.isoformat() if hasattr(value, "isoformat") else "" if value is None else str(value) for value in values])
        workbook.close()
    except HTTPException:
        raise
    except (zipfile.BadZipFile, OSError, ValueError, KeyError, IndexError) as error:
        raise HTTPException(status_code=422, detail="Malformed or unsupported XLSX workbook") from error
    if not csv_buffer.getvalue():
        raise HTTPException(status_code=422, detail="XLSX worksheet is empty")
    return csv_buffer.getvalue()


@router.post("/api/owner/stores/{slug}/products/import/preview")
def preview_product_import(
    request: CSVImportRequest,
    store: dict[str, Any] = Depends(auth.require_store_member),
):
    with get_connection() as connection:
        return _preview_csv(connection, store["id"], request.csv_text, request.mapping)


@router.post("/api/owner/stores/{slug}/products/import")
def import_products(
    request: CSVImportRequest,
    store: dict[str, Any] = Depends(auth.require_store_member),
):
    if not request.confirmed:
        raise HTTPException(status_code=400, detail="Confirm the reviewed import before submitting")
    try:
        with get_connection() as connection:
            preview = _preview_csv(connection, store["id"], request.csv_text, request.mapping)
            if not preview["can_import"]:
                raise HTTPException(
                    status_code=422,
                    detail={"message": "Fix all row errors before importing", "rows": preview["rows"]},
                )
            for item in preview["rows"]:
                data = item["data"]
                category = _check_category(connection, store["id"], data["category"])
                connection.execute(
                    """INSERT INTO products
                       (store_id, name, description, category, price, original_price, discount_percent,
                        stock, sku, image_url, images_json, variants_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (store["id"], data["name"], data["description"], category, data["price"],
                     data["original_price"], data["discount_percent"], data["stock"], data["sku"],
                     data["images"][0] if data["images"] else "", json.dumps(data["images"]), "[]"),
                )
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="A product name or SKU became duplicated during import") from error
    return {"imported_count": preview["total_rows"], "summary": "All reviewed products were imported."}


@router.post("/api/owner/stores/{slug}/products/import-xlsx/preview")
def preview_xlsx_import(
    request: XLSXImportRequest,
    store: dict[str, Any] = Depends(auth.require_store_member),
):
    csv_text = _xlsx_to_csv(request.xlsx_base64)
    with get_connection() as connection:
        return _preview_csv(connection, store["id"], csv_text, request.mapping)


@router.get("/api/owner/stores/{slug}/products/import-xlsx/template")
def download_xlsx_template(store: dict[str, Any] = Depends(auth.require_store_member)):
    del store  # enforce store membership before returning the template
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Products"
    sheet.append(["name", "description", "category", "price", "original_price", "stock", "sku", "image_url", "discount_percent"])
    sheet.append(["Woven Basket", "Handwoven storage basket", "Home", 24.99, 29.99, 12, "BASKET-01", "https://example.com/basket.jpg", None])
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="store-products-template.xlsx"'},
    )


@router.post("/api/owner/stores/{slug}/products/import-xlsx/headers")
def xlsx_import_headers(
    request: XLSXImportRequest,
    store: dict[str, Any] = Depends(auth.require_store_member),
):
    del store  # dependency enforces ownership before the workbook is parsed
    try:
        reader = csv.reader(io.StringIO(_xlsx_to_csv(request.xlsx_base64), newline=""), strict=True)
        headers = [value.strip() for value in next(reader, [])]
    except csv.Error as error:
        raise HTTPException(status_code=422, detail="Malformed XLSX header row") from error
    if not headers or any(not header for header in headers) or len(headers) != len(set(headers)):
        raise HTTPException(status_code=422, detail="XLSX must have unique, non-empty column headers")
    return {"headers": headers}


@router.post("/api/owner/stores/{slug}/products/import-xlsx")
def import_xlsx_products(
    request: XLSXImportRequest,
    store: dict[str, Any] = Depends(auth.require_store_member),
):
    if not request.confirmed:
        raise HTTPException(status_code=400, detail="Confirm the reviewed import before submitting")
    csv_text = _xlsx_to_csv(request.xlsx_base64)
    try:
        with get_connection() as connection:
            preview = _preview_csv(connection, store["id"], csv_text, request.mapping)
            if not preview["can_import"]:
                raise HTTPException(status_code=422, detail={"message": "Fix all row errors before importing", "rows": preview["rows"]})
            for item in preview["rows"]:
                data = item["data"]
                category = _check_category(connection, store["id"], data["category"])
                connection.execute(
                    """INSERT INTO products
                       (store_id, name, description, category, price, original_price, discount_percent,
                        stock, sku, image_url, images_json, variants_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (store["id"], data["name"], data["description"], category, data["price"],
                     data["original_price"], data["discount_percent"], data["stock"], data["sku"],
                     data["images"][0] if data["images"] else "", json.dumps(data["images"]), "[]"),
                )
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="A product name or SKU became duplicated during import") from error
    return {"imported_count": preview["total_rows"], "summary": "All reviewed spreadsheet rows were imported."}


@router.get("/api/owner/stores/{slug}/customization")
def get_customization(
    store: dict[str, Any] = Depends(auth.require_store_owner),
):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM store_customizations WHERE store_id = ?", (store["id"],)
        ).fetchone()
    return _theme_settings(row)


@router.patch("/api/owner/stores/{slug}/customization")
def update_customization(
    request: ThemeUpdate,
    store: dict[str, Any] = Depends(auth.require_store_owner),
):
    changes = request.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Provide at least one customization field")
    if any(value is None for name, value in changes.items() if name != "banner_url"):
        raise HTTPException(status_code=422, detail="Only the banner URL may be cleared")
    if "banner_url" in changes and changes["banner_url"] == "":
        changes["banner_url"] = None
    if "homepage_sections" in changes:
        changes["homepage_sections_json"] = json.dumps(changes.pop("homepage_sections"))
    assignments = ", ".join(f"{name} = ?" for name in changes)
    values = [*changes.values(), store["id"]]
    with get_connection() as connection:
        connection.execute(
            f"UPDATE store_customizations SET {assignments} WHERE store_id = ?", values
        )
        public_contact = {field: changes[field] for field in ("contact_email", "contact_phone") if field in changes}
        if public_contact:
            public_assignments = ", ".join(f"{field} = ?" for field in public_contact)
            connection.execute(
                f"UPDATE stores SET {public_assignments} WHERE id = ?",
                [*public_contact.values(), store["id"]],
            )
        row = connection.execute(
            "SELECT * FROM store_customizations WHERE store_id = ?", (store["id"],)
        ).fetchone()
    return _theme_settings(row)
