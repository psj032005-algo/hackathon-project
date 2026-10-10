"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8002";
type Tracking = { order_ref: string; status: string; created_at: string; items: { name: string; quantity: number; variant: { name: string; value: string } | null }[]; events: { status: string; created_at: string }[] };

export default function OrderConfirmation({ slug, orderRef }: { slug: string; orderRef: string }) {
  const [lookupCode, setLookupCode] = useState("");
  const [data, setData] = useState<Tracking | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [manualCode, setManualCode] = useState("");

  const lookup = useCallback(async (code: string) => {
    setBusy(true); setError("");
    try {
      const response = await fetch(`${API_BASE}/api/orders/track`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ order_ref: orderRef, lookup_code: code }) });
      const body = await response.json();
      if (!response.ok) throw new Error("Order could not be found. Check the reference and lookup code.");
      setData(body as Tracking);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not look up this order."); }
    finally { setBusy(false); }
  }, [orderRef]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      try { const saved = sessionStorage.getItem(`store-order:${orderRef}`); if (saved) setLookupCode(saved); }
      catch { setLookupCode(""); }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [orderRef]);

  useEffect(() => {
    if (!lookupCode) return;
    const timer = window.setTimeout(() => { void lookup(lookupCode); }, 0);
    return () => window.clearTimeout(timer);
  }, [lookupCode, lookup]);

  function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); void lookup(manualCode.trim()); }

  return <main className="min-h-screen bg-[#faf9f6] px-5 py-10 text-[#22251f] sm:px-8"><div className="mx-auto max-w-3xl rounded-3xl border border-black/10 bg-white p-6 sm:p-9"><p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#9b7753]">ORDER STATUS</p><h1 className="mt-3 text-3xl font-medium">{data ? "Your order is confirmed." : "Your order reference"}</h1><p className="mt-3 text-sm leading-6 text-gray-600">Demo checkout only. No payment was collected or processed.</p><div className="mt-5 rounded-2xl bg-[#f4f3ed] p-4"><p className="text-xs uppercase tracking-wide text-gray-500">Order reference</p><p className="mt-1 break-all font-mono text-sm">{orderRef}</p></div>{lookupCode && <div className="mt-4 rounded-2xl border border-amber-300 bg-amber-50 p-4"><p className="text-sm font-semibold">Private lookup code</p><p className="mt-2 break-all font-mono text-sm">{lookupCode}</p><p className="mt-2 text-xs text-gray-600">Save it with your order reference. It is required to look up order status later.</p></div>}{busy && <p className="mt-5 text-sm">Loading secure order status...</p>}{error && <p role="alert" className="mt-4 rounded-xl bg-red-50 p-3 text-sm text-red-800">{error}</p>}{!data && !busy && <form onSubmit={submit} className="mt-5 space-y-3"><label className="block text-sm font-medium">Lookup code<input className="mt-2 w-full rounded-xl border px-4 py-3 font-mono text-sm" value={manualCode} onChange={(event) => setManualCode(event.target.value)} required minLength={20} maxLength={100} autoComplete="off" /></label><button className="rounded-full bg-[#243c30] px-5 py-3 text-sm font-semibold text-white">Look up order</button></form>}{data && <section className="mt-6"><div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-xl font-semibold">Status: <span className="capitalize">{data.status}</span></h2><time className="text-xs text-gray-500">Placed {new Date(data.created_at + (data.created_at.endsWith("Z") ? "" : "Z")).toLocaleString()}</time></div><h3 className="mt-5 font-semibold">Items</h3><ul className="mt-2 space-y-2 text-sm">{data.items.map((item, index) => <li key={`${item.name}-${index}`}>{item.name}{item.variant ? ` · ${item.variant.name}: ${item.variant.value}` : ""} × {item.quantity}</li>)}</ul><h3 className="mt-5 font-semibold">Updates</h3><ol className="mt-2 space-y-2 text-sm">{data.events.map((event, index) => <li key={`${event.status}-${index}`} className="flex justify-between gap-4"><span className="capitalize">{event.status}</span><time className="text-gray-500">{new Date(event.created_at + (event.created_at.endsWith("Z") ? "" : "Z")).toLocaleString()}</time></li>)}</ol></section>}<Link href={`/stores/${slug}`} className="mt-7 inline-block text-sm underline">Return to store</Link></div></main>;
}
