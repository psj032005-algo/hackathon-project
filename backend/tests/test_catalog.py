import pytest
from fastapi.testclient import TestClient

from main import app


TEST_SECRET = "test-secret-for-isolated-catalog-suite-0123456789"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STOREFRONT_DATABASE_PATH", str(tmp_path / "catalog-test.sqlite3"))
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    with TestClient(app) as test_client:
        yield test_client


def owner(client, email, slug):
    response = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "a-strong-test-password",
            "store_name": f"{slug} store",
            "store_slug": slug,
        },
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def product_payload(**overrides):
    payload = {
        "name": "Handmade Ceramic Bowl",
        "description": "A glazed bowl made in small batches.",
        "category": "Home",
        "price": 32.5,
        "original_price": 38,
        "discount_percent": 10,
        "stock": 8,
        "sku": "BOWL-001",
        "images": ["https://images.example.test/bowl.jpg"],
        "variants": [{"name": "Color", "value": "Sand", "price_adjustment": 2, "stock": 3}],
    }
    payload.update(overrides)
    return payload


def test_product_crud_filters_and_validation_are_store_scoped(client):
    first_headers = owner(client, "one@example.com", "one-shop")
    second_headers = owner(client, "two@example.com", "two-shop")
    url = "/api/owner/stores/one-shop/products"

    assert client.get(url).status_code == 401
    assert client.post(url, json=product_payload()).status_code == 401
    invalid = client.post(url, headers=first_headers, json=product_payload(price=-1, stock=-3))
    assert invalid.status_code == 422
    assert client.post(url, headers=first_headers, json=product_payload(discount_percent=101)).status_code == 422
    assert client.post(url, headers=first_headers, json=product_payload(images=["javascript:alert(1)"])).status_code == 422
    assert client.post(url, headers=first_headers, json=product_payload(variants=[{"name": "Size", "value": "XL", "stock": -1}])).status_code == 422

    created = client.post(url, headers=first_headers, json=product_payload())
    assert created.status_code == 201
    item = created.json()
    assert item["sku"] == "BOWL-001"
    assert item["images"] == ["https://images.example.test/bowl.jpg"]
    assert item["variants"][0]["value"] == "Sand"

    assert client.get(url.replace("one-shop", "two-shop"), headers=second_headers).json() == []
    assert client.get(url, headers=second_headers).status_code == 404
    assert client.get(url + "?search=BOWL-001", headers=first_headers).json()[0]["id"] == item["id"]
    assert client.get(url + "?category=Home&stock=in_stock", headers=first_headers).json()[0]["id"] == item["id"]
    assert client.get(url + "?stock=out_of_stock", headers=first_headers).json() == []

    assert client.put(
        f"{url}/{item['id']}", headers=first_headers,
        json=product_payload(name="Updated Ceramic Bowl", stock=12, sku="BOWL-001"),
    ).status_code == 200
    assert client.put(
        f"/api/owner/stores/two-shop/products/{item['id']}",
        headers=second_headers,
        json=product_payload(name="Hijacked"),
    ).status_code == 404
    assert client.delete(f"{url}/{item['id']}", headers=second_headers).status_code == 404
    assert client.get(url, headers=first_headers).json()[0]["name"] == "Updated Ceramic Bowl"
    assert client.delete(f"{url}/{item['id']}", headers=first_headers).status_code == 204
    assert client.get(url, headers=first_headers).json() == []


def test_categories_custom_categories_and_bulk_updates_are_tenant_scoped(client):
    first_headers = owner(client, "first@example.com", "first-shop")
    second_headers = owner(client, "second@example.com", "second-shop")
    first_categories = "/api/owner/stores/first-shop/categories"
    second_categories = "/api/owner/stores/second-shop/categories"

    assert client.get(first_categories).status_code == 401
    assert client.post(first_categories, headers=first_headers, json={"name": "Garden"}).status_code == 201
    assert "Garden" in [row["name"] for row in client.get(first_categories, headers=first_headers).json()]
    assert "Garden" not in [row["name"] for row in client.get(second_categories, headers=second_headers).json()]
    assert client.post(first_categories, headers=first_headers, json={"name": "Garden"}).status_code == 409

    product_url = "/api/owner/stores/first-shop/products"
    product = client.post(product_url, headers=first_headers, json=product_payload()).json()
    assert client.post(
        "/api/owner/stores/second-shop/products", headers=second_headers,
        json=product_payload(name="Invalid Category", sku="BOWL-002", category="Garden"),
    ).status_code == 422
    bulk_url = "/api/owner/stores/first-shop/products/bulk"
    mixed = client.patch(
        bulk_url, headers=first_headers,
        json={"product_ids": [product["id"], 999999], "changes": {"stock": 0}},
    )
    assert mixed.status_code == 404
    assert client.get(product_url, headers=first_headers).json()[0]["stock"] == 8
    changed = client.patch(
        bulk_url, headers=first_headers,
        json={"product_ids": [product["id"]], "changes": {"stock": 0, "category": "Garden"}},
    )
    assert changed.status_code == 200
    assert changed.json()["updated_count"] == 1
    assert client.get(product_url + "?stock=out_of_stock", headers=first_headers).json()[0]["category"] == "Garden"
    assert client.patch(
        "/api/owner/stores/second-shop/products/bulk", headers=second_headers,
        json={"product_ids": [product["id"]], "changes": {"price": 1}},
    ).status_code == 404


