"""Tenant-scoped product, category, import, and storefront customization APIs."""

from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
    result["homepage_sections"] = json.loads(result.pop("homepage_sections_json"))
    return result


@router.get("/api/owner/stores/{slug}/categories")
def list_categories(
    store: dict[str, Any] = Depends(auth.require_store_owner),
):
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT name, is_predefined FROM categories WHERE store_id = ? ORDER BY is_predefined DESC, name COLLATE NOCASE",
            (store["id"],),
        ).fetchall()
    return [{"name": row["name"], "is_predefined": bool(row["is_predefined"])} for row in rows]


@router.post("/api/owner/stores/{slug}/categories", status_code=status.HTTP_201_CREATED)
def create_category(
    request: CategoryCreate,
    store: dict[str, Any] = Depends(auth.require_store_owner),
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


@router.get("/api/owner/stores/{slug}/products")
def list_products(
    slug: str,
    search: str = Query(default="", max_length=160),
    category: str | None = Query(default=None, max_length=50),
    stock: Literal["all", "in_stock", "low_stock", "out_of_stock"] = "all",
    store: dict[str, Any] = Depends(auth.require_store_owner),
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
    if stock == "in_stock":
        clauses.append("stock > 0")
    elif stock == "low_stock":
        clauses.append("stock BETWEEN 1 AND 5")
    elif stock == "out_of_stock":
        clauses.append("stock = 0")
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT id, name, description, category, price, original_price, discount_percent, stock, sku, image_url, images_json, variants_json "
            f"FROM products WHERE {' AND '.join(clauses)} ORDER BY id DESC",
            params,
        ).fetchall()
    return [_product(row) for row in rows]


@router.post("/api/owner/stores/{slug}/products", status_code=status.HTTP_201_CREATED)
def create_product(
    request: ProductWrite,
    store: dict[str, Any] = Depends(auth.require_store_owner),
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
    store: dict[str, Any] = Depends(auth.require_store_owner),
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
    store: dict[str, Any] = Depends(auth.require_store_owner),
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
    store: dict[str, Any] = Depends(auth.require_store_owner),
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
        assignments = ", ".join(f"{field} = ?" for field in changes)
        connection.execute(
            f"UPDATE products SET {assignments} WHERE store_id = ? AND id IN ({placeholders})",
            [*changes.values(), store["id"], *product_ids],
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


@router.post("/api/owner/stores/{slug}/products/import/preview")
def preview_product_import(
    request: CSVImportRequest,
    store: dict[str, Any] = Depends(auth.require_store_owner),
):
    with get_connection() as connection:
        return _preview_csv(connection, store["id"], request.csv_text, request.mapping)


@router.post("/api/owner/stores/{slug}/products/import")
def import_products(
    request: CSVImportRequest,
    store: dict[str, Any] = Depends(auth.require_store_owner),
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
        row = connection.execute(
            "SELECT * FROM store_customizations WHERE store_id = ?", (store["id"],)
        ).fetchone()
    return _theme_settings(row)
