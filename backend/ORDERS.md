# Orders and store FAQ

Database initialization applies schema migration version 3 in a transaction. It
creates the order, item, and status-event tables and adds shipping/returns policy
text columns only when those columns are absent. Existing stores and products are
not reassigned, removed, or rewritten by this migration. Tests point
`STOREFRONT_DATABASE_PATH` at pytest temporary directories.

Checkout at `POST /api/stores/{slug}/checkout` is a demo order flow. It records a
placed order and reserves inventory, but does not charge a card or contact a
payment processor. The customer receives a random order reference and a separate
lookup code derived with HMAC-SHA256 from the configured `JWT_SECRET` and
reference. The database stores only the lookup code's SHA-256 hash, so an
idempotent retry can return the same code without storing it in plaintext.
Checkout uses an `Idempotency-Key` and a request fingerprint so a retry cannot
reserve inventory twice or reuse the key for a different request.

Owners can move an order from placed to packed or cancelled, packed to shipped or
cancelled, and shipped to delivered. Cancellation is available only before
shipment and restores product and selected-variant inventory in the same SQLite
transaction as the status change. Repeated cancellation is rejected, preventing
double restoration. Analytics counts every order and treats delivered order
value only as revenue; because checkout is demo-only, it is not payment revenue.

`POST /api/stores/{slug}/chat` is a deterministic, read-only FAQ fallback. It
queries only the requested published store's products, contact details, and
published policy text. No model provider, API key, or paid service is configured
or called. Questions without matching store data return exactly
`I don't have that data.`
