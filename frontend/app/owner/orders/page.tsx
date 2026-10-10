"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { SessionExpiredError, useAuth } from "../../auth-provider";
import { FormError, inputClassName, OwnerFrame, OwnerPanel, responseError } from "../owner-ui";

type Store = { slug: string; name: string };
type OrderItem = { name: string; category: string; sku: string | null; variant: { name: string; value: string } | null; quantity: number; unit_price: number; line_total: number };
type Order = { id: number; public_ref: string; customer_name: string; customer_email: string; customer_phone: string; address_line1: string; address_line2: string; city: string; region: string; postal_code: string; country: string; delivery_notes: string; status: string; subtotal: number; created_at: string; items: OrderItem[] };
type Analytics = { total_orders: number; delivered_revenue: number; pending_revenue: number; revenue_definition: string; orders_by_status: Record<string, number>; recent_orders: { public_ref: string; customer_name: string; status: string; subtotal: number; created_at: string }[]; low_stock_products: { id: number; name: string; stock: number; sku: string | null }[]; low_stock_variants: { product_id: number; name: string; variant_name: string; variant_value: string; stock: number }[] };
const statuses = ["placed", "packed", "shipped", "delivered", "cancelled"];
const nextStatuses: Record<string, string[]> = { placed: ["packed", "cancelled"], packed: ["shipped", "cancelled"], shipped: ["delivered"], delivered: [], cancelled: [] };
const money = (value: number) => new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(value);