def test_csv_preview_confirmation_row_errors_and_duplicates(client):
    headers = owner(client, "csv@example.com", "csv-shop")
    endpoint = "/api/owner/stores/csv-shop/products/import"
    mapping = {"name": "Product Name", "category": "Type", "price": "Price", "stock": "On Hand", "sku": "SKU", "image_url": "Photo"}
    good_csv = (
        "Product Name,Type,Price,On Hand,SKU,Photo\n"
        "CSV Mug,Home,15.50,4,CSV-1,https://images.example.test/mug.jpg\n"
    )
    request = {"csv_text": good_csv, "mapping": mapping}

    assert client.post(endpoint, headers=headers, json=request).status_code == 400
    preview = client.post(endpoint + "/preview", headers=headers, json=request)
    assert preview.status_code == 200
    assert preview.json()["valid_rows"] == 1
    assert preview.json()["can_import"] is True
    assert client.get("/api/owner/stores/csv-shop/products", headers=headers).json() == []

    imported = client.post(endpoint, headers=headers, json={**request, "confirmed": True})
    assert imported.status_code == 200
    assert imported.json()["imported_count"] == 1
    products = client.get("/api/owner/stores/csv-shop/products", headers=headers).json()
    assert len(products) == 1 and products[0]["sku"] == "CSV-1"

    invalid_csv = "Product Name,Type,Price,On Hand\nBroken,Home,-4,not-a-number\n"
    invalid_request = {"csv_text": invalid_csv, "mapping": {"name": "Product Name", "category": "Type", "price": "Price", "stock": "On Hand"}}
    invalid_preview = client.post(endpoint + "/preview", headers=headers, json=invalid_request)
    assert invalid_preview.status_code == 200
    assert invalid_preview.json()["error_rows"] == 1
    assert len(invalid_preview.json()["rows"][0]["errors"]) >= 2
    rejected = client.post(endpoint, headers=headers, json={**invalid_request, "confirmed": True})
    assert rejected.status_code == 422
    assert len(client.get("/api/owner/stores/csv-shop/products", headers=headers).json()) == 1

    duplicate_csv = "Name,Category,Price\nCSV Mug,Home,18\n"
    duplicate = client.post(
        endpoint + "/preview", headers=headers,
        json={"csv_text": duplicate_csv, "mapping": {"name": "Name", "category": "Category", "price": "Price"}},
    )
    assert duplicate.json()["rows"][0]["valid"] is False
    assert any("Duplicate" in issue for issue in duplicate.json()["rows"][0]["errors"])


def test_csv_limits_malformed_files_and_import_tenant_isolation(client):
    first_headers = owner(client, "csv-one@example.com", "csv-one")
    second_headers = owner(client, "csv-two@example.com", "csv-two")
    url = "/api/owner/stores/csv-one/products/import"
    mapping = {"name": "Name", "category": "Category", "price": "Price"}
    malformed = client.post(
        url + "/preview", headers=first_headers,
        json={"csv_text": 'Name,Category,Price\n"unterminated,Home,4', "mapping": mapping},
    )
    assert malformed.status_code == 422
    too_many_rows = "Name,Category,Price\n" + "X,Home,4\n" * 1001
    limited = client.post(
        url + "/preview", headers=first_headers,
        json={"csv_text": too_many_rows, "mapping": mapping},
    )
    assert limited.status_code == 413
    too_many_bytes = "Name,Category,Price\n" + ("Boîte,Home,4\n" * 80000)
    assert client.post(
        url + "/preview", headers=first_headers,
        json={"csv_text": too_many_bytes, "mapping": mapping},
    ).status_code == 413
    assert client.post(
        url + "/preview", headers=second_headers,
        json={"csv_text": "Name,Category,Price\nOther,Home,3", "mapping": mapping},
    ).status_code == 404


def test_customization_is_validated_persistent_public_and_tenant_scoped(client):
    first_headers = owner(client, "theme-one@example.com", "theme-one")
    second_headers = owner(client, "theme-two@example.com", "theme-two")
    first_url = "/api/owner/stores/theme-one/customization"
    second_url = "/api/owner/stores/theme-two/customization"

    before = client.get(first_url, headers=first_headers)
    assert before.status_code == 200 and before.json()["theme_id"] == "market"
    changed = client.patch(
        first_url, headers=first_headers,
        json={
            "theme_id": "botanical", "primary_color": "#345678", "font_family": "serif",
            "banner_url": "https://images.example.test/banner.jpg",
            "homepage_sections": ["hero", "categories"], "footer_text": "Made with care",
            "contact_email": "hello@example.test", "contact_phone": "+1 555 123 4567",
        },
    )
    assert changed.status_code == 200
    assert client.get(first_url, headers=first_headers).json()["primary_color"] == "#345678"
    assert client.get(second_url, headers=second_headers).json()["primary_color"] != "#345678"
    assert client.patch(first_url, headers=second_headers, json={"theme_id": "midnight"}).status_code == 404
    assert client.patch(first_url, headers=first_headers, json={"primary_color": "red"}).status_code == 422
    assert client.patch(first_url, headers=first_headers, json={"banner_url": "javascript:alert(1)"}).status_code == 422
    assert client.patch(first_url, headers=first_headers, json={"arbitrary_html": "<script>"}).status_code == 422

    assert client.get("/api/stores/theme-one").status_code == 404
    assert client.patch(
        "/api/owner/stores/theme-one", headers=first_headers, json={"is_published": True}
    ).status_code == 200
    public = client.get("/api/stores/theme-one")
    assert public.status_code == 200
    assert public.json()["customization"]["theme_id"] == "botanical"
    assert public.json()["customization"]["homepage_sections"] == ["hero", "categories"]
