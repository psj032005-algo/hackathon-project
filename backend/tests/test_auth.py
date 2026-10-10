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


def step_three_registration_payload(email="step-three@example.com", slug="step-three-shop"):
    """Mirror the complete payload submitted by the owner registration form."""
    return {
        "email": email,
        "password": "a-strong-test-password",
        "store_name": "Step Three Shop",
        "store_slug": slug,
        "business_type": "Home goods",
        "address_line1": "12 Market Lane",
        "address_line2": "Suite 2",
        "city": "Pune",
        "region": "Maharashtra",
        "postal_code": "411001",
        "country": "India",
        "contact_email": "shop@example.com",
        "contact_phone": "+91 555 0100",
    }


def test_step_three_registration_persists_store_and_owner_can_sign_in(client):
    payload = step_three_registration_payload()
    registered = client.post("/api/auth/register", json=payload)
    assert registered.status_code == 201
    assert registered.json()["store"] == {
        "slug": "step-three-shop",
        "name": "Step Three Shop",
        "is_published": False,
    }

    signed_in = client.post("/api/auth/login", json={
        "email": payload["email"], "password": payload["password"],
    })
    assert signed_in.status_code == 200
    headers = auth_header(signed_in.json()["access_token"])
    store = client.get("/api/owner/stores/step-three-shop", headers=headers)
    assert store.status_code == 200
    assert store.json()["business_type"] == "Home goods"
    assert store.json()["address_line1"] == "12 Market Lane"
    assert store.json()["contact_email"] == "shop@example.com"

    setup = client.get("/api/owner/stores/step-three-shop/setup", headers=headers)
    assert setup.status_code == 200
    assert setup.json() == {"categories": [], "product_setup_method": None, "is_complete": False}


def test_registration_rejects_unknown_fields_without_creating_records(client, tmp_path):
    payload = step_three_registration_payload(email="extra@example.com", slug="extra-shop")
    payload["onboarding_data"] = {"categories": ["Home"]}
    response = client.post("/api/auth/register", json=payload)

    assert response.status_code == 422
    rejected = [issue for issue in response.json()["detail"] if issue["type"] == "extra_forbidden"]
    assert [issue["loc"] for issue in rejected] == [["body", "onboarding_data"]]

    connection = sqlite3.connect(tmp_path / "isolated-test.sqlite3")
    try:
        assert connection.execute("SELECT COUNT(*) FROM users WHERE email = ?", ("extra@example.com",)).fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM stores WHERE slug = ?", ("extra-shop",)).fetchone()[0] == 0
    finally:
        connection.close()


def test_registration_duplicate_email_or_slug_creates_no_partial_records(client, tmp_path):
    assert client.post("/api/auth/register", json=step_three_registration_payload()).status_code == 201

    duplicate_email = step_three_registration_payload(email="step-three@example.com", slug="another-shop")
    duplicate_slug = step_three_registration_payload(email="another@example.com", slug="step-three-shop")
    email_response = client.post("/api/auth/register", json=duplicate_email)
    slug_response = client.post("/api/auth/register", json=duplicate_slug)
    assert email_response.status_code == slug_response.status_code == 409
    assert email_response.json()["detail"] == slug_response.json()["detail"] == "Email or store slug already exists"

    connection = sqlite3.connect(tmp_path / "isolated-test.sqlite3")
    try:
        assert connection.execute("SELECT COUNT(*) FROM users WHERE email IN (?, ?)", ("another@example.com", "step-three@example.com")).fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM stores WHERE slug IN (?, ?)", ("another-shop", "step-three-shop")).fetchone()[0] == 1
    finally:
        connection.close()


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


def test_registration_persists_validated_store_profile_and_legacy_fields_default(client):
    response = client.post("/api/auth/register", json={
        "email": "profile@example.com", "password": "a-strong-test-password",
        "store_name": "Profile Shop", "store_slug": "profile-shop",
        "business_type": "  Home goods  ", "address_line1": "  12 Market Lane ",
        "address_line2": " Suite 2 ", "city": "Pune", "region": "Maharashtra",
        "postal_code": "411001", "country": "India", "contact_email": "HELLO@EXAMPLE.COM",
        "contact_phone": "+91 555 0100",
    })
    assert response.status_code == 201
    headers = auth_header(response.json()["access_token"])
    store = client.get("/api/owner/stores/profile-shop", headers=headers).json()
    assert store["business_type"] == "Home goods"
    assert store["address_line1"] == "12 Market Lane"
    assert store["address_line2"] == "Suite 2"
    assert store["city"] == "Pune" and store["country"] == "India"
    assert store["contact_email"] == "hello@example.com"
    assert store["contact_phone"] == "+91 555 0100"

    invalid = client.post("/api/auth/register", json={
        "email": "bad-profile@example.com", "password": "a-strong-test-password",
        "store_name": "Bad Profile", "store_slug": "bad-profile", "contact_email": "not-an-email",
    })
    assert invalid.status_code == 422
    incomplete = client.post("/api/auth/register", json={
        "email": "incomplete-profile@example.com", "password": "a-strong-test-password",
        "store_name": "Incomplete", "store_slug": "incomplete-profile", "business_type": "Other",
    })
    assert incomplete.status_code == 422
    invalid_phone = client.post("/api/auth/register", json={
        "email": "invalid-phone@example.com", "password": "a-strong-test-password",
        "store_name": "Invalid Phone", "store_slug": "invalid-phone",
        "business_type": "Retail", "address_line1": "1 Main St", "city": "Pune",
        "region": "MH", "postal_code": "411001", "country": "India",
        "contact_phone": "call-me-at-555",
    })
    assert invalid_phone.status_code == 422