export default function OwnerOrdersPage() {
  const router = useRouter();
  const { ready, token, authorizedFetch } = useAuth();
  const [stores, setStores] = useState<Store[]>([]);
  const [slug, setSlug] = useState("");
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [orders, setOrders] = useState<Order[]>([]);
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => { if (ready && !token) router.replace("/owner/login"); }, [ready, token, router]);
  useEffect(() => {
    if (!ready || !token) return;
    let cancelled = false;
    authorizedFetch("/api/owner/stores").then(async (response) => { if (!response.ok) throw new Error(await responseError(response)); return response.json() as Promise<Store[]>; })
      .then((value) => { if (!cancelled) { setStores(value); setSlug((current) => value.some((store) => store.slug === current) ? current : value[0]?.slug || ""); } })
      .catch((caught) => { if (!cancelled && !(caught instanceof SessionExpiredError)) setError(caught instanceof Error ? caught.message : "Could not load stores."); });
    return () => { cancelled = true; };
  }, [ready, token, authorizedFetch]);

  const load = useCallback(async () => {
    if (!token || !slug) return;
    setLoading(true); setError("");
    try {
      const query = new URLSearchParams();
      if (filter !== "all") query.set("status", filter);
      if (search.trim()) query.set("search", search.trim());
      const [ordersResponse, analyticsResponse] = await Promise.all([
        authorizedFetch(`/api/owner/stores/${encodeURIComponent(slug)}/orders?${query}`),
        authorizedFetch(`/api/owner/stores/${encodeURIComponent(slug)}/analytics`),
      ]);
      if (!ordersResponse.ok) throw new Error(await responseError(ordersResponse));
      if (!analyticsResponse.ok) throw new Error(await responseError(analyticsResponse));
      setOrders(await ordersResponse.json()); setAnalytics(await analyticsResponse.json());
    } catch (caught) { if (!(caught instanceof SessionExpiredError)) setError(caught instanceof Error ? caught.message : "Could not load store operations."); }
    finally { setLoading(false); }
  }, [token, slug, filter, search, authorizedFetch]);

  useEffect(() => { const timer = window.setTimeout(() => { void load(); }, 200); return () => window.clearTimeout(timer); }, [load]);

  async function changeStatus(order: Order, next: string) {
    setUpdating(order.id); setError("");
    try {
      const response = await authorizedFetch(`/api/owner/stores/${encodeURIComponent(slug)}/orders/${order.id}`, { method: "PATCH", body: JSON.stringify({ status: next }) });
      if (!response.ok) throw new Error(await responseError(response));
      const updated: { notification_status?: string } = await response.json();
      setNotice(updated.notification_status === "sent" ? "Order updated and customer email sent." : updated.notification_status === "failed" ? "Order updated; customer email delivery failed." : "Order updated. Email delivery is not configured; demo status is recorded.");
      await load();
    } catch (caught) { if (!(caught instanceof SessionExpiredError)) setError(caught instanceof Error ? caught.message : "Could not update order."); }
    finally { setUpdating(null); }
  }

  if (!ready || !token) return <OwnerFrame eyebrow="ORDERS" adminNav><p className="mt-8 text-sm text-gray-500">Checking sign-in...</p></OwnerFrame>;
  return <OwnerFrame eyebrow="STORE OPERATIONS" adminNav><div className="flex flex-wrap items-end justify-between gap-4"><div><h1 className="text-4xl font-medium tracking-tight">Orders & analytics.</h1><p className="mt-2 text-sm text-gray-600">Private order and inventory data for your store.</p></div><div className="flex gap-3"><Link href="/owner/dashboard" className="rounded-full border px-4 py-2 text-sm">Dashboard</Link><Link href="/owner/products" className="rounded-full border px-4 py-2 text-sm">Products</Link></div></div>
    <div className="mt-6 max-w-md"><label className="block text-sm font-medium">Store<select className={`${inputClassName} mt-2`} value={slug} onChange={(event) => setSlug(event.target.value)}>{stores.map((store) => <option key={store.slug} value={store.slug}>{store.name}</option>)}</select></label></div>
    {error && <div className="mt-5"><FormError message={error} /></div>}{notice && <p role="status" className="mt-4 rounded-xl bg-[#eef1e9] px-4 py-3 text-sm">{notice}</p>}
    {analytics && <><div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4"><OwnerPanel title="Total orders"><p className="mt-3 text-3xl font-semibold">{analytics.total_orders}</p></OwnerPanel><OwnerPanel title="Delivered order value"><p className="mt-3 text-3xl font-semibold">{money(analytics.delivered_revenue)}</p><p className="mt-2 text-xs text-gray-500">Delivered orders only</p></OwnerPanel><OwnerPanel title="Pending order value"><p className="mt-3 text-3xl font-semibold">{money(analytics.pending_revenue)}</p><p className="mt-2 text-xs text-gray-500">Placed, packed, and shipped</p></OwnerPanel>{statuses.slice(0, 2).map((status) => <OwnerPanel key={status} title={`${status[0].toUpperCase()}${status.slice(1)} orders`}><p className="mt-3 text-3xl font-semibold">{analytics.orders_by_status[status] || 0}</p></OwnerPanel>)}</div><p className="mt-3 text-xs text-gray-500">{analytics.revenue_definition}</p><div className="mt-5 grid gap-5 lg:grid-cols-2"><OwnerPanel title="Low stock (5 or fewer)">{analytics.low_stock_products.length || analytics.low_stock_variants.length ? <ul className="mt-3 space-y-2 text-sm">{analytics.low_stock_products.map((product) => <li className="flex justify-between gap-3" key={`product-${product.id}`}><span>{product.name}</span><strong>{product.stock} left</strong></li>)}{analytics.low_stock_variants.map((variant) => <li className="flex justify-between gap-3" key={`variant-${variant.product_id}-${variant.variant_name}-${variant.variant_value}`}><span>{variant.name} · {variant.variant_name}: {variant.variant_value}</span><strong>{variant.stock} left</strong></li>)}</ul> : <p className="mt-3 text-sm text-gray-500">No low-stock products or variants.</p>}</OwnerPanel><OwnerPanel title="Recent orders"><ul className="mt-3 space-y-2 text-sm">{analytics.recent_orders.length ? analytics.recent_orders.map((order) => <li className="flex justify-between gap-3" key={order.public_ref}><span className="truncate">{order.customer_name} · {order.status}</span><strong>{money(order.subtotal)}</strong></li>) : <li className="text-gray-500">No orders yet.</li>}</ul></OwnerPanel></div></>}
    <OwnerPanel title="Order management" description="Move orders through placed → packed → shipped → delivered. Cancelling before shipment restores inventory once.">
      <div className="mt-4 grid gap-3 sm:grid-cols-[200px_1fr]"><label className="text-sm">Status filter<select className={`${inputClassName} mt-1`} value={filter} onChange={(event) => setFilter(event.target.value)}><option value="all">All statuses</option>{statuses.map((status) => <option key={status} value={status}>{status}</option>)}</select></label><label className="text-sm">Search<input className={`${inputClassName} mt-1`} placeholder="Order reference, customer, email" value={search} onChange={(event) => setSearch(event.target.value)} /></label></div>
      {loading ? <p className="mt-5 text-sm text-gray-500">Loading orders...</p> : orders.length === 0 ? <p className="mt-5 text-sm text-gray-500">No matching orders.</p> : <div className="mt-5 space-y-4">{orders.map((order) => <article key={order.id} className="rounded-2xl border border-black/10 p-4 sm:p-5"><div className="flex flex-wrap items-start justify-between gap-4"><div><p className="break-all font-mono text-xs text-gray-500">{order.public_ref}</p><h3 className="mt-1 font-semibold">{order.customer_name} · {order.status}</h3><p className="mt-1 text-sm text-gray-600">{order.customer_email} · {order.customer_phone}</p><p className="mt-1 text-sm text-gray-600">{order.address_line1}{order.address_line2 ? `, ${order.address_line2}` : ""}, {order.city}, {order.region} {order.postal_code}, {order.country}</p></div><div className="flex items-center gap-3"><strong>{money(order.subtotal)}</strong><select aria-label={`Update order ${order.public_ref}`} className="rounded-xl border px-3 py-2 text-sm" value={order.status} disabled={updating === order.id || nextStatuses[order.status]?.length === 0} onChange={(event) => void changeStatus(order, event.target.value)}><option value={order.status}>{order.status}</option>{nextStatuses[order.status]?.map((status) => <option key={status} value={status}>{status}</option>)}</select></div></div><ul className="mt-4 border-t pt-3 text-sm">{order.items.map((item, index) => <li key={`${item.name}-${index}`} className="flex justify-between gap-3 py-1"><span>{item.name}{item.variant ? ` · ${item.variant.name}: ${item.variant.value}` : ""} × {item.quantity}</span><span>{money(item.line_total)}</span></li>)}</ul><p className="mt-2 text-xs text-gray-500">Placed {new Date(order.created_at + (order.created_at.endsWith("Z") ? "" : "Z")).toLocaleString()}{order.delivery_notes ? ` · Note: ${order.delivery_notes}` : ""}</p></article>)}</div>}
    </OwnerPanel>
  </OwnerFrame>;
}
