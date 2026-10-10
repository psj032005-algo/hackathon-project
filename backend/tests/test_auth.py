import sqlite3

import jwt
import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from database import initialize_database
from main import app
from config import load_backend_env


TEST_JWT_SECRET = "test-secret-for-isolated-auth-suite-0123456789"


@pytest.fixture
def client(tmp_path, monkeypatch):
    database_path = tmp_path / "isolated-test.sqlite3"
    monkeypatch.setenv("STOREFRONT_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.delenv("JWT_ISSUER", raising=False)
    monkeypatch.delenv("JWT_ACCESS_TOKEN_MINUTES", raising=False)
    with TestClient(app) as test_client:
        yield test_client


def register_owner(client, email="owner@example.com", slug="owner-shop"):
    return client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "a-strong-test-password",
            "store_name": f"{slug} Store",
            "store_slug": slug,
        },
    )


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def test_registration_hashes_password_and_preserves_unowned_demo(client, tmp_path):
    response = register_owner(client)
    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["store"] == {
        "slug": "owner-shop",
        "name": "owner-shop Store",
        "is_published": False,
    }

    connection = sqlite3.connect(tmp_path / "isolated-test.sqlite3")
    try:
        user = connection.execute(
            "SELECT id, email, password_hash FROM users WHERE email = ?",
            ("owner@example.com",),
        ).fetchone()
        assert user is not None
        assert user[2] != "a-strong-test-password"
        assert PasswordHasher().verify(user[2], "a-strong-test-password")

        owner_store = connection.execute(
            "SELECT owner_user_id, is_published FROM stores WHERE slug = ?",
            ("owner-shop",),
        ).fetchone()
        assert owner_store == (user[0], 0)

        demo_store = connection.execute(
            "SELECT id, owner_user_id, is_published FROM stores WHERE slug = ?",
            ("littlemarket-demo-2",),
        ).fetchone()
        assert demo_store is not None
        assert demo_store[1:] == (None, 1)
        assert connection.execute(
            "SELECT COUNT(*) FROM products WHERE store_id = ?", (demo_store[0],)
        ).fetchone()[0] == 4
    finally:
        connection.close()


def test_login_returns_signed_bearer_token(client):
    assert register_owner(client).status_code == 201
    response = client.post(
        "/api/auth/login",
        json={"email": "OWNER@example.com", "password": "a-strong-test-password"},
    )
    assert response.status_code == 200
    payload = jwt.decode(
        response.json()["access_token"],
        TEST_JWT_SECRET,
        algorithms=["HS256"],
        issuer="launch-store-backend",
        options={"require": ["exp", "iat", "iss", "sub", "token_type"]},
    )
    assert payload["token_type"] == "access"


def test_invalid_credentials_return_same_error(client):
    assert register_owner(client).status_code == 201
    wrong_password = client.post(
        "/api/auth/login",
        json={"email": "owner@example.com", "password": "not-the-password"},
    )
    unknown_email = client.post(
        "/api/auth/login",
        json={"email": "missing@example.com", "password": "not-the-password"},
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["detail"] == unknown_email.json()["detail"]


def test_missing_and_invalid_tokens_cannot_read_private_store(client):
    assert register_owner(client).status_code == 201
    path = "/api/owner/stores/owner-shop"

    assert client.get(path).status_code == 401
    assert client.get(path, headers=auth_header("not.a.valid-token")).status_code == 401
    assert client.patch(path, json={"name": "Unauthorized"}).status_code == 401
    assert client.patch(
        path,
        headers=auth_header("not.a.valid-token"),
        json={"name": "Unauthorized"},
    ).status_code == 401

    forged = jwt.encode(
        {
            "sub": "1",
            "iss": "launch-store-backend",
            "iat": 2_000_000_000,
            "exp": 2_000_000_060,
            "token_type": "access",
        },
        "a-different-test-secret-that-is-also-long-enough",
        algorithm="HS256",
    )
    assert client.get(path, headers=auth_header(forged)).status_code == 401


def test_missing_or_weak_jwt_secret_fails_closed_without_registration(client, tmp_path, monkeypatch):
    payload = {
        "email": "unconfigured@example.com",
        "password": "a-strong-test-password",
        "store_name": "Unavailable Store",
        "store_slug": "unavailable-store",
    }
    monkeypatch.delenv("JWT_SECRET")
    missing = client.post("/api/auth/register", json=payload)
    assert missing.status_code == 503
    assert "backend/.env" in missing.json()["detail"]
    assert client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "a-strong-test-password"},
    ).status_code == 503

    monkeypatch.setenv("JWT_SECRET", "too-short")
    assert client.post("/api/auth/register", json=payload).status_code == 503
    monkeypatch.setenv("JWT_SECRET", "a" * 48)
    assert client.post("/api/auth/register", json=payload).status_code == 503

    connection = sqlite3.connect(tmp_path / "isolated-test.sqlite3")
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM users WHERE email = ?", ("unconfigured@example.com",)
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_backend_env_file_loading_preserves_process_environment(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# Local-only backend configuration\n"
        "JWT_SECRET=file-secret-value\n"
        "JWT_ISSUER='test issuer'\n"
        "export APP_MODE=development # local setting\n",
        encoding="utf-8",
    )
    environ = {"JWT_SECRET": "process-secret-value"}

    load_backend_env(env_file, environ)

    assert environ == {
        "JWT_SECRET": "process-secret-value",
        "JWT_ISSUER": "test issuer",
        "APP_MODE": "development",
    }


