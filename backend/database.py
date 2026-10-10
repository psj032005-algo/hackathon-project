"""SQLite persistence and additive schema migrations for the storefront API."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


BACKEND_DIR = Path(__file__).resolve().parent
DEFAULT_DATABASE_PATH = BACKEND_DIR / "storefront.db"
PREDEFINED_CATEGORIES = ("Accessories", "Home", "Wellness", "Clothing", "Food", "Other")


def get_database_path() -> Path:
    """Return the configured database path or the ignored local default."""
    configured_path = os.environ.get("STOREFRONT_DATABASE_PATH")
    path = Path(configured_path).expanduser() if configured_path else DEFAULT_DATABASE_PATH
    if not path.is_absolute():
        path = (BACKEND_DIR / path).resolve()
    return path


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Open a transaction and always close its SQLite connection."""
    database_path = get_database_path()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, timeout=10)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}


def initialize_database() -> None:
    """Create missing tables and migrate old schemas without replacing records."""
    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS stores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                logo_url TEXT,
                owner_user_id INTEGER REFERENCES users(id) ON DELETE RESTRICT,
                is_published INTEGER NOT NULL DEFAULT 1 CHECK (is_published IN (0, 1))
            )
            """
        )

        store_columns = _column_names(connection, "stores")
        if "owner_user_id" not in store_columns:
            # NULL keeps all legacy stores unowned until an explicit transfer process.
            connection.execute(
                "ALTER TABLE stores ADD COLUMN owner_user_id INTEGER "
                "REFERENCES users(id) ON DELETE RESTRICT"
            )
        if "is_published" not in store_columns:
            # Existing stores were publicly visible before this migration.
            connection.execute(
                "ALTER TABLE stores ADD COLUMN is_published INTEGER NOT NULL "
                "DEFAULT 1 CHECK (is_published IN (0, 1))"
            )

        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_stores_owner_user_id "
            "ON stores(owner_user_id)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                price REAL NOT NULL CHECK (price >= 0),
                original_price REAL CHECK (original_price IS NULL OR original_price >= 0),
                stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
                image_url TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (store_id) REFERENCES stores(id) ON DELETE CASCADE,
                UNIQUE (store_id, name)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)", (1,)
        )

        product_columns = _column_names(connection, "products")
        for column, declaration in (
            ("sku", "TEXT"),
            ("images_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("variants_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("discount_percent", "REAL"),
        ):
            if column not in product_columns:
                connection.execute(f"ALTER TABLE products ADD COLUMN {column} {declaration}")

        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_products_store_sku
            ON products(store_id, sku) WHERE sku IS NOT NULL AND sku <> ''
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                is_predefined INTEGER NOT NULL DEFAULT 0 CHECK (is_predefined IN (0, 1)),
                FOREIGN KEY (store_id) REFERENCES stores(id) ON DELETE CASCADE,
                UNIQUE (store_id, name)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_categories_store_id ON categories(store_id)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS store_customizations (
                store_id INTEGER PRIMARY KEY,
                theme_id TEXT NOT NULL DEFAULT 'market',
                primary_color TEXT NOT NULL DEFAULT '#243c30',
                accent_color TEXT NOT NULL DEFAULT '#9b7753',
                background_color TEXT NOT NULL DEFAULT '#faf9f6',
                font_family TEXT NOT NULL DEFAULT 'sans',
                banner_url TEXT,
                homepage_sections_json TEXT NOT NULL DEFAULT '["hero","featured","categories"]',
                footer_text TEXT NOT NULL DEFAULT '',
                contact_email TEXT NOT NULL DEFAULT '',
                contact_phone TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (store_id) REFERENCES stores(id) ON DELETE CASCADE
            )
            """
        )

        for category in PREDEFINED_CATEGORIES:
            connection.execute(
                """
                INSERT OR IGNORE INTO categories (store_id, name, is_predefined)
                SELECT id, ?, 1 FROM stores
                """,
                (category,),
            )
        connection.execute(
            """
            INSERT OR IGNORE INTO categories (store_id, name, is_predefined)
            SELECT DISTINCT store_id, category, 0 FROM products
            WHERE TRIM(category) <> ''
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO store_customizations (store_id)
            SELECT id FROM stores
            """
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)", (2,)
        )

        # Version 3 is additive: existing stores and products are retained, and
        # new orders only reference records created after this migration.
        custom_columns = _column_names(connection, "store_customizations")
        for column in ("shipping_policy", "returns_policy"):
            if column not in custom_columns:
                connection.execute(
                    f"ALTER TABLE store_customizations ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"
                )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE RESTRICT,
                public_ref TEXT NOT NULL UNIQUE,
                lookup_hash TEXT NOT NULL,
                request_hash TEXT NOT NULL DEFAULT '',
                idempotency_key TEXT,
                customer_name TEXT NOT NULL,
                customer_email TEXT NOT NULL,
                customer_phone TEXT NOT NULL,
                address_line1 TEXT NOT NULL,
                address_line2 TEXT NOT NULL DEFAULT '',
                city TEXT NOT NULL,
                region TEXT NOT NULL DEFAULT '',
                postal_code TEXT NOT NULL,
                country TEXT NOT NULL,
                delivery_notes TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL CHECK (status IN ('placed','packed','shipped','delivered','cancelled')),
                subtotal REAL NOT NULL CHECK (subtotal >= 0),
                payment_method TEXT NOT NULL DEFAULT 'demo',
                payment_status TEXT NOT NULL DEFAULT 'not_processed',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        order_columns = _column_names(connection, "orders")
        if "request_hash" not in order_columns:
            connection.execute("ALTER TABLE orders ADD COLUMN request_hash TEXT NOT NULL DEFAULT ''")
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_store_idempotency "
            "ON orders(store_id, idempotency_key) WHERE idempotency_key IS NOT NULL"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_orders_store_created ON orders(store_id, created_at DESC)"
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
                product_name TEXT NOT NULL,
                category TEXT NOT NULL,
                sku TEXT,
                variant_json TEXT,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                unit_price REAL NOT NULL CHECK (unit_price >= 0),
                discount_percent REAL NOT NULL DEFAULT 0 CHECK (discount_percent BETWEEN 0 AND 90),
                line_total REAL NOT NULL CHECK (line_total >= 0)
            )"""
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id)"
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS order_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                from_status TEXT,
                to_status TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)", (3,)
        )

        connection.execute(
            """
            INSERT OR IGNORE INTO stores (slug, name, description)
            VALUES (?, ?, ?)
            """,
            (
                "littlemarket-demo-2",
                "Little Market",
                "Thoughtful everyday essentials for your home and style.",
            ),
        )
        store = connection.execute(
            "SELECT id FROM stores WHERE slug = ?", ("littlemarket-demo-2",)
        ).fetchone()
        if store is None:
            raise RuntimeError("Demo store initialization failed")

        for category in PREDEFINED_CATEGORIES:
            connection.execute(
                "INSERT OR IGNORE INTO categories (store_id, name, is_predefined) VALUES (?, ?, 1)",
                (store["id"], category),
            )
        connection.execute(
            "INSERT OR IGNORE INTO store_customizations (store_id) VALUES (?)",
            (store["id"],),
        )

        demo_products = [
            (
                "Woven Market Tote",
                "Accessories",
                1499,
                1799,
                18,
                "https://images.unsplash.com/photo-1590874103328-eac38a683ce7?auto=format&fit=crop&w=900&q=85",
                "A sturdy handwoven tote for market mornings and everyday errands.",
            ),
            (
                "Stoneware Coffee Mug",
                "Home",
                899,
                None,
                24,
                "https://images.unsplash.com/photo-1514228742587-6b1558f89616?auto=format&fit=crop&w=900&q=85",
                "A softly speckled ceramic mug, shaped for a slow cup of coffee.",
            ),
            (
                "Linen Cushion Cover",
                "Home",
                1299,
                1499,
                12,
                "https://images.unsplash.com/photo-1584100936595-c0654b55a2e2?auto=format&fit=crop&w=900&q=85",
                "A breathable natural-linen cushion cover in a warm, versatile neutral.",
            ),
            (
                "Botanical Soy Candle",
                "Wellness",
                1099,
                None,
                9,
                "https://images.unsplash.com/photo-1603006905003-be475563bc59?auto=format&fit=crop&w=900&q=85",
                "A hand-poured soy candle with a gentle botanical fragrance.",
            ),
        ]
        connection.executemany(
            """
            INSERT OR IGNORE INTO products
                (store_id, name, category, price, original_price, stock, image_url, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [(store["id"], *product) for product in demo_products],
        )
