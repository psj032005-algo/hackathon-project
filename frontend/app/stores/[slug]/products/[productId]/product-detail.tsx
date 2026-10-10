"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8002";
type Variant = { name: string; value: string; price_adjustment: number; stock: number };
type Product = { id: number; name: string; description: string; category: string; price: number; original_price: number | null; discount_percent: number | null; stock: number; image_url: string; images: string[]; variants: Variant[] };
type CartLine = { product_id: number; quantity: number; variant_name?: string; variant_value?: string };
const cartKey = (slug: string) => `store-cart:${slug}`;
const money = (value: number) => new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(value);

export default function ProductDetail({ slug, productId }: { slug: string; productId: string }) {
  const [product, setProduct] = useState<Product | null>(null);
  const [variantIndex, setVariantIndex] = useState(0);
  const [quantity, setQuantity] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/api/stores/${encodeURIComponent(slug)}/products/${encodeURIComponent(productId)}`, { cache: "no-store" })
      .then(async (response) => { if (!response.ok) throw new Error(response.status === 404 ? "This product is unavailable." : "Could not load this product."); return response.json() as Promise<Product>; })
      .then((value) => { if (!cancelled) setProduct(value); })
      .catch((caught) => { if (!cancelled) setError(caught instanceof Error ? caught.message : "Could not load this product."); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [slug, productId]);

  if (loading) return <main className="min-h-screen grid place-items-center bg-[#faf9f6]">Loading product...</main>;
  if (!product) return <main className="min-h-screen bg-[#faf9f6] p-6"><div className="mx-auto max-w-3xl rounded-3xl bg-white p-8"><p role="alert">{error || "Product unavailable."}</p><Link className="mt-4 inline-block underline" href={`/stores/${slug}`}>Back to store</Link></div></main>;
  const variant = product.variants?.[variantIndex];
  const stock = Math.min(product.stock, variant?.stock ?? product.stock);
  const price = (product.price + Number(variant?.price_adjustment || 0)) * (1 - Number(product.discount_percent || 0) / 100);

  function addToBag() {
    if (!product || stock <= 0) return;
    try {
      const saved = JSON.parse(sessionStorage.getItem(cartKey(slug)) || "[]") as CartLine[];
      const line: CartLine = { product_id: product.id, quantity, ...(variant ? { variant_name: variant.name, variant_value: variant.value } : {}) };
      const same = (item: CartLine) => item.product_id === line.product_id && item.variant_name === line.variant_name && item.variant_value === line.variant_value;
      const existing = saved.find(same);
      if (existing) existing.quantity = Math.min(stock, existing.quantity + quantity);
      else saved.push(line);
      sessionStorage.setItem(cartKey(slug), JSON.stringify(saved));
      setNotice("Added to your bag.");
    } catch { setError("Could not save your bag in this browser session."); }
  }

  return <main className="min-h-screen bg-[#faf9f6] px-5 py-8 text-[#22251f] sm:px-8 sm:py-12"><div className="mx-auto max-w-6xl"><Link href={`/stores/${slug}`} className="text-sm underline underline-offset-4">← Back to store</Link><div className="mt-6 grid gap-8 rounded-[2rem] border border-black/10 bg-white/70 p-5 sm:p-8 md:grid-cols-2"><div className="aspect-square overflow-hidden rounded-3xl bg-black/5"><img src={product.images?.[0] || product.image_url || "https://placehold.co/800x800?text=Product"} alt={product.name} className="h-full w-full object-cover" onError={(event) => { event.currentTarget.src = "https://placehold.co/800x800?text=Image+unavailable"; }} /></div><section className="flex flex-col justify-center"><p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#9b7753]">{product.category}</p><h1 className="mt-3 text-3xl font-medium sm:text-4xl">{product.name}</h1><p className="mt-4 text-base leading-7 text-gray-600">{product.description || "A thoughtfully selected piece for everyday life."}</p><p className="mt-6 text-2xl font-semibold">{money(price)}{product.original_price && <del className="ml-3 text-base font-normal text-gray-500">{money(product.original_price)}</del>}</p><p className="mt-2 text-sm text-gray-600">{stock > 0 ? `${stock} available` : "Currently out of stock"}</p>{product.variants?.length > 0 && <label className="mt-6 block"><span className="mb-2 block text-sm font-medium">{product.variants[0].name}</span><select className="w-full rounded-xl border border-black/15 bg-white px-4 py-3" value={variantIndex} onChange={(event) => { setVariantIndex(Number(event.target.value)); setQuantity(1); }} aria-label={product.variants[0].name}>{product.variants.map((item, index) => <option key={`${item.name}-${item.value}`} value={index}>{item.value}{item.stock <= 0 ? " · sold out" : ""}</option>)}</select></label>}<label className="mt-5 block max-w-40"><span className="mb-2 block text-sm font-medium">Quantity</span><input className="w-full rounded-xl border border-black/15 px-4 py-3" type="number" min={1} max={stock} value={quantity} onChange={(event) => setQuantity(Math.max(1, Math.min(stock || 1, Number(event.target.value) || 1)))} /></label><button onClick={addToBag} disabled={stock <= 0} className="mt-6 rounded-full bg-[#243c30] px-6 py-3 font-semibold text-white disabled:opacity-40">{stock <= 0 ? "Unavailable" : "Add to bag"}</button>{notice && <p role="status" className="mt-3 text-sm text-emerald-800">{notice} <Link href={`/stores/${slug}`} className="underline">Continue shopping</Link></p>}{error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}</section></div></div></main>;
}
