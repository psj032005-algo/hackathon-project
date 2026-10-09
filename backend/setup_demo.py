
import json
import urllib.request
import urllib.error
import getpass

BASE = "http://127.0.0.1:8001"

def request(path, method="GET", data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        BASE + path, data=body, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req) as response:
            raw = response.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            detail = json.loads(raw)
        except Exception:
            detail = raw
        raise RuntimeError(f"{method} {path}: HTTP {e.code}: {detail}")

def main():
    email = input("Demo owner email: ").strip()
    password = getpass.getpass("Password (at least 8 characters): ")

    # Register first; if the account already exists, log in instead.
    try:
        result = request(
            "/api/auth/register", "POST",
            {"email": email, "password": password}
        )
        print("Registration response:", result)
    except RuntimeError as e:
        print("Registration not completed; trying login.")

    result = request(
        "/api/auth/login", "POST",
        {"email": email, "password": password}
    )
    token = result.get("access_token") or result.get("token")
    if not token:
        print("Login response:", result)
        raise RuntimeError("Could not find an access token in login response.")

    print("Login successful.")

    slug = "littlemarket-demo"
    try:
        store = request(
            "/api/stores", "POST",
            {
                "store_name": "Littlemarket Demo",
                "slug": slug,
                "business_type": "Lifestyle",
                "theme": "minimal_luxe"
            },
            token
        )
        print("Store created:", store)
    except RuntimeError as e:
        print("Store creation response:", e)
        print("Checking whether this store already exists.")
        try:
            store = request(f"/api/stores/{slug}")
            print("Existing store:", store)
        except RuntimeError:
            raise RuntimeError(
                "Could not create or find the demo store. "
                "Check whether this owner already has a store."
            )

    products = [
        {
            "name": "Everyday Tote Bag", "price": 799, "original_price": 999,
            "stock": 18, "category": "Accessories",
            "description": "A versatile everyday bag with a clean, minimal look.",
            "image_url": "https://images.unsplash.com/photo-1544816155-12df9643f363?auto=format&fit=crop&w=700&q=85",
            "status": "published"
        },
        {
            "name": "Classic Ceramic Mug", "price": 399, "original_price": 499,
            "stock": 25, "category": "Home",
            "description": "A simple ceramic mug for your favourite daily drink.",
            "image_url": "https://images.unsplash.com/photo-1514228742587-6b1558fcca3d?auto=format&fit=crop&w=700&q=85",
            "status": "published"
        },
        {
            "name": "Minimal Wrist Watch", "price": 1499, "original_price": 1899,
            "stock": 7, "category": "Accessories",
            "description": "A timeless watch with an understated modern design.",
            "image_url": "https://images.unsplash.com/photo-1523275335684-37898b6baf30?auto=format&fit=crop&w=700&q=85",
            "status": "published"
        },
        {
            "name": "Daily Skincare Set", "price": 999, "original_price": 999,
            "stock": 12, "category": "Beauty",
            "description": "A simple self-care set for your everyday routine.",
            "image_url": "https://images.unsplash.com/photo-1608248543803-ba4f8c70ae0b?auto=format&fit=crop&w=700&q=85",
            "status": "published"
        },
        {
            "name": "Classic Sneakers", "price": 1799, "original_price": 2299,
            "stock": 0, "category": "Fashion",
            "description": "Comfortable everyday sneakers with a bold silhouette.",
            "image_url": "https://images.unsplash.com/photo-1542291026-7eec264c27ff?auto=format&fit=crop&w=700&q=85",
            "status": "published"
        },
        {
            "name": "Desk Plant Pot", "price": 549, "original_price": 699,
            "stock": 9, "category": "Home",
            "description": "Bring a little greenery to your desk or living space.",
            "image_url": "https://images.unsplash.com/photo-1485955900006-10f4d324d411?auto=format&fit=crop&w=700&q=85",
            "status": "published"
        }
    ]

    # Check existing admin products to avoid inserting duplicates.
    existing = request("/api/admin/products", token=token)
    if isinstance(existing, dict):
        existing = existing.get("products", existing.get("items", []))
    existing_names = {
        p.get("name") for p in existing if isinstance(p, dict)
    } if isinstance(existing, list) else set()

    for product in products:
        if product["name"] in existing_names:
            print("Already exists; skipping:", product["name"])
            continue
        try:
            created = request(
                "/api/admin/products", "POST", product, token
            )
            print("Created product:", product["name"], created)
        except RuntimeError as e:
            print("PRODUCT ERROR:", e)
            raise

    try:
        published = request(
            f"/api/stores/{slug}/publish", "POST", {}, token
        )
        print("Publish response:", published)
    except RuntimeError as e:
        print("PUBLISH ERROR:", e)
        raise

    print("\nPublic store check:")
    print(json.dumps(request(f"/api/stores/{slug}"), indent=2))
    print("\nPublic products check:")
    print(json.dumps(request(f"/api/stores/{slug}/products"), indent=2))
    print("\nStore slug:", slug)

if __name__ == "__main__":
    main()
