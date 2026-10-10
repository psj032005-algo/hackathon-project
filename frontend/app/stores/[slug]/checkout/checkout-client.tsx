"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8002";
type CartLine = { product_id: number; quantity: number; variant_name?: string; variant_value?: string };
type Product = { id: number; name: string; price: number; discount_percent: number | null; stock: number; variants: { name: string; value: string; price_adjustment: number; stock: number }[] };
type CheckoutResult = { order_ref: string; lookup_code: string | null; subtotal: number; replayed: boolean; payment: string };
const cartKey = (slug: string) => `store-cart:${slug}`;
const checkoutKey = (slug: string) => `store-checkout-key:${slug}`;
const money = (value: number) => new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(value);

export default function Checkout({ slug }: { slug: string }) {
  const router = useRouter();
  const [cart, setCart] = useState<CartLine[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [ready, setReady] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ customer_name: "", customer_email: "", customer_phone: "", address_line1: "", address_line2: "", city: "", region: "", postal_code: "", country: "India", delivery_notes: "" });

  useEffect(() => {
    const timer = window.setTimeout(() => {
      try { const saved = JSON.parse(sessionStorage.getItem(cartKey(slug)) || "[]"); if (Array.isArray(saved)) setCart(saved); }
      catch { sessionStorage.removeItem(cartKey(slug)); }
      setReady(true);
    }, 0);
    fetch(`${API_BASE}/api/stores/${encodeURIComponent(slug)}/products`, { cache: "no-store" }).then((response) => response.ok ? response.json() : []).then((value: Product[]) => setProducts(value)).catch(() => setProducts([]));
    return () => window.clearTimeout(timer);
  }, [slug]);

  const subtotal = cart.reduce((sum, line) => {
    const product = products.find((item) => item.id === line.product_id);
    const variant = product?.variants?.find((item) => item.name === line.variant_name && item.value === line.variant_value);
    return product ? sum + (product.price + Number(variant?.price_adjustment || 0)) * (1 - Number(product.discount_percent || 0) / 100) * line.quantity : sum;
  }, 0);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSubmitting(true); setError("");
    try {
      const idempotencyKey = sessionStorage.getItem(checkoutKey(slug)) || crypto.randomUUID();
      sessionStorage.setItem(checkoutKey(slug), idempotencyKey);
      const response = await fetch(`${API_BASE}/api/stores/${encodeURIComponent(slug)}/checkout`, {
        method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
        body: JSON.stringify({ ...form, items: cart }),
      });
      const body = await response.json();
      if (!response.ok) {
        const detail = typeof body.detail === "string" ? body.detail : Array.isArray(body.detail) ? body.detail.map((item: { msg?: string }) => item.msg).filter(Boolean).join(" ") : "Checkout could not be completed.";
        throw new Error(detail);
      }
      const result = body as CheckoutResult;
      if (result.lookup_code) sessionStorage.setItem(`store-order:${result.order_ref}`, result.lookup_code);
      sessionStorage.removeItem(cartKey(slug));
      sessionStorage.removeItem(checkoutKey(slug));
      router.push(`/stores/${encodeURIComponent(slug)}/orders/${encodeURIComponent(result.order_ref)}`);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Checkout could not be completed. Please try again."); }
    finally { setSubmitting(false); }
  }

  return <main className="min-h-screen bg-[#faf9f6] px-5 py-8 text-[#22251f] sm:px-8 sm:py-12"><div className="mx-auto max-w-5xl"><Link href={`/stores/${slug}`} className="text-sm underline">← Continue shopping</Link><h1 className="mt-5 text-4xl font-medium">Checkout</h1><p className="mt-2 text-sm text-gray-600">Demo checkout only. No payment is collected or processed.</p>{!ready ? <p className="mt-8">Loading your bag...</p> : cart.length === 0 ? <div className="mt-8 rounded-3xl bg-white p-8"><p>Your bag is empty.</p><Link href={`/stores/${slug}`} className="mt-4 inline-block underline">Browse products</Link></div> : <div className="mt-7 grid gap-6 lg:grid-cols-[1.3fr_0.7fr]"><form onSubmit={submit} className="space-y-5 rounded-3xl border border-black/10 bg-white p-6 sm:p-8">{error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-800">{error}</p>}<h2 className="text-xl font-semibold">Delivery details</h2><div className="grid gap-4 sm:grid-cols-2">{([["customer_name", "Full name", "text"], ["customer_email", "Email", "email"], ["customer_phone", "Phone", "tel"], ["address_line1", "Address", "text"], ["address_line2", "Apartment / unit (optional)", "text"], ["city", "City", "text"], ["region", "State / region", "text"], ["postal_code", "Postal code", "text"], ["country", "Country", "text"]] as const).map(([field, label, type]) => <label className="block" key={field}><span className="mb-2 block text-sm font-medium">{label}</span><input required={!field.endsWith("2")} type={type} maxLength={field === "address_line1" || field === "address_line2" ? 200 : 120} className="w-full rounded-xl border border-black/15 px-4 py-3 text-sm" value={form[field]} onChange={(event) => setForm((old) => ({ ...old, [field]: event.target.value }))} /></label>)}</div><label className="block"><span className="mb-2 block text-sm font-medium">Delivery notes (optional)</span><textarea maxLength={500} className="w-full rounded-xl border border-black/15 px-4 py-3 text-sm" value={form.delivery_notes} onChange={(event) => setForm((old) => ({ ...old, delivery_notes: event.target.value }))} /></label><button disabled={submitting} className="rounded-full bg-[#243c30] px-6 py-3 font-semibold text-white disabled:opacity-50">{submitting ? "Placing order..." : "Place demo order"}</button></form><aside className="h-fit rounded-3xl border border-black/10 bg-white p-6"><h2 className="text-xl font-semibold">Order summary</h2><div className="mt-4 space-y-3">{cart.map((line, index) => { const product = products.find((item) => item.id === line.product_id); const variant = product?.variants?.find((item) => item.name === line.variant_name && item.value === line.variant_value); return <div key={`${line.product_id}-${line.variant_value}-${index}`} className="flex justify-between gap-3 text-sm"><span>{product?.name || `Product ${line.product_id}`}{variant ? ` · ${variant.value}` : ""} × {line.quantity}</span><span>{product ? money((product.price + Number(variant?.price_adjustment || 0)) * (1 - Number(product.discount_percent || 0) / 100) * line.quantity) : "—"}</span></div>; })}</div><p className="mt-5 border-t pt-4 font-semibold">Estimated subtotal <span className="float-right">{money(subtotal)}</span></p><p className="mt-3 text-xs leading-5 text-gray-500">The server checks current stock and calculates the final amount from store data before placing your order.</p></aside></div>}</div></main>;
}
