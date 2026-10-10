"use client";
import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { SessionExpiredError, useAuth } from "../../auth-provider";
import { FormError, FormField, inputClassName, OwnerFrame, OwnerPanel, primaryButtonClassName, responseError } from "../owner-ui";

type Product = { id: number; name: string; description: string; category: string; price: number; original_price: number | null; discount_percent: number | null; stock: number; sku: string | null; images: string[]; variants: { name: string; value: string; price_adjustment: number; stock: number }[] };
type Store = { slug: string; name: string };
type Category = { name: string; is_predefined: boolean };
type Preview = { rows: { row: number; data: Record<string, unknown>; errors: string[]; valid: boolean }[]; total_rows: number; valid_rows: number; error_rows: number; can_import: boolean };
type FormValue = { name: string; description: string; category: string; price: string; original_price: string; discount_percent: string; stock: string; sku: string; images: string; variants: Product["variants"] };
const blank: FormValue = { name: "", description: "", category: "Other", price: "", original_price: "", discount_percent: "", stock: "0", sku: "", images: "", variants: [] };
const fields = [["name", "Name (required)"], ["description", "Description"], ["category", "Category (required)"], ["price", "Price (required)"], ["original_price", "Original price"], ["stock", "Stock"], ["sku", "SKU"], ["image_url", "Image URL"], ["discount_percent", "Discount percent"]];

function csvHeaders(text: string) {
  const line = text.replace(/^\uFEFF/, "").split(/\r?\n/, 1)[0] || "";
  const result: string[] = []; let part = ""; let quoted = false;
  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    if (char === '"' && quoted && line[i + 1] === '"') { part += '"'; i += 1; }
    else if (char === '"') quoted = !quoted;
    else if (char === "," && !quoted) { result.push(part.trim()); part = ""; }
    else part += char;
  }
  result.push(part.trim()); return result.filter(Boolean);
}

function downloadTemplate() {
  const text = "name,description,category,price,original_price,stock,sku,image_url,discount_percent\r\nWoven Basket,Handwoven storage basket,Home,24.99,29.99,12,BASKET-01,https://example.com/basket.jpg,";
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a"); anchor.href = url; anchor.download = "store-products-template.csv"; anchor.click(); URL.revokeObjectURL(url);
}

