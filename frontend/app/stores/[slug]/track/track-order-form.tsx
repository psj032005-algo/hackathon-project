"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8002";

export default function TrackOrderForm({ slug }: { slug: string }) {
  const router = useRouter();
  const [orderRef, setOrderRef] = useState("");
  const [lookupCode, setLookupCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const normalizedRef = orderRef.trim();
    const normalizedCode = lookupCode.trim();
    try {
      const response = await fetch(`${API_BASE}/api/orders/track`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ order_ref: normalizedRef, lookup_code: normalizedCode }),
      });
      if (!response.ok) throw new Error("Order not found. Check the reference and lookup code.");
      sessionStorage.setItem(`store-order:${normalizedRef}`, normalizedCode);
      router.push(`/stores/${encodeURIComponent(slug)}/orders/${encodeURIComponent(normalizedRef)}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not look up this order.");
    } finally { setBusy(false); }
  }

  return <main className="min-h-screen bg-[#faf9f6] px-5 py-10 text-[#22251f] sm:px-8"><div className="mx-auto max-w-xl rounded-3xl border border-black/10 bg-white p-6 sm:p-9"><Link href={`/stores/${slug}`} className="text-sm underline">← Back to store</Link><p className="mt-7 text-xs font-semibold uppercase tracking-[0.2em] text-[#9b7753]">ORDER STATUS</p><h1 className="mt-3 text-3xl font-medium">Track your order.</h1><p className="mt-3 text-sm leading-6 text-gray-600">Enter the order reference and private lookup code from your confirmation. No customer contact details are shown.</p><form onSubmit={submit} className="mt-6 space-y-4">{error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-800">{error}</p>}<label className="block text-sm font-medium">Order reference<input className="mt-2 w-full rounded-xl border border-black/15 px-4 py-3 font-mono text-sm" value={orderRef} onChange={(event) => setOrderRef(event.target.value)} required minLength={12} maxLength={100} autoComplete="off" /></label><label className="block text-sm font-medium">Private lookup code<input className="mt-2 w-full rounded-xl border border-black/15 px-4 py-3 font-mono text-sm" value={lookupCode} onChange={(event) => setLookupCode(event.target.value)} required minLength={20} maxLength={100} autoComplete="off" /></label><button disabled={busy} className="rounded-full bg-[#243c30] px-6 py-3 font-semibold text-white disabled:opacity-50">{busy ? "Checking..." : "Track order"}</button></form></div></main>;
}
