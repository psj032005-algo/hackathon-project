
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DATABASE_PATH = Path(__file__).resolve().parent / "data" / "store.db"


def get_connection():
    """Open a SQLite connection with foreign-key checks enabled."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def get_db():
    """Provide a database connection and always close it."""
    connection = get_connection()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db():
    """Create all tables if they do not exist."""
    with get_db() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS stores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_name TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                owner_email TEXT NOT NULL,
                logo_url TEXT,
                business_type TEXT,
                phone TEXT,
                address TEXT,
                theme TEXT NOT NULL DEFAULT 'minimal_luxe',
                published INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'owner'
                    CHECK (role IN ('owner', 'staff')),
                store_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (store_id) REFERENCES stores(id)
                    ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                is_custom INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (store_id) REFERENCES stores(id)
                    ON DELETE CASCADE,
                UNIQUE (store_id, name)
            );

            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id INTEGER NOT NULL,
                sku TEXT,
                name TEXT NOT NULL,
                description TEXT,
                price REAL NOT NULL CHECK (price >= 0),
                original_price REAL,
                category TEXT,
                image_url TEXT,
                stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
                low_stock_threshold INTEGER NOT NULL DEFAULT 5,
                status TEXT NOT NULL DEFAULT 'published'
                    CHECK (status IN ('published', 'draft')),
                variants_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (store_id) REFERENCES stores(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_products_store
                ON products(store_id);

            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id INTEGER NOT NULL,
                receipt_code TEXT NOT NULL UNIQUE,
                customer_name TEXT NOT NULL,
                customer_email TEXT NOT NULL,
                customer_phone TEXT,
                delivery_address TEXT NOT NULL,
                items_json TEXT NOT NULL,
                item_count INTEGER NOT NULL DEFAULT 0,
                subtotal REAL NOT NULL CHECK (subtotal >= 0),
                total REAL NOT NULL CHECK (total >= 0),
                status TEXT NOT NULL DEFAULT 'Placed'
                    CHECK (status IN (
                        'Placed', 'Packed', 'Shipped',
                        'Delivered', 'Cancelled'
                    )),
                payment_status TEXT NOT NULL DEFAULT 'Test order - unpaid',
                status_history_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (store_id) REFERENCES stores(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_orders_store
                ON orders(store_id);
            """
        )
