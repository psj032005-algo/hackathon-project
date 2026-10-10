"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, type CSSProperties } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8002";
type Customization = { theme_id: "market" | "botanical" | "studio" | "midnight"; primary_color: string; accent_color: string; background_color: string; font_family: "sans" | "serif" | "mono"; banner_url: string | null; homepage_sections: string[]; footer_text: string; contact_email: string; contact_phone: string; shipping_policy: string; returns_policy: string };
type Store = { slug: string; name: string; description: string; logo_url: string | null; customization: Customization };
type Variant = { name: string; value: string; price_adjustment: number; stock: number };
type Product = { id: number; name: string; category: string; price: number; original_price: number | null; discount_percent: number | null; stock: number; image_url: string; images: string[]; variants: Variant[]; description: string };
type CartLine = { product_id: number; quantity: number; variant_name?: string; variant_value?: string };
const money = (value: number) => new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(value);
const effectivePrice = (product: Product) => product.price * (1 - Number(product.discount_percent || 0) / 100);
const isAvailable = (product: Product) => product.stock > 0 && (!product.variants?.length || product.variants.some((variant) => variant.stock > 0));
const cartKey = (slug: string) => `store-cart:${slug}`;
const lineKey = (line: CartLine) => `${line.product_id}:${line.variant_name || ""}:${line.variant_value || ""}`;