def test_cross_tenant_reads_and_writes_are_denied(client):
    first = register_owner(client, "first@example.com", "first-shop").json()
    second = register_owner(client, "second@example.com", "second-shop").json()
    first_headers = auth_header(first["access_token"])
    second_headers = auth_header(second["access_token"])

    assert client.get("/api/owner/stores/first-shop", headers=first_headers).status_code == 200
    update_own_store = client.patch(
        "/api/owner/stores/first-shop",
        headers=first_headers,
        json={"description": "Owned by the first account"},
    )
    assert update_own_store.status_code == 200

    second_store_path = "/api/owner/stores/second-shop"
    assert client.get(second_store_path, headers=first_headers).status_code == 404
    assert client.patch(
        second_store_path,
        headers=first_headers,
        json={"name": "Compromised name", "is_published": True},
    ).status_code == 404

    second_store = client.get(second_store_path, headers=second_headers)
    assert second_store.status_code == 200
    assert second_store.json()["name"] == "second-shop Store"
    assert second_store.json()["is_published"] is False


def test_owner_store_list_requires_auth_and_is_tenant_scoped(client):
    first = register_owner(client, "first@example.com", "first-shop").json()
    second = register_owner(client, "second@example.com", "second-shop").json()

    assert client.get("/api/owner/stores").status_code == 401
    first_stores = client.get(
        "/api/owner/stores", headers=auth_header(first["access_token"])
    )
    second_stores = client.get(
        "/api/owner/stores", headers=auth_header(second["access_token"])
    )

    assert first_stores.status_code == second_stores.status_code == 200
    assert [store["slug"] for store in first_stores.json()] == ["first-shop"]
    assert [store["slug"] for store in second_stores.json()] == ["second-shop"]


def test_public_routes_hide_unpublished_stores_and_follow_owner_publication(client):
    demo_store = client.get("/api/stores/littlemarket-demo-2")
    demo_products = client.get("/api/stores/littlemarket-demo-2/products")
    assert demo_store.status_code == 200
    assert demo_products.status_code == 200
    assert len(demo_products.json()) == 4

    registration = register_owner(client, "publisher@example.com", "publisher-shop").json()
    headers = auth_header(registration["access_token"])
    assert client.get("/api/stores/publisher-shop").status_code == 404
    assert client.get("/api/stores/publisher-shop/products").status_code == 404

    publish = client.patch(
        "/api/owner/stores/publisher-shop",
        headers=headers,
        json={"is_published": True},
    )
    assert publish.status_code == 200
    assert publish.json()["is_published"] is True
    assert client.get("/api/stores/publisher-shop").status_code == 200
    assert client.get("/api/stores/publisher-shop/products").status_code == 200

    unpublish = client.patch(
        "/api/owner/stores/publisher-shop",
        headers=headers,
        json={"is_published": False},
    )
    assert unpublish.status_code == 200
    assert unpublish.json()["is_published"] is False
    assert client.get("/api/stores/publisher-shop").status_code == 404
    assert client.get("/api/stores/publisher-shop/products").status_code == 404


def test_legacy_migration_is_non_destructive_and_repeatable(tmp_path, monkeypatch):
    database_path = tmp_path / "legacy.sqlite3"
    monkeypatch.setenv("STOREFRONT_DATABASE_PATH", str(database_path))
    connection = sqlite3.connect(database_path)
    try:
        connection.executescript(
            """
            CREATE TABLE stores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                logo_url TEXT
            );
            CREATE TABLE products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                price REAL NOT NULL CHECK (price >= 0),
                original_price REAL,
                stock INTEGER NOT NULL DEFAULT 0,
                image_url TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (store_id) REFERENCES stores(id) ON DELETE CASCADE,
                UNIQUE (store_id, name)
            );
            INSERT INTO stores (id, slug, name, description, logo_url)
            VALUES (77, 'littlemarket-demo-2', 'Legacy Little Market', 'Keep this description', NULL);
            """
        )
        legacy_products = [
            (501, 77, "Woven Market Tote", "Legacy Accessories", 701, 901, 3, "legacy://tote", "Keep tote"),
            (502, 77, "Stoneware Coffee Mug", "Legacy Home", 702, None, 4, "legacy://mug", "Keep mug"),
            (503, 77, "Linen Cushion Cover", "Legacy Home", 703, 903, 5, "legacy://linen", "Keep linen"),
            (504, 77, "Botanical Soy Candle", "Legacy Wellness", 704, None, 6, "legacy://candle", "Keep candle"),
        ]
        connection.executemany(
            """
            INSERT INTO products
                (id, store_id, name, category, price, original_price, stock, image_url, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            legacy_products,
        )
        connection.commit()
    finally:
        connection.close()

    initialize_database()
    initialize_database()

    connection = sqlite3.connect(database_path)
    try:
        store = connection.execute(
            "SELECT id, slug, name, description, owner_user_id, is_published "
            "FROM stores WHERE id = 77"
        ).fetchone()
        assert store == (
            77,
            "littlemarket-demo-2",
            "Legacy Little Market",
            "Keep this description",
            None,
            1,
        )

        products = connection.execute(
            """
            SELECT id, store_id, name, category, price, original_price, stock, image_url, description
            FROM products WHERE store_id = 77 ORDER BY id
            """
        ).fetchall()
        assert products == legacy_products
        assert connection.execute("SELECT COUNT(*) FROM stores").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 4
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        assert connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall() == [(1,), (2,), (3,)]
        assert {row[1] for row in connection.execute("PRAGMA table_info(products)")} >= {
            "sku", "images_json", "variants_json", "discount_percent"
        }
        assert connection.execute("SELECT COUNT(*) FROM store_customizations").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()