def test_store_profile_updates_are_owner_scoped_and_contact_is_public(client):
    first = register_owner(client, "profile-one@example.com", "profile-one").json()
    second = register_owner(client, "profile-two@example.com", "profile-two").json()
    first_headers = auth_header(first["access_token"])
    second_headers = auth_header(second["access_token"])
    changed = client.patch("/api/owner/stores/profile-one", headers=first_headers, json={
        "business_type": "Wellness", "address_line1": "18 River Road", "city": "Jaipur",
        "contact_email": "shop@example.com", "contact_phone": "+91 555 2222",
    })
    assert changed.status_code == 200
    assert changed.json()["business_type"] == "Wellness"
    assert changed.json()["contact_email"] == "shop@example.com"
    assert client.patch("/api/owner/stores/profile-one", headers=second_headers, json={"city": "Other"}).status_code == 404
    assert client.patch("/api/owner/stores/profile-one", headers=first_headers, json={"contact_email": "bad"}).status_code == 422
    assert client.patch("/api/owner/stores/profile-one", headers=first_headers, json={"is_published": True}).status_code == 200
    public = client.get("/api/stores/profile-one").json()
    assert public["customization"]["contact_email"] == "shop@example.com"
    contact_only = client.patch("/api/owner/stores/profile-one", headers=first_headers, json={"contact_email": "new@example.com"})
    assert contact_only.status_code == 200 and contact_only.json()["contact_email"] == "new@example.com"
    assert client.patch("/api/owner/stores/profile-one", headers=first_headers, json={"business_type": "  "}).status_code == 422
    assert client.patch("/api/owner/stores/profile-one", headers=first_headers, json={"city": None}).status_code == 422
    assert client.patch("/api/owner/stores/profile-one", headers=first_headers, json={"logo_url": "javascript:alert(1)"}).status_code == 422
    assert client.patch("/api/owner/stores/profile-one", headers=first_headers, json={"contact_phone": "phone-me"}).status_code == 422


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


