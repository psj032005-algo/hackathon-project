"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { SessionExpiredError, useAuth } from "../../auth-provider";
import { FormError, OwnerFrame, OwnerPanel, primaryButtonClassName, responseError } from "../owner-ui";

type Store = { slug: string; name: string };
type Category = { name: string; is_predefined: boolean };
type Setup = { categories: string[]; product_setup_method: "demo" | "spreadsheet" | null; is_complete: boolean };
type SamplePreview = { total_products: number; importable_count: number; skipped_count: number; products: { name: string; category: string; description: string; price: number; stock: number; image_url: string; already_exists: boolean }[] };

export default function OwnerSetupPage() {
  const router = useRouter();
  const { ready, token, authorizedFetch } = useAuth();
  const [stores, setStores] = useState<Store[]>([]);
  const [slug, setSlug] = useState("");
  const [categories, setCategories] = useState<Category[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [method, setMethod] = useState<"demo" | "spreadsheet" | "">("");
  const [step, setStep] = useState(1);
  const [preview, setPreview] = useState<SamplePreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (ready && !token) router.replace("/owner/login");
  }, [ready, token, router]);

  useEffect(() => {
    if (!ready || !token) return;
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const response = await authorizedFetch("/api/owner/stores");
        if (!response.ok) throw new Error(await responseError(response));
        const storeList: Store[] = await response.json();
        if (cancelled) return;
        setStores(storeList);
        setSlug(storeList[0]?.slug || "");
      } catch (caught) {
        if (!cancelled && !(caught instanceof SessionExpiredError)) setError(caught instanceof Error ? caught.message : "Could not load your store.");
      } finally { if (!cancelled) setLoading(false); }
    }
    void load();
    return () => { cancelled = true; };
  }, [ready, token, authorizedFetch]);

  useEffect(() => {
    if (!token || !slug) return;
    let cancelled = false;
    async function loadStoreSetup() {
      setError(""); setPreview(null);
      try {
        const [categoryResponse, setupResponse] = await Promise.all([
          authorizedFetch(`/api/owner/stores/${encodeURIComponent(slug)}/categories`),
          authorizedFetch(`/api/owner/stores/${encodeURIComponent(slug)}/setup`),
        ]);
        if (!categoryResponse.ok) throw new Error(await responseError(categoryResponse));
        if (!setupResponse.ok) throw new Error(await responseError(setupResponse));
        const available: Category[] = await categoryResponse.json();
        const saved: Setup = await setupResponse.json();
        if (!cancelled) {
          setCategories(available);
          setSelected(saved.categories);
          setMethod(saved.product_setup_method || "");
          setStep(saved.is_complete ? 1 : saved.categories.length ? 2 : 1);
        }
      } catch (caught) {
        if (!cancelled && !(caught instanceof SessionExpiredError)) setError(caught instanceof Error ? caught.message : "Could not load setup details.");
      }
    }
    void loadStoreSetup();
    return () => { cancelled = true; };
  }, [token, slug, authorizedFetch]);

  async function saveSetup(selectedCategories: string[], selectedMethod: "demo" | "spreadsheet" | null) {
    const response = await authorizedFetch(`/api/owner/stores/${encodeURIComponent(slug)}/setup`, {
      method: "PUT",
      body: JSON.stringify({ categories: selectedCategories, product_setup_method: selectedMethod }),
    });
    if (!response.ok) throw new Error(await responseError(response));
  }

  async function reviewSetup() {
    setError(""); setNotice(""); setSaving(true);
    try {
      if (!selected.length) throw new Error("Choose at least one category to continue.");
      if (!method) throw new Error("Choose how you want to add products.");
      await saveSetup(selected, method);
      if (method === "demo") {
        const response = await authorizedFetch(`/api/owner/stores/${encodeURIComponent(slug)}/products/import-samples/preview`, {
          method: "POST", body: JSON.stringify({ categories: selected }),
        });
        if (!response.ok) throw new Error(await responseError(response));
        setPreview(await response.json());
      }
      setStep(3);
    } catch (caught) {
      if (!(caught instanceof SessionExpiredError)) setError(caught instanceof Error ? caught.message : "Could not save your setup.");
    } finally { setSaving(false); }
  }

  async function finishDemoImport() {
    setError(""); setSaving(true);
    try {
      const response = await authorizedFetch(`/api/owner/stores/${encodeURIComponent(slug)}/products/import-samples`, {
        method: "POST", body: JSON.stringify({ categories: selected }),
      });
      if (!response.ok) throw new Error(await responseError(response));
      const result: { imported_count: number; skipped_count: number } = await response.json();
      const complete = await authorizedFetch(`/api/owner/stores/${encodeURIComponent(slug)}/setup/complete`, { method: "POST" });
      if (!complete.ok) throw new Error(await responseError(complete));
      setNotice(`${result.imported_count} demo products added${result.skipped_count ? `; ${result.skipped_count} existing products skipped` : ""}. Setup is complete.`);
      setTimeout(() => router.push("/owner/dashboard"), 900);
    } catch (caught) {
      if (!(caught instanceof SessionExpiredError)) setError(caught instanceof Error ? caught.message : "Could not import sample products.");
    } finally { setSaving(false); }
  }

  function continueToSpreadsheet() {
    sessionStorage.setItem(`owner-setup-import:${slug}`, "1");
    router.push("/owner/products#product-import");
  }

  if (!ready || !token) return <OwnerFrame eyebrow="STORE SETUP" adminNav><p className="mt-8 text-sm text-gray-500">Checking sign-in...</p></OwnerFrame>;
  const store = stores.find((item) => item.slug === slug);
  return <OwnerFrame eyebrow="STORE SETUP" adminNav>
    <div className="mt-5 flex flex-wrap items-end justify-between gap-4"><div><h1 className="text-4xl font-medium tracking-tight sm:text-5xl">Set up your catalog.</h1><p className="mt-3 text-sm leading-6 text-gray-600">Choose the collections your store carries, then add starter products or upload your own sheet.</p></div><Link href="/owner/dashboard" className="rounded-full border px-4 py-2 text-sm">Back to admin</Link></div>
    {stores.length > 1 && <label className="mt-6 block max-w-md text-sm font-medium">Store<select className="mt-2 w-full rounded-xl border bg-white px-4 py-3" value={slug} onChange={(event) => setSlug(event.target.value)}>{stores.map((item) => <option key={item.slug} value={item.slug}>{item.name}</option>)}</select></label>}
    {error && <div className="mt-5"><FormError message={error} /></div>}{notice && <p role="status" className="mt-5 rounded-xl bg-[#eef1e9] px-4 py-3 text-sm">{notice}</p>}
    {loading ? <p className="mt-8 text-sm text-gray-500">Loading your setup...</p> : !store ? <OwnerPanel className="mt-6" title="No store yet"><p className="mt-2 text-sm text-gray-600">Create a store to begin setup.</p><Link className="mt-4 inline-block underline" href="/owner/register">Register a store</Link></OwnerPanel> : <>
      <div className="mt-7 flex gap-2 text-xs font-semibold uppercase tracking-wide text-gray-500" aria-label="Setup progress">{["Categories", "Product method", "Review"].map((label, index) => <span key={label} className={`rounded-full px-3 py-2 ${step === index + 1 ? "bg-[#243c30] text-white" : "bg-white"}`}>{index + 1}. {label}</span>)}</div>
      {step === 1 && <OwnerPanel className="mt-5" title="What will you sell?" description="Pick one or more store categories. You can update these later from Products & inventory."><div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{categories.map((item) => <label key={item.name} className="flex cursor-pointer items-start gap-3 rounded-2xl border p-4"><input className="mt-1 accent-[#243c30]" type="checkbox" checked={selected.includes(item.name)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, item.name] : current.filter((name) => name !== item.name))} /><span><b>{item.name}</b><span className="mt-1 block text-xs text-gray-500">{item.is_predefined ? "Store category" : "Custom category"}</span></span></label>)}</div><button className={primaryButtonClassName + " mt-5"} disabled={!selected.length} onClick={() => { setError(""); setStep(2); }}>Continue with {selected.length} categories</button></OwnerPanel>}
      {step === 2 && <OwnerPanel className="mt-5" title="How would you like to add products?" description="You can change this choice before the final confirmation."><div className="mt-5 grid gap-4 md:grid-cols-2">{([["demo", "Start with demo products", "Preview realistic sample items for your selected categories. They are examples, not supplier inventory."], ["spreadsheet", "Upload my product sheet", "Use the existing CSV or Excel wizard to map columns, validate rows, and preview before importing."]] as const).map(([value, title, description]) => <button type="button" key={value} onClick={() => setMethod(value)} aria-pressed={method === value} className={`rounded-2xl border p-5 text-left ${method === value ? "border-[#243c30] bg-[#eef1e9] ring-2 ring-[#243c30]/15" : "bg-white"}`}><span className="font-semibold">{title}</span><span className="mt-2 block text-sm leading-6 text-gray-600">{description}</span></button>)}</div><div className="mt-5 flex gap-3"><button className="rounded-full border px-5 py-3 text-sm font-semibold" onClick={() => setStep(1)}>Back</button><button className={primaryButtonClassName} disabled={!method || saving} onClick={() => void reviewSetup()}>{saving ? "Saving..." : "Review setup"}</button></div></OwnerPanel>}
      {step === 3 && <OwnerPanel className="mt-5" title="Review your setup" description="Your catalog is saved only after you confirm the next step."><dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2"><div><dt className="text-gray-500">Store</dt><dd className="mt-1 font-semibold">{store.name} <span className="font-normal text-gray-500">/stores/{store.slug}</span></dd></div><div><dt className="text-gray-500">Product setup</dt><dd className="mt-1 font-semibold">{method === "demo" ? "Demo products" : "CSV/XLSX upload"}</dd></div><div className="sm:col-span-2"><dt className="text-gray-500">Selected categories</dt><dd className="mt-1">{selected.join(", ")}</dd></div></dl>
        {method === "demo" && preview && <><p className="mt-5 rounded-xl bg-[#f4f3ed] p-4 text-sm">{preview.total_products} sample products · {preview.importable_count} new · {preview.skipped_count} already present and will be skipped</p><div className="mt-4 grid gap-3 sm:grid-cols-2">{preview.products.map((product) => <article key={`${product.category}:${product.name}`} className="flex gap-3 rounded-xl border p-3"><div role="img" aria-label={`Sample product image: ${product.name}`} className="h-20 w-20 shrink-0 rounded-lg bg-cover bg-center" style={{ backgroundImage: `url(\"${product.image_url}\"), url(\"https://placehold.co/160x160?text=Sample\")` }} /><div className="min-w-0"><p className="font-semibold">{product.name}</p><p className="text-xs text-gray-500">{product.category} · ₹{product.price} · {product.stock} in sample stock</p><p className="mt-1 text-xs text-gray-600">{product.description}</p>{product.already_exists && <p className="mt-1 text-xs text-amber-700">Already exists; will be skipped</p>}</div></article>)}</div></>}
        {method === "spreadsheet" && <p className="mt-5 rounded-xl bg-[#f4f3ed] p-4 text-sm">The import wizard will show the number of valid rows after you upload a file. No rows are written before you confirm that preview.</p>}
        <div className="mt-5 flex flex-wrap gap-3"><button className="rounded-full border px-5 py-3 text-sm font-semibold" onClick={() => setStep(2)}>Change method</button>{method === "demo" ? <button className={primaryButtonClassName} disabled={saving || !preview?.total_products} onClick={() => void finishDemoImport()}>{saving ? "Importing..." : preview?.importable_count ? `Confirm and add ${preview.importable_count} demo products` : "Finish setup with existing products"}</button> : <button className={primaryButtonClassName} onClick={continueToSpreadsheet}>Continue to spreadsheet import</button>}</div>
      </OwnerPanel>}
    </>}
  </OwnerFrame>;
}