export default function OwnerProductsPage() {
  const { ready, token, authorizedFetch } = useAuth();
  const [stores, setStores] = useState<Store[]>([]); const [slug, setSlug] = useState("");
  const [products, setProducts] = useState<Product[]>([]); const [categories, setCategories] = useState<Category[]>([]);
  const [search, setSearch] = useState(""); const [category, setCategory] = useState(""); const [stock, setStock] = useState("all");
  const [selected, setSelected] = useState<number[]>([]); const [editing, setEditing] = useState<number | null>(null); const [form, setForm] = useState(blank);
  const [newCategory, setNewCategory] = useState(""); const [bulkStock, setBulkStock] = useState(""); const [bulkPrice, setBulkPrice] = useState("");
  const [csvText, setCsvText] = useState(""); const [csvName, setCsvName] = useState(""); const [headers, setHeaders] = useState<string[]>([]);
  const [mapping, setMapping] = useState<Record<string, string>>({}); const [preview, setPreview] = useState<Preview | null>(null);
  const [loading, setLoading] = useState(true); const [saving, setSaving] = useState(false); const [error, setError] = useState(""); const [notice, setNotice] = useState("");

  useEffect(() => {
    if (!ready || !token) return;
    let cancelled = false;
    async function loadStores() {
      try {
        const response = await authorizedFetch("/api/owner/stores");
        if (!response.ok) throw new Error(await responseError(response));
        const list: Store[] = await response.json();
        if (!cancelled) { setStores(list); setSlug((current) => list.some((item) => item.slug === current) ? current : list[0]?.slug || ""); }
      } catch (e) { if (!cancelled && !(e instanceof SessionExpiredError)) setError(e instanceof Error ? e.message : "Could not load stores."); }
    }
    void loadStores(); return () => { cancelled = true; };
  }, [ready, token, authorizedFetch]);

  const refresh = useCallback(async () => {
    if (!slug) { setProducts([]); setLoading(false); return; }
    setLoading(true); setError("");
    try {
      const params = new URLSearchParams(); if (search.trim()) params.set("search", search.trim()); if (category) params.set("category", category); if (stock !== "all") params.set("stock", stock);
      const base = "/api/owner/stores/" + encodeURIComponent(slug);
      const responses = await Promise.all([authorizedFetch(base + "/products?" + params), authorizedFetch(base + "/categories")]);
      if (!responses[0].ok) throw new Error(await responseError(responses[0]));
      if (!responses[1].ok) throw new Error(await responseError(responses[1]));
      setProducts(await responses[0].json()); setCategories(await responses[1].json()); setSelected([]);
    } catch (e) { if (!(e instanceof SessionExpiredError)) setError(e instanceof Error ? e.message : "Could not load products."); }
    finally { setLoading(false); }
  }, [slug, search, category, stock, authorizedFetch]);

  useEffect(() => {
    if (!token || !slug) return;
    const timer = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(timer);
  }, [token, slug, refresh]);

  function edit(item?: Product) {
    if (!item) { setEditing(null); setForm(blank); return; }
    setEditing(item.id);
    setForm({ name: item.name, description: item.description, category: item.category, price: String(item.price), original_price: item.original_price == null ? "" : String(item.original_price), discount_percent: item.discount_percent == null ? "" : String(item.discount_percent), stock: String(item.stock), sku: item.sku || "", images: item.images.join("\n"), variants: item.variants });
    document.getElementById("product-form")?.scrollIntoView({ behavior: "smooth" });
  }

  async function saveProduct(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setError("");
    try {
      const body = { name: form.name.trim(), description: form.description.trim(), category: form.category, price: Number(form.price), original_price: form.original_price ? Number(form.original_price) : null, discount_percent: form.discount_percent ? Number(form.discount_percent) : null, stock: Number(form.stock), sku: form.sku.trim() || null, images: form.images.split(/\r?\n/).map((s) => s.trim()).filter(Boolean), variants: form.variants };
      const url = "/api/owner/stores/" + encodeURIComponent(slug) + "/products" + (editing ? "/" + editing : "");
      const response = await authorizedFetch(url, { method: editing ? "PUT" : "POST", body: JSON.stringify(body) });
      if (!response.ok) throw new Error(await responseError(response));
      setNotice(editing ? "Product updated." : "Product created."); edit(); await refresh();
    } catch (e) { if (!(e instanceof SessionExpiredError)) setError(e instanceof Error ? e.message : "Could not save product."); }
    finally { setSaving(false); }
  }

  async function deleteProduct(item: Product) {
    if (!window.confirm("Delete " + item.name + "? This cannot be undone.")) return;
    try {
      const response = await authorizedFetch("/api/owner/stores/" + encodeURIComponent(slug) + "/products/" + item.id, { method: "DELETE" });
      if (!response.ok) throw new Error(await responseError(response));
      setNotice(item.name + " deleted."); await refresh();
    } catch (e) { if (!(e instanceof SessionExpiredError)) setError(e instanceof Error ? e.message : "Could not delete product."); }
  }

  async function addCategory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const response = await authorizedFetch("/api/owner/stores/" + encodeURIComponent(slug) + "/categories", { method: "POST", body: JSON.stringify({ name: newCategory.trim() }) });
      if (!response.ok) throw new Error(await responseError(response));
      setNewCategory(""); setNotice("Custom category added."); await refresh();
    } catch (e) { if (!(e instanceof SessionExpiredError)) setError(e instanceof Error ? e.message : "Could not add category."); }
  }

  async function bulkEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const changes: Record<string, number> = {};
    if (bulkStock !== "") changes.stock = Number(bulkStock); if (bulkPrice !== "") changes.price = Number(bulkPrice);
    if (!Object.keys(changes).length) { setError("Enter a stock quantity or price."); return; }
    try {
      const response = await authorizedFetch("/api/owner/stores/" + encodeURIComponent(slug) + "/products/bulk", { method: "PATCH", body: JSON.stringify({ product_ids: selected, changes }) });
      if (!response.ok) throw new Error(await responseError(response));
      setNotice((await response.json()).updated_count + " products updated."); setBulkStock(""); setBulkPrice(""); await refresh();
    } catch (e) { if (!(e instanceof SessionExpiredError)) setError(e instanceof Error ? e.message : "Bulk edit failed."); }
  }

  async function previewCsv() {
    try {
      const response = await authorizedFetch("/api/owner/stores/" + encodeURIComponent(slug) + "/products/import/preview", { method: "POST", body: JSON.stringify({ csv_text: csvText, mapping }) });
      if (!response.ok) throw new Error(await responseError(response)); setPreview(await response.json());
    } catch (e) { if (!(e instanceof SessionExpiredError)) setError(e instanceof Error ? e.message : "Could not preview CSV."); }
  }

  async function importCsv() {
    if (!preview?.can_import || !window.confirm("Import " + preview.total_rows + " reviewed products?")) return;
    setSaving(true);
    try {
      const response = await authorizedFetch("/api/owner/stores/" + encodeURIComponent(slug) + "/products/import", { method: "POST", body: JSON.stringify({ csv_text: csvText, mapping, confirmed: true }) });
      if (!response.ok) throw new Error(await responseError(response));
      setNotice((await response.json()).imported_count + " products imported."); setCsvText(""); setCsvName(""); setHeaders([]); setPreview(null); await refresh();
    } catch (e) { if (!(e instanceof SessionExpiredError)) setError(e instanceof Error ? e.message : "Import failed."); }
    finally { setSaving(false); }
  }

  if (!ready || !token) return <OwnerFrame eyebrow="PRODUCTS"><p className="mt-8 text-center text-sm text-gray-500">Checking your sign-in...</p></OwnerFrame>;
  return <OwnerFrame eyebrow="STORE MANAGEMENT">
    <div className="mt-5 flex flex-wrap items-end justify-between gap-4"><div><h1 className="text-4xl font-medium tracking-tight sm:text-5xl">Products & inventory.</h1><p className="mt-3 text-sm text-gray-600">Manage products, stock, categories, and CSV imports.</p></div><div className="flex gap-3"><Link className="rounded-full border px-4 py-2 text-sm" href="/owner/dashboard">Dashboard</Link><Link className="rounded-full border px-4 py-2 text-sm" href="/owner/customize">Customize storefront</Link></div></div>
    <div className="mt-6 max-w-md"><FormField label="Store"><select className={inputClassName} value={slug} onChange={(e) => setSlug(e.target.value)}>{stores.map((item) => <option key={item.slug} value={item.slug}>{item.name}</option>)}</select></FormField></div>
    {error && <div className="mt-4"><FormError message={error} /></div>}{notice && <p role="status" className="mt-4 rounded-xl bg-[#eef1e9] px-4 py-3 text-sm">{notice}</p>}
    <div className="mt-6 grid gap-6 xl:grid-cols-[1.5fr_0.9fr]"><div className="space-y-6">
      <OwnerPanel title="Product catalog" description="Search and filter products. Select rows to bulk edit stock and price.">
        <div className="mt-5 grid gap-3 sm:grid-cols-3"><input className={inputClassName} placeholder="Search name, SKU, description" value={search} onChange={(e) => setSearch(e.target.value)} /><select className={inputClassName} value={category} onChange={(e) => setCategory(e.target.value)}><option value="">All categories</option>{categories.map((c) => <option key={c.name}>{c.name}</option>)}</select><select className={inputClassName} value={stock} onChange={(e) => setStock(e.target.value)}><option value="all">Any stock</option><option value="in_stock">In stock</option><option value="low_stock">Low stock (1–5)</option><option value="out_of_stock">Out of stock</option></select></div>
        {selected.length > 0 && <form onSubmit={bulkEdit} className="mt-4 flex flex-wrap items-end gap-3 rounded-xl bg-[#f4f3ed] p-4"><span className="mr-auto pb-3">{selected.length} selected</span><label className="text-xs">Set stock<input className={inputClassName} type="number" min="0" value={bulkStock} onChange={(e) => setBulkStock(e.target.value)} /></label><label className="text-xs">Set price<input className={inputClassName} type="number" min="0.01" step="0.01" value={bulkPrice} onChange={(e) => setBulkPrice(e.target.value)} /></label><button className={primaryButtonClassName}>Apply</button></form>}
        <div className="mt-4 overflow-x-auto"><table className="w-full min-w-[620px] text-left text-sm"><thead><tr className="border-b text-xs uppercase text-gray-500"><th className="p-3"><input type="checkbox" aria-label="Select all" checked={products.length > 0 && selected.length === products.length} onChange={(e) => setSelected(e.target.checked ? products.map((p) => p.id) : [])} /></th><th className="p-3">Product</th><th className="p-3">Category</th><th className="p-3">Price</th><th className="p-3">Stock</th><th className="p-3">Actions</th></tr></thead><tbody>{loading ? <tr><td colSpan={6} className="p-5">Loading...</td></tr> : products.length === 0 ? <tr><td colSpan={6} className="p-5">No products match these filters.</td></tr> : products.map((p) => <tr className="border-b" key={p.id}><td className="p-3"><input type="checkbox" checked={selected.includes(p.id)} aria-label={"Select " + p.name} onChange={(e) => setSelected((old) => e.target.checked ? [...old, p.id] : old.filter((id) => id !== p.id))} /></td><td className="p-3"><b>{p.name}</b><p className="text-xs text-gray-500">{p.sku || "No SKU"}</p></td><td className="p-3">{p.category}</td><td className="p-3">{p.price.toFixed(2)}</td><td className="p-3">{p.stock}</td><td className="p-3"><button className="underline" onClick={() => edit(p)}>Edit</button><button className="ml-3 text-red-700 underline" onClick={() => void deleteProduct(p)}>Delete</button></td></tr>)}</tbody></table></div>
      </OwnerPanel>
      <OwnerPanel title={editing ? "Edit product" : "Add a product"} description="Image URLs must be public HTTP(S). Add options such as size or color as variants.">
        <form id="product-form" onSubmit={saveProduct} className="mt-5 grid gap-4 sm:grid-cols-2">
          <FormField label="Name"><input className={inputClassName} required maxLength={160} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></FormField><FormField label="Category"><select className={inputClassName} value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>{categories.map((c) => <option key={c.name}>{c.name}</option>)}</select></FormField>
          <FormField label="Price"><input className={inputClassName} type="number" min="0.01" step="0.01" required value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} /></FormField><FormField label="Original price"><input className={inputClassName} type="number" min="0.01" step="0.01" value={form.original_price} onChange={(e) => setForm({ ...form, original_price: e.target.value })} /></FormField>
          <FormField label="Discount %"><input className={inputClassName} type="number" min="0" max="90" value={form.discount_percent} onChange={(e) => setForm({ ...form, discount_percent: e.target.value })} /></FormField><FormField label="Stock"><input className={inputClassName} type="number" min="0" max="1000000" step="1" value={form.stock} onChange={(e) => setForm({ ...form, stock: e.target.value })} /></FormField><FormField label="SKU"><input className={inputClassName} maxLength={80} value={form.sku} onChange={(e) => setForm({ ...form, sku: e.target.value })} /></FormField><FormField label="Image URLs (one per line)"><textarea className={inputClassName} value={form.images} onChange={(e) => setForm({ ...form, images: e.target.value })} /></FormField>
          <div className="sm:col-span-2"><FormField label="Description"><textarea className={inputClassName} maxLength={4000} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></FormField></div>
          <div className="space-y-3 sm:col-span-2"><div className="flex items-center justify-between"><span className="text-sm font-medium">Variants</span><button className="text-sm font-semibold underline" type="button" onClick={() => setForm({ ...form, variants: [...form.variants, { name: "", value: "", price_adjustment: 0, stock: 0 }] })}>Add variant</button></div>{form.variants.length === 0 ? <p className="text-xs text-gray-500">No variants. Add options like size or color if needed.</p> : form.variants.map((variant, index) => <div className="grid gap-2 rounded-xl bg-[#f4f3ed] p-3 sm:grid-cols-2" key={index}><label className="text-xs">Option<input className={inputClassName} placeholder="Size" value={variant.name} onChange={(e) => setForm({ ...form, variants: form.variants.map((item, i) => i === index ? { ...item, name: e.target.value } : item) })} /></label><label className="text-xs">Value<input className={inputClassName} placeholder="Large" value={variant.value} onChange={(e) => setForm({ ...form, variants: form.variants.map((item, i) => i === index ? { ...item, value: e.target.value } : item) })} /></label><label className="text-xs">Price adjustment<input className={inputClassName} type="number" step="0.01" value={variant.price_adjustment} onChange={(e) => setForm({ ...form, variants: form.variants.map((item, i) => i === index ? { ...item, price_adjustment: Number(e.target.value) } : item) })} /></label><label className="text-xs">Variant stock<input className={inputClassName} type="number" min="0" step="1" value={variant.stock} onChange={(e) => setForm({ ...form, variants: form.variants.map((item, i) => i === index ? { ...item, stock: Number(e.target.value) } : item) })} /></label><button type="button" className="text-left text-xs text-red-700 underline sm:col-span-2" onClick={() => setForm({ ...form, variants: form.variants.filter((_, i) => i !== index) })}>Remove variant</button></div>)}</div>
          <div className="flex gap-3 sm:col-span-2"><button className={primaryButtonClassName} disabled={saving}>{saving ? "Saving..." : editing ? "Save product" : "Add product"}</button>{editing && <button type="button" className="rounded-full border px-5" onClick={() => edit()}>Cancel</button>}</div>
        </form>
      </OwnerPanel>
    </div><div className="space-y-6">
      <OwnerPanel title="Categories" description="Predefined categories plus categories belonging to this store."><form onSubmit={addCategory} className="mt-5 flex gap-2"><input className={inputClassName} required maxLength={50} placeholder="New category" value={newCategory} onChange={(e) => setNewCategory(e.target.value)} /><button className={primaryButtonClassName}>Add</button></form><div className="mt-4 flex flex-wrap gap-2">{categories.map((c) => <span key={c.name} className="rounded-full bg-[#f4f3ed] px-3 py-1.5 text-xs">{c.name}{c.is_predefined ? " · default" : ""}</span>)}</div></OwnerPanel>
      <OwnerPanel title="CSV product import" description="Review every row. Invalid or duplicate rows block importing."><button type="button" onClick={downloadTemplate} className="text-sm font-semibold underline">Download CSV template</button><p className="mt-3 text-xs leading-5">Columns: name, description, category, price, original_price, stock, sku, image_url, discount_percent. Required: name, category, price. Max 1 MB and 1,000 rows.</p><label className="mt-4 block text-sm">Choose CSV<input className="mt-2 block w-full text-sm" type="file" accept=".csv,text/csv" onChange={(e) => void (async () => { const file = e.target.files?.[0]; if (!file) return; if (file.size > 1000000) { setError("CSV is limited to 1 MB."); return; } const text = await file.text(); const cols = csvHeaders(text); const next: Record<string, string> = {}; fields.forEach(([key]) => { const found = cols.find((h) => h.toLowerCase().replaceAll(" ", "_") === key); if (found) next[key] = found; }); setCsvText(text); setCsvName(file.name); setHeaders(cols); setMapping(next); setPreview(null); })()} /></label>{csvName && <p className="mt-2 text-xs text-gray-500">{csvName}</p>}
        {headers.length > 0 && <div className="mt-4 space-y-3"><b className="text-sm">Map columns</b>{fields.map(([key, label]) => <label key={key} className="grid grid-cols-2 items-center gap-2 text-xs"><span>{label}</span><select className={inputClassName} value={mapping[key] || ""} onChange={(e) => { setPreview(null); setMapping((old) => { const next = { ...old }; if (e.target.value) next[key] = e.target.value; else delete next[key]; return next; }); }}><option value="">Not mapped</option>{headers.map((h) => <option key={h}>{h}</option>)}</select></label>)}<button type="button" className={primaryButtonClassName + " w-full"} onClick={() => void previewCsv()}>Preview and validate</button></div>}
        {preview && <div className="mt-4 rounded-xl border p-4"><p className="text-sm">{preview.total_rows} rows · {preview.valid_rows} valid · {preview.error_rows} errors</p><div className="mt-3 max-h-64 overflow-auto"><table className="w-full text-left text-xs"><tbody>{preview.rows.map((row) => <tr className="border-t align-top" key={row.row}><td className="py-2">{row.row}</td><td>{String(row.data.name || "—")}</td><td className={row.valid ? "text-emerald-700" : "text-red-700"}>{row.valid ? "Ready" : row.errors.join("; ")}</td></tr>)}</tbody></table></div><button type="button" disabled={!preview.can_import || saving} onClick={() => void importCsv()} className={primaryButtonClassName + " mt-4 w-full"}>{saving ? "Importing..." : "Confirm import " + preview.valid_rows}</button></div>}
      </OwnerPanel>
    </div></div>
  </OwnerFrame>;
}