def test_staff_membership_is_store_scoped_and_cannot_manage_owner_settings(client):
    first = register_owner(client, "staff-owner@example.com", "staff-shop").json()
    staff = register_owner(client, "staff-user@example.com", "staff-users-shop").json()
    first_headers = auth_header(first["access_token"])
    staff_headers = auth_header(staff["access_token"])
    staff_user = client.post("/api/owner/stores/staff-shop/staff", headers=first_headers, json={"email": "staff-user@example.com"})
    assert staff_user.status_code == 201 and staff_user.json()["role"] == "staff"
    listed = {row["slug"]: row["role"] for row in client.get("/api/owner/stores", headers=staff_headers).json()}
    assert listed == {"staff-shop": "staff", "staff-users-shop": "owner"}
    assert client.get("/api/owner/stores/staff-shop/products", headers=staff_headers).status_code == 200
    assert client.post("/api/owner/stores/staff-shop/categories", headers=staff_headers, json={"name": "Staff Shelf"}).status_code == 201
    staff_product = client.post("/api/owner/stores/staff-shop/products", headers=staff_headers, json={
        "name": "Staff Added Mug", "category": "Home", "price": 12, "stock": 4,
    })
    assert staff_product.status_code == 201
    assert client.put(f"/api/owner/stores/staff-shop/products/{staff_product.json()['id']}", headers=staff_headers, json={
        "name": "Staff Edited Mug", "category": "Home", "price": 12, "stock": 4,
    }).status_code == 200
    assert client.get("/api/owner/stores/staff-shop/customization", headers=staff_headers).status_code == 404
    assert client.patch("/api/owner/stores/staff-shop", headers=staff_headers, json={"is_published": True}).status_code == 404
    assert client.post("/api/owner/stores/staff-shop/staff", headers=staff_headers, json={"email": "staff-owner@example.com"}).status_code == 404
    assert client.delete(f"/api/owner/stores/staff-shop/staff/{staff_user.json()['user_id']}", headers=staff_headers).status_code == 404
    assert client.patch("/api/owner/stores/staff-shop/customization", headers=staff_headers, json={"theme_id": "studio"}).status_code == 404
    assert client.get("/api/owner/stores/staff-users-shop/products", headers=staff_headers).status_code == 200
    assert client.put(f"/api/owner/stores/staff-users-shop/products/{staff_product.json()['id']}", headers=staff_headers, json={
        "name": "Cross Tenant Edit", "category": "Home", "price": 1, "stock": 0,
    }).status_code == 404
    assert client.patch("/api/owner/stores/staff-shop", headers=staff_headers, json={"name": "Hijack"}).status_code == 404
    assert client.delete("/api/owner/stores/staff-shop/staff/99999", headers=first_headers).status_code == 404
    assert client.delete(f"/api/owner/stores/staff-shop/staff/{staff_user.json()['user_id']}", headers=first_headers).status_code == 204
    assert client.get("/api/owner/stores/staff-shop/products", headers=staff_headers).status_code == 404


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
                id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', logo_url TEXT
            );
            CREATE TABLE products (
                id INTEGER PRIMARY KEY AUTOINCREMENT, store_id INTEGER NOT NULL,
                name TEXT NOT NULL, category TEXT NOT NULL, price REAL NOT NULL CHECK (price >= 0),
                original_price REAL, stock INTEGER NOT NULL DEFAULT 0,
                image_url TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
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
            """INSERT INTO products
               (id, store_id, name, category, price, original_price, stock, image_url, description)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            legacy_products,
        )
        connection.commit()
    finally:
        connection.close()

    initialize_database()
    initialize_database()
    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute(
            "SELECT id, slug, name, description, owner_user_id, is_published FROM stores WHERE id = 77"
        ).fetchone() == (77, "littlemarket-demo-2", "Legacy Little Market", "Keep this description", None, 1)
        assert connection.execute(
            "SELECT id, store_id, name, category, price, original_price, stock, image_url, description FROM products WHERE store_id = 77 ORDER BY id"
        ).fetchall() == legacy_products
        assert connection.execute("SELECT COUNT(*) FROM stores").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 4
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        assert connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall() == [(1,), (2,), (3,), (4,), (5,), (6,), (7,)]
        store_columns = {row[1] for row in connection.execute("PRAGMA table_info(stores)")}
        assert {"business_type", "address_line1", "contact_email", "contact_phone"} <= store_columns
        assert connection.execute("SELECT business_type, address_line1 FROM stores WHERE id = 77").fetchone() == ("Other", "")
        assert {row[1] for row in connection.execute("PRAGMA table_info(products)")} >= {"sku", "images_json", "variants_json", "discount_percent"}
        assert connection.execute("SELECT COUNT(*) FROM store_customizations").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM store_memberships").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM notification_attempts").fetchone()[0] == 0
        assert connection.execute("SELECT is_complete FROM store_onboarding WHERE store_id = 77").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM store_category_selections WHERE store_id = 77").fetchone()[0] >= 6
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


def test_membership_migration_backfills_only_explicit_owners(tmp_path, monkeypatch):
    database_path = tmp_path / "owner-migration.sqlite3"
    monkeypatch.setenv("STOREFRONT_DATABASE_PATH", str(database_path))
    connection = sqlite3.connect(database_path)
    try:
        connection.executescript(
            """CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT UNIQUE, password_hash TEXT NOT NULL);
               CREATE TABLE stores (id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
                 description TEXT NOT NULL DEFAULT '', logo_url TEXT, owner_user_id INTEGER);
               INSERT INTO users (id, email, password_hash) VALUES (7, 'kept@example.test', 'existing-hash');
               INSERT INTO stores (id, slug, name, owner_user_id) VALUES (88, 'kept-shop', 'Kept Shop', 7);"""
        )
        connection.commit()
    finally:
        connection.close()
    initialize_database()
    initialize_database()
    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute("SELECT store_id, user_id, role FROM store_memberships").fetchall() == [(88, 7, "owner")]
        assert connection.execute("SELECT owner_user_id FROM stores WHERE slug = 'littlemarket-demo-2'").fetchone() == (None,)
        assert connection.execute("SELECT email, password_hash FROM users WHERE id = 7").fetchone() == ("kept@example.test", "existing-hash")
    finally:
        connection.close()
