# Orders and store FAQ

Database initialization applies additive schema migrations through version 7 in
a transaction. Version 4 adds optional store profile fields with defaults for
legacy rows. Version 5 creates owner/staff memberships and backfills only stores
whose `owner_user_id` was already set; unowned legacy stores remain unassigned.
Version 6 adds one notification attempt per status event. Version 7 adds
category selections and onboarding progress while retaining existing stores and
catalog data. Existing stores and products are not reassigned, removed, or
rewritten by these migrations. Tests point `STOREFRONT_DATABASE_PATH` at pytest
temporary directories.

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
double restoration. Owners and assigned staff can manage catalog and orders;
only owners can publish, change store settings, or manage staff. Analytics counts
every order and treats delivered order value only as realized revenue; placed,
packed, and shipped values are reported separately as pending. Because checkout
is demo-only, neither number is processed payment revenue.

Order status changes create a durable notification attempt record. Without mail
settings, the attempt is recorded as `not_configured` and the order transition
still succeeds. Optional delivery uses the Python standard-library SMTP client
with STARTTLS. Set `SMTP_HOST`, `SMTP_PORT` (default 587), `SMTP_FROM`, and, when
required by the provider, both `SMTP_USERNAME` and `SMTP_PASSWORD`. `SMTP_USE_TLS`
must be `true`; clear-text SMTP is not supported. Delivery failures store only
the generic `smtp_delivery_failed` code. Tests clear all SMTP variables and use
mock senders, so they never contact a mail server. Real email delivery has not
been verified without provider configuration.

`POST /api/stores/{slug}/chat` is a deterministic, read-only FAQ fallback. It
queries only the requested published store's products, contact details, and
published policy text. If `GEMINI_API_KEY` is configured, the backend uses the
Gemini `generateContent` API. `GEMINI_MODEL` is optional and defaults to
`gemini-3.5-flash-lite`. Gemini takes precedence when both provider keys are
configured. Otherwise, if `AI_API_KEY` and `AI_MODEL` are configured, the backend
can use the OpenAI Responses API with an optional HTTPS `AI_BASE_URL` (defaults
to the OpenAI Responses endpoint). The provider
receives only the current user's question plus bounded facts already retrieved
for the published store; it never gets database access or tools. Responses are
requested with storage disabled. The question and retrieved text remain untrusted.
Provider errors return the existing deterministic FAQ answer, and the response
marks whether it used `ai` or `faq_fallback`. Without a key, FAQ mode remains
available; unsupported or missing facts return exactly `I don't have that data.`

`POST /api/owner/stores/{slug}/chat` is separate and owner-authenticated. It uses
an allowlist of read-only intents and parameterized, store-scoped queries for top
sellers, low stock, recent orders, order totals, and seven-day delivered-revenue
comparisons. Only a fixed intent summary and aggregate evidence may be sent to
the optional provider, never the owner's raw prompt or customer personal details.
Both chat routes are rate-limited to 30 requests per minute per store and client
address in each backend process. The limit is in-memory, so deployments with
multiple workers should add a shared rate-limit store before public production.

Provider use can incur charges and questions plus bounded retrieved facts are
sent to the selected provider. Gemini uses the backend-only `GEMINI_API_KEY`
header; the key is never returned to the frontend or written to logs. The
application does not log keys, questions, provider responses, or customer
information.

Public store URLs use the path form `/stores/{slug}`. Slugs have a database
unique constraint and registration reports a conflict when a slug is taken;
the owner dashboard copies the current origin plus that path. Public deployment,
custom domains, DNS, TLS termination, and production CORS origins are not
configured here. Before deployment, set the frontend API base URL to the
deployed backend and add the exact frontend origin to FastAPI CORS settings.