export default function PublicStorePage({ slug }: { slug: string }) {
  const [store, setStore] = useState<Store | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("All");
  const [sort, setSort] = useState("featured");
  const [inStockOnly, setInStockOnly] = useState(false);
  const [cart, setCart] = useState<Record<string, CartLine>>({});
  const [cartReady, setCartReady] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [chatOpen, setChatOpen] = useState(false);
  const [chatMessage, setChatMessage] = useState("");
  const [chatReply, setChatReply] = useState("");
  const [chatEvidence, setChatEvidence] = useState("");
  const [chatBusy, setChatBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true); setError("");
      try {
        const [storeResponse, productResponse] = await Promise.all([
          fetch(API_BASE + "/api/stores/" + encodeURIComponent(slug), { cache: "no-store" }),
          fetch(API_BASE + "/api/stores/" + encodeURIComponent(slug) + "/products", { cache: "no-store" }),
        ]);
        if (!storeResponse.ok || !productResponse.ok) throw new Error("This storefront is not available.");
        const storeData: Store = await storeResponse.json();
        const productData: Product[] = await productResponse.json();
        if (!cancelled) { setStore(storeData); setProducts(productData); }
      } catch (caught) { if (!cancelled) setError(caught instanceof Error ? caught.message : "Could not load this storefront."); }
      finally { if (!cancelled) setLoading(false); }
    }
    void load();
    return () => { cancelled = true; };
  }, [slug]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      try {
        const saved = sessionStorage.getItem(cartKey(slug));
        if (saved) {
          const parsed = JSON.parse(saved) as CartLine[];
          if (Array.isArray(parsed)) setCart(Object.fromEntries(parsed.filter((line) => line && Number.isInteger(line.product_id) && Number.isInteger(line.quantity) && line.quantity > 0).map((line) => [lineKey(line), line])));
        }
      } catch { sessionStorage.removeItem(cartKey(slug)); }
      setCartReady(true);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [slug]);

  useEffect(() => {
    if (cartReady) sessionStorage.setItem(cartKey(slug), JSON.stringify(Object.values(cart)));
  }, [cart, cartReady, slug]);

  const categories = useMemo(() => ["All", ...Array.from(new Set(products.map((item) => item.category)))], [products]);
  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase();
    const result = products.filter((item) => (category === "All" || item.category === category) && (!inStockOnly || isAvailable(item)) && (!term || [item.name, item.category, item.description].some((value) => value.toLowerCase().includes(term))));
    if (sort === "name") result.sort((a, b) => a.name.localeCompare(b.name));
    if (sort === "price-asc") result.sort((a, b) => effectivePrice(a) - effectivePrice(b));
    if (sort === "price-desc") result.sort((a, b) => effectivePrice(b) - effectivePrice(a));
    return result;
  }, [products, query, category, sort, inStockOnly]);
  const count = Object.values(cart).reduce((sum, item) => sum + item.quantity, 0);
  const total = Object.values(cart).reduce((sum, line) => {
    const product = products.find((item) => item.id === line.product_id);
    if (!product) return sum;
    const variant = product.variants?.find((item) => item.name === line.variant_name && item.value === line.variant_value);
    const price = (product.price + Number(variant?.price_adjustment || 0)) * (1 - Number(product.discount_percent || 0) / 100);
    return sum + price * line.quantity;
  }, 0);
  const settings = store?.customization;
  const styles = {
    "--store-primary": settings?.primary_color || "#243c30",
    "--store-accent": settings?.accent_color || "#9b7753",
    "--store-surface": settings?.background_color || "#faf9f6",
    backgroundColor: settings?.background_color || "#faf9f6",
    fontFamily: settings?.font_family === "serif" ? "Georgia, serif" : settings?.font_family === "mono" ? "monospace" : "Arial, sans-serif",
  } as CSSProperties;

  function addToCart(product: Product) {
    const line: CartLine = { product_id: product.id, quantity: 1 };
    const key = lineKey(line);
    setCart((old) => ({ ...old, [key]: { ...line, quantity: Math.min(product.stock, (old[key]?.quantity || 0) + 1) } }));
  }
  function changeQuantity(key: string, quantity: number) {
    setCart((old) => {
      if (quantity < 1) { const next = { ...old }; delete next[key]; return next; }
      const line = old[key];
      const product = products.find((item) => item.id === line?.product_id);
      const variant = product?.variants?.find((item) => item.name === line?.variant_name && item.value === line?.variant_value);
      const maxStock = Math.min(product?.stock || 0, variant?.stock ?? product?.stock ?? 0);
      return { ...old, [key]: { ...line, quantity: Math.min(quantity, maxStock) } };
    });
  }
  async function askStore(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setChatBusy(true); setChatReply("");
    try {
      const response = await fetch(`${API_BASE}/api/stores/${encodeURIComponent(slug)}/chat`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: chatMessage }) });
      const body = await response.json();
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "I couldn't look that up right now.");
      setChatReply(body.answer);
      setChatEvidence(Array.isArray(body.supporting_data) && body.supporting_data.length ? JSON.stringify(body.supporting_data) : "");
    } catch (caught) { setChatReply(caught instanceof Error ? caught.message : "I couldn't look that up right now."); }
    finally { setChatBusy(false); }
  }

  if (loading) return <main className="min-h-screen grid place-items-center bg-[#faf9f6] text-gray-600">Loading storefront...</main>;
  if (error || !store) return <main className="min-h-screen grid place-items-center bg-[#faf9f6] p-6 text-center"><div><h1 className="text-3xl font-semibold">Store unavailable</h1><p className="mt-3 text-gray-600">{error || "This store could not be found."}</p><Link className="mt-5 inline-block underline" href="/">Back to Little Market</Link></div></main>;

  return <main data-store-theme={settings?.theme_id || "market"} style={styles} className="storefront-page min-h-screen text-[#22251f]">
    <div className="storefront-ribbon px-4 py-2.5 text-center text-xs font-medium tracking-wide text-white">{store.name} · Thoughtful goods for everyday life</div>
    <header className="storefront-header sticky top-0 z-20 border-b border-black/10 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-5 py-4 sm:px-8"><Link className="flex items-center gap-3 text-xl font-semibold sm:text-2xl" href={`/stores/${slug}`}>{store.logo_url && <img src={store.logo_url} alt="" className="h-10 max-w-32 object-contain" />}<span>{store.name}</span></Link><nav className="hidden gap-6 text-sm md:flex"><a href="#products">Shop all</a><a href="#story">Our story</a></nav><button className="storefront-primary rounded-full px-4 py-2 text-sm font-semibold text-white" onClick={() => document.getElementById("cart")?.scrollIntoView({ behavior: "smooth" })}>Bag ({count})</button></div>
    </header>
    {settings?.homepage_sections.includes("hero") !== false && <section className="mx-auto max-w-7xl px-5 py-10 sm:px-8 sm:py-16"><div className="storefront-hero overflow-hidden rounded-[2rem] p-7 sm:p-12" style={{ backgroundImage: settings?.banner_url ? "linear-gradient(90deg,#0009,#0001),url(" + settings.banner_url + ")" : undefined }}><p className="text-xs font-semibold uppercase tracking-[0.25em]" style={{ color: settings?.banner_url ? "white" : "var(--store-accent)" }}>A LITTLE SOMETHING SPECIAL</p><h1 className="mt-4 max-w-2xl text-4xl font-medium tracking-tight sm:text-6xl">{store.name}</h1><p className="mt-4 max-w-xl text-base leading-7">{store.description || "Thoughtful everyday finds, chosen with care."}</p><a href="#products" className="storefront-primary mt-7 inline-flex rounded-full px-6 py-3 text-sm font-semibold text-white">Explore the collection</a></div></section>}
    <section id="products" className="mx-auto max-w-7xl scroll-mt-24 px-5 py-10 sm:px-8 sm:py-14">
      <div className="flex flex-col gap-5 border-b border-black/10 pb-6 sm:flex-row sm:items-end sm:justify-between"><div><p className="text-xs font-semibold uppercase tracking-[0.2em]" style={{ color: "var(--store-accent)" }}>THE COLLECTION</p><h2 className="mt-2 text-3xl font-medium sm:text-4xl">Made for your everyday.</h2><p className="mt-2 text-sm opacity-70">{filtered.length} products</p></div><div className="grid gap-2 sm:grid-cols-2"><input className="w-full rounded-full border border-black/15 bg-white/80 px-5 py-3 text-sm" aria-label="Search products" placeholder="Search products..." value={query} onChange={(e) => setQuery(e.target.value)} /><select aria-label="Sort products" className="rounded-full border border-black/15 bg-white/80 px-4 py-3 text-sm" value={sort} onChange={(e) => setSort(e.target.value)}><option value="featured">Featured</option><option value="name">Name</option><option value="price-asc">Price: low to high</option><option value="price-desc">Price: high to low</option></select></div></div>
      {settings?.homepage_sections.includes("categories") !== false && <div className="my-6 flex gap-2 overflow-x-auto pb-2">{categories.map((item) => <button key={item} onClick={() => setCategory(item)} className={"shrink-0 rounded-full border px-4 py-2 text-sm " + (category === item ? "storefront-primary border-transparent text-white" : "bg-white/70")}>{item}</button>)}</div>}
      <label className="mb-5 flex items-center gap-2 text-sm"><input type="checkbox" checked={inStockOnly} onChange={(event) => setInStockOnly(event.target.checked)} />Show available products only</label>
      {settings?.homepage_sections.includes("featured") !== false && <div className="storefront-grid grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">{filtered.map((product) => <article className="storefront-card overflow-hidden rounded-3xl border border-black/10 bg-white/80" key={product.id}><Link href={`/stores/${slug}/products/${product.id}`} className="block"><div className="relative aspect-[4/3] bg-black/5"><img src={product.images?.[0] || product.image_url || "https://placehold.co/600x450?text=Product"} alt={product.name} className="h-full w-full object-cover" onError={(event) => { event.currentTarget.src = "https://placehold.co/600x450?text=Image+unavailable"; }} />{!isAvailable(product) && <span className="absolute left-3 top-3 rounded-full bg-white px-3 py-1 text-xs">Sold out</span>}</div></Link><div className="p-5"><p className="text-xs uppercase tracking-wide opacity-60">{product.category}</p><Link href={`/stores/${slug}/products/${product.id}`}><h3 className="mt-2 text-lg font-semibold">{product.name}</h3></Link><p className="mt-2 min-h-10 text-sm leading-5 opacity-70">{product.description}</p><div className="mt-4 flex items-center justify-between gap-3"><span className="font-semibold">{money(effectivePrice(product))}{product.original_price && <del className="ml-2 text-xs font-normal opacity-60">{money(product.original_price)}</del>}</span>{product.variants?.length ? <Link href={`/stores/${slug}/products/${product.id}`} className="storefront-primary rounded-full px-4 py-2 text-xs font-semibold text-white">Choose options</Link> : <button disabled={product.stock <= (cart[`${product.id}::`]?.quantity || 0)} onClick={() => addToCart(product)} className="storefront-primary rounded-full px-4 py-2 text-xs font-semibold text-white disabled:opacity-40">{product.stock === 0 ? "Unavailable" : "Add to bag"}</button>}</div></div></article>)}</div>}
      {!filtered.length && <p className="rounded-3xl border border-dashed border-black/20 py-16 text-center text-sm opacity-70">No products found. Try another search or category.</p>}
    </section>
    <section id="story" className="mx-auto max-w-7xl px-5 py-8 sm:px-8"><div className="rounded-3xl bg-black/5 p-6 sm:p-9"><h2 className="text-2xl font-semibold">A little about us</h2><p className="mt-3 max-w-2xl text-sm leading-6 opacity-75">{store.description || "Thoughtful everyday essentials, selected with care."}</p></div></section>
    <section id="cart" className="mx-auto max-w-7xl px-5 py-8 sm:px-8"><div className="rounded-3xl border border-black/10 bg-white/70 p-6"><h2 className="text-xl font-semibold">Your bag · {count} items</h2>{count ? <><div className="mt-3 space-y-3">{Object.entries(cart).map(([key, line]) => { const item = products.find((product) => product.id === line.product_id); if (!item) return null; const variant = item.variants?.find((value) => value.name === line.variant_name && value.value === line.variant_value); const unit = (item.price + Number(variant?.price_adjustment || 0)) * (1 - Number(item.discount_percent || 0) / 100); return <div className="flex flex-wrap items-center justify-between gap-3 border-b border-black/5 pb-3 text-sm" key={key}><span>{item.name}{variant ? ` · ${variant.name}: ${variant.value}` : ""}</span><div className="flex items-center gap-2"><button aria-label="Decrease quantity" onClick={() => changeQuantity(key, line.quantity - 1)} className="rounded-full border px-2">−</button><span>{line.quantity}</span><button aria-label="Increase quantity" onClick={() => changeQuantity(key, line.quantity + 1)} className="rounded-full border px-2">+</button><button onClick={() => changeQuantity(key, 0)} className="ml-2 underline">Remove</button></div><span>{money(unit * line.quantity)}</span></div>; })}</div><p className="mt-4 border-t border-black/10 pt-4 font-semibold">Estimated subtotal <span className="float-right">{money(total)}</span></p><p className="mt-2 text-xs opacity-60">Final prices and stock are checked securely at checkout.</p><Link href={`/stores/${slug}/checkout`} className="storefront-primary mt-5 inline-flex rounded-full px-6 py-3 text-sm font-semibold text-white">Continue to checkout</Link></> : <p className="mt-2 text-sm opacity-70">Your bag is waiting. Add a product to get started.</p>}</div></section>
    <footer className="storefront-footer mt-8 px-5 py-10 text-white sm:px-8"><div className="mx-auto flex max-w-7xl flex-col justify-between gap-5 sm:flex-row"><div><h2 className="text-xl font-semibold">{store.name}</h2><p className="mt-2 max-w-md text-sm opacity-75">{settings?.footer_text || "Thoughtful goods, selected with care."}</p></div><div className="text-sm">{settings?.contact_email && <p>{settings.contact_email}</p>}{settings?.contact_phone && <p className="mt-1">{settings.contact_phone}</p>}<Link href={`/stores/${slug}/track`} className="mt-2 inline-block underline">Track an order</Link></div><button onClick={() => setChatOpen((old) => !old)} className="rounded-full bg-white/15 px-5 py-3 text-sm font-semibold">Ask about this store</button></div></footer>
    {chatOpen && <section className="fixed bottom-4 right-4 z-30 w-[min(24rem,calc(100vw-2rem))] rounded-3xl border border-black/10 bg-white p-5 shadow-2xl"><div className="flex items-center justify-between"><h2 className="font-semibold">Store helper</h2><button aria-label="Close chat" onClick={() => setChatOpen(false)}>×</button></div><p className="mt-1 text-xs text-gray-500">Answers use this store&apos;s product and published store information.</p><form className="mt-4 space-y-3" onSubmit={askStore}><textarea className="w-full rounded-xl border p-3 text-sm" maxLength={500} required value={chatMessage} onChange={(event) => setChatMessage(event.target.value)} placeholder="Ask about a product, price, stock, or policy" /><button className="storefront-primary rounded-full px-4 py-2 text-sm text-white" disabled={chatBusy}>{chatBusy ? "Looking..." : "Ask"}</button></form>{chatReply && <div role="status" className="mt-3 rounded-xl bg-gray-50 p-3 text-sm"><p>{chatReply}</p>{chatEvidence && <details className="mt-2 text-xs text-gray-500"><summary>Supporting store data</summary><pre className="mt-2 whitespace-pre-wrap break-words font-sans">{chatEvidence}</pre></details>}</div>}</section>}
  </main>;
}
