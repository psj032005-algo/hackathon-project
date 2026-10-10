"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { SessionExpiredError, useAuth } from "../../auth-provider";
import {
  FormError,
  FormField,
  inputClassName,
  OwnerFrame,
  OwnerPanel,
  primaryButtonClassName,
  responseError,
} from "../owner-ui";

type Store = {
  slug: string;
  name: string;
  description: string;
  logo_url: string | null;
  is_published: boolean;
  business_type: string;
  address_line1: string;
  address_line2: string;
  city: string;
  region: string;
  postal_code: string;
  country: string;
  contact_email: string;
  contact_phone: string;
  role: "owner" | "staff";
};

type StoreChanges = Partial<Pick<Store, "name" | "description" | "logo_url" | "is_published" | "business_type" | "address_line1" | "address_line2" | "city" | "region" | "postal_code" | "country" | "contact_email" | "contact_phone">>;
type AnalyticsSummary = { total_orders: number; delivered_revenue: number; pending_revenue: number; orders_by_status: Record<string, number>; low_stock_products: { id: number; name: string; stock: number }[]; low_stock_variants: { product_id: number; name: string; variant_name: string; variant_value: string; stock: number }[]; product_count: number; stock_units: number };
type StoreAgentResponse = { answer: string; explanation?: string | null; intent?: string; supporting_data: Record<string, unknown>[]; metric_definitions?: string[]; clarification?: string | null; mode: "ai" | "faq_fallback" };
type StoreAgentTurn = { question: string; response: StoreAgentResponse };

const STORE_AGENT_QUESTIONS = [
  "Summarize my store.",
  "Which products are low on stock?",
  "How many orders are pending?",
  "Compare this month with last month.",
  "What should I restock first?",
];

function evidenceValue(value: unknown): string {
  if (value === null || value === undefined) return "Not available";
  if (typeof value === "number") return new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(value);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function evidenceLabel(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function StoreDetailsForm({
  store,
  saving,
  onSave,
}: {
  store: Store;
  saving: boolean;
  onSave: (changes: StoreChanges) => Promise<void>;
}) {
  const [name, setName] = useState(store.name);
  const [description, setDescription] = useState(store.description ?? "");
  const [logoUrl, setLogoUrl] = useState(store.logo_url ?? "");
  const [businessType, setBusinessType] = useState(store.business_type || "Other");
  const [addressLine1, setAddressLine1] = useState(store.address_line1 || "");
  const [addressLine2, setAddressLine2] = useState(store.address_line2 || "");
  const [city, setCity] = useState(store.city || "");
  const [region, setRegion] = useState(store.region || "");
  const [postalCode, setPostalCode] = useState(store.postal_code || "");
  const [country, setCountry] = useState(store.country || "");
  const [contactEmail, setContactEmail] = useState(store.contact_email || "");
  const [contactPhone, setContactPhone] = useState(store.contact_phone || "");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setNotice("");
    try {
      await onSave({
        name: name.trim(),
        description: description.trim(),
        logo_url: logoUrl.trim() || null,
        business_type: businessType,
        address_line1: addressLine1.trim(),
        address_line2: addressLine2.trim(),
        city: city.trim(),
        region: region.trim(),
        postal_code: postalCode.trim(),
        country: country.trim(),
        contact_email: contactEmail.trim(),
        contact_phone: contactPhone.trim(),
      });
      setNotice("Your store details have been saved.");
    } catch (caught) {
      if (!(caught instanceof SessionExpiredError)) {
        setError(caught instanceof Error ? caught.message : "Could not save store details.");
      }
    }
  }

  return (
    <>
      {error && <FormError message={error} />}
      {notice && <p role="status" className="mb-4 rounded-xl bg-[#eef1e9] px-4 py-3 text-sm text-[#243c30]">{notice}</p>}
      <form onSubmit={submit} className="mt-5 space-y-5">
        <FormField label="Store name">
          <input
            className={inputClassName}
            required
            minLength={1}
            maxLength={120}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </FormField>
        <FormField label="Store address" hint="Public path address. It cannot be changed after registration.">
          <input className={`${inputClassName} bg-[#f4f3ed] text-gray-600`} value={`/stores/${store.slug}`} readOnly />
        </FormField>
        <FormField label="Business type"><select className={inputClassName} value={businessType} onChange={(e) => setBusinessType(e.target.value)}>{["Home goods", "Clothing & accessories", "Food & beverage", "Wellness", "Arts & crafts", "Other"].map((type) => <option key={type}>{type}</option>)}</select></FormField>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label="Street address"><input className={inputClassName} maxLength={200} value={addressLine1} onChange={(e) => setAddressLine1(e.target.value)} /></FormField>
          <FormField label="Address line 2"><input className={inputClassName} maxLength={200} value={addressLine2} onChange={(e) => setAddressLine2(e.target.value)} /></FormField>
          <FormField label="City"><input className={inputClassName} maxLength={120} value={city} onChange={(e) => setCity(e.target.value)} /></FormField>
          <FormField label="State / region"><input className={inputClassName} maxLength={120} value={region} onChange={(e) => setRegion(e.target.value)} /></FormField>
          <FormField label="Postal code"><input className={inputClassName} maxLength={32} value={postalCode} onChange={(e) => setPostalCode(e.target.value)} /></FormField>
          <FormField label="Country"><input className={inputClassName} maxLength={120} value={country} onChange={(e) => setCountry(e.target.value)} /></FormField>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label="Store contact email"><input className={inputClassName} type="email" maxLength={254} value={contactEmail} onChange={(e) => setContactEmail(e.target.value)} /></FormField>
          <FormField label="Store contact phone"><input className={inputClassName} type="tel" maxLength={40} value={contactPhone} onChange={(e) => setContactPhone(e.target.value)} /></FormField>
        </div>
        <FormField label="Description">
          <textarea
            className={`${inputClassName} min-h-28 resize-y`}
            maxLength={2000}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="A short introduction to your store"
          />
        </FormField>
        <FormField label="Logo image URL" hint="Optional. Use a publicly accessible image URL.">
          <input
            className={inputClassName}
            type="url"
            maxLength={2048}
            value={logoUrl}
            onChange={(event) => setLogoUrl(event.target.value)}
            placeholder="https://example.com/logo.png"
          />
        </FormField>
        <button className={primaryButtonClassName} disabled={saving}>
          {saving ? "Saving…" : "Save changes"}
        </button>
      </form>
    </>
  );
}

function StaffManager({ store, authorizedFetch }: { store: Store; authorizedFetch: (path: string, init?: RequestInit) => Promise<Response> }) {
  const [staff, setStaff] = useState<{ user_id: number; email: string }[]>([]);
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const endpoint = `/api/owner/stores/${encodeURIComponent(store.slug)}/staff`;
  const refresh = useCallback(async () => {
    const response = await authorizedFetch(endpoint);
    if (!response.ok) throw new Error(await responseError(response));
    const result = await response.json() as { id: number; email: string }[];
    setStaff(result.map(({ id, email: address }) => ({ user_id: id, email: address })));
  }, [authorizedFetch, endpoint]);
  useEffect(() => { const timer = window.setTimeout(() => { void refresh().catch((caught) => setError(caught instanceof Error ? caught.message : "Could not load staff.")); }, 0); return () => window.clearTimeout(timer); }, [refresh]);
  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    try { const response = await authorizedFetch(endpoint, { method: "POST", body: JSON.stringify({ email: email.trim() }) }); if (!response.ok) throw new Error(await responseError(response)); setEmail(""); await refresh(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Could not add staff."); }
    finally { setBusy(false); }
  }
  async function remove(userId: number) {
    setBusy(true); setError("");
    try { const response = await authorizedFetch(`${endpoint}/${userId}`, { method: "DELETE" }); if (!response.ok) throw new Error(await responseError(response)); await refresh(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Could not remove staff."); }
    finally { setBusy(false); }
  }
  return <OwnerPanel title="Staff access" description="Invite an existing account to manage this store’s catalog and orders. Staff cannot publish or change store settings.">
    {error && <FormError message={error} />}
    <form onSubmit={add} className="mt-4 flex flex-col gap-2 sm:flex-row"><input className={inputClassName} type="email" required maxLength={254} value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Existing account email" /><button className={primaryButtonClassName} disabled={busy}>Add staff</button></form>
    <ul className="mt-4 divide-y">{staff.map((member) => <li key={member.user_id} className="flex items-center justify-between gap-3 py-3 text-sm"><span className="break-all">{member.email}</span><button className="shrink-0 text-red-700 underline" disabled={busy} onClick={() => void remove(member.user_id)}>Remove</button></li>)}{staff.length === 0 && <li className="py-3 text-sm text-gray-500">No staff accounts have been added.</li>}</ul>
  </OwnerPanel>;
}

function OwnerStoreChat({ store, authorizedFetch }: { store: Store; authorizedFetch: (path: string, init?: RequestInit) => Promise<Response> }) {
  const [message, setMessage] = useState("");
  const [turns, setTurns] = useState<StoreAgentTurn[]>([]);
  const [error, setError] = useState("");
  const [retryQuestion, setRetryQuestion] = useState("");
  const [busy, setBusy] = useState(false);

  async function sendQuestion(question: string) {
    const cleanQuestion = question.trim();
    if (!cleanQuestion || busy) return;
    setBusy(true);
    setError("");
    try {
      const response = await authorizedFetch(`/api/owner/stores/${encodeURIComponent(store.slug)}/chat`, {
        method: "POST",
        body: JSON.stringify({ message: cleanQuestion }),
      });
      if (!response.ok) throw new Error(await responseError(response));
      const result = await response.json() as StoreAgentResponse;
      if (typeof result.answer !== "string" || !Array.isArray(result.supporting_data)) {
        throw new Error("The store assistant returned an invalid response. Please retry.");
      }
      setTurns((previous) => [...previous, { question: cleanQuestion, response: result }]);
      setMessage("");
      setRetryQuestion("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not query store data.");
      setRetryQuestion(cleanQuestion);
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void sendQuestion(message);
  }

  return <OwnerPanel title="AI Store Assistant" description="Ask questions about this store’s products, inventory, order activity, and sales. Answers use read-only store records; customer contact details are excluded.">
    {turns.length === 0 && <div className="mt-4">
      <p className="text-sm font-medium">Try asking</p>
      <div className="mt-2 flex flex-wrap gap-2">{STORE_AGENT_QUESTIONS.map((question) => <button key={question} type="button" className="rounded-full border border-[#d9d8cf] px-3 py-2 text-left text-xs hover:bg-[#f4f3ed]" disabled={busy} onClick={() => void sendQuestion(question)}>{question}</button>)}</div>
    </div>}
    <div aria-live="polite" aria-relevant="additions" className="mt-4 max-h-[34rem] space-y-4 overflow-y-auto pr-1">
      {turns.map(({ question, response }, index) => <article key={`${index}-${question}`} className="space-y-3 rounded-2xl border border-black/5 bg-[#faf9f6] p-4">
        <p className="font-medium">You asked: <span className="font-normal">{question}</span></p>
        <div className="rounded-xl bg-white p-3 text-sm">
          <p>{response.answer}</p>
          {response.explanation && <p className="mt-2 border-t border-black/5 pt-2 text-gray-700">{response.explanation}</p>}
          <p className="mt-3 text-xs text-gray-500">{response.mode === "ai" ? "AI-assisted explanation · evidence below is computed from store records" : "Deterministic database answer"}</p>
        </div>
        {response.supporting_data.length > 0 && <details className="rounded-xl border border-black/5 bg-white px-3 py-2 text-xs">
          <summary className="cursor-pointer font-semibold">Evidence and retrieved figures</summary>
          <div className="mt-3 space-y-3">{response.supporting_data.map((fact, factIndex) => <dl key={factIndex} className="grid gap-x-4 gap-y-2 sm:grid-cols-2">{Object.entries(fact).map(([key, value]) => <div key={key} className="min-w-0"><dt className="text-gray-500">{evidenceLabel(key)}</dt><dd className="break-words font-medium">{evidenceValue(value)}</dd></div>)}</dl>)}</div>
          {response.metric_definitions?.map((definition) => <p key={definition} className="mt-2 border-t border-black/5 pt-2 text-gray-500">{definition}</p>)}
        </details>}
      </article>)}
      {busy && <p role="status" className="rounded-xl bg-[#f4f3ed] p-3 text-sm">Checking this store’s records…</p>}
    </div>
    <form onSubmit={submit} className="mt-4 space-y-3">
      <label htmlFor="store-agent-question" className="text-sm font-medium">Ask a store question</label>
      <textarea id="store-agent-question" aria-describedby="store-agent-help" className={`${inputClassName} min-h-24 resize-y`} maxLength={500} required value={message} onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} placeholder="Which products sold the most?" />
      <p id="store-agent-help" className="text-xs text-gray-500">Press Enter to send or Shift+Enter for a new line.</p>
      <button className={primaryButtonClassName} disabled={busy || !message.trim()}>{busy ? "Checking store data…" : "Ask assistant"}</button>
    </form>
    {error && <div className="mt-3"><FormError message={error} />{retryQuestion && <button type="button" className="mt-2 text-sm font-semibold underline" disabled={busy} onClick={() => void sendQuestion(retryQuestion)}>Retry question</button>}</div>}
  </OwnerPanel>;
}
export default function OwnerDashboardPage() {
  const router = useRouter();
  const { token, ready, logout, authorizedFetch } = useAuth();
  const [stores, setStores] = useState<Store[]>([]);
  const [selectedSlug, setSelectedSlug] = useState("");
  const [store, setStore] = useState<Store | null>(null);
  const [loadingStores, setLoadingStores] = useState(true);
  const [loadingStore, setLoadingStore] = useState(false);
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [analytics, setAnalytics] = useState<AnalyticsSummary | null>(null);
  const [analyticsSlug, setAnalyticsSlug] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");

  useEffect(() => {
    if (ready && !token) router.replace("/owner/login");
  }, [ready, token, router]);

  useEffect(() => {
    if (!ready || !token) return;
    let cancelled = false;

    async function loadStores() {
      setLoadingStores(true);
      setError("");
      try {
        const response = await authorizedFetch("/api/owner/stores");
        if (!response.ok) throw new Error(await responseError(response));
        const result: Store[] = await response.json();
        if (cancelled) return;
        setStores(result);
        setSelectedSlug((current) =>
          result.some((item) => item.slug === current) ? current : result[0]?.slug ?? "",
        );
      } catch (caught) {
        if (!cancelled && !(caught instanceof SessionExpiredError)) {
          setError(caught instanceof Error ? caught.message : "Could not load your stores.");
        }
      } finally {
        if (!cancelled) setLoadingStores(false);
      }
    }

    void loadStores();
    return () => {
      cancelled = true;
    };
  }, [ready, token, authorizedFetch]);

  useEffect(() => {
    if (!token || !selectedSlug) {
      return;
    }
    let cancelled = false;

    async function loadStore() {
      setLoadingStore(true);
      setError("");
      try {
        // The slug comes from the authenticated owner list; the backend still
        // independently checks ownership for this detail request.
        const response = await authorizedFetch(
          `/api/owner/stores/${encodeURIComponent(selectedSlug)}`,
        );
        if (!response.ok) throw new Error(await responseError(response));
        const result: Store = await response.json();
        if (!cancelled) setStore(result);
      } catch (caught) {
        if (!cancelled && !(caught instanceof SessionExpiredError)) {
          setError(caught instanceof Error ? caught.message : "Could not load store details.");
        }
      } finally {
        if (!cancelled) setLoadingStore(false);
      }
    }

    void loadStore();
    return () => {
      cancelled = true;
    };
  }, [token, selectedSlug, authorizedFetch]);

  const updateStore = useCallback(
    async (storeToUpdate: Store, changes: StoreChanges) => {
      const response = await authorizedFetch(
        `/api/owner/stores/${encodeURIComponent(storeToUpdate.slug)}`,
        { method: "PATCH", body: JSON.stringify(changes) },
      );
      if (!response.ok) throw new Error(await responseError(response));
      const updated: Store = await response.json();
      setStore(updated);
      setStores((current) => current.map((item) => (item.slug === updated.slug ? updated : item)));
      return updated;
    },
    [authorizedFetch],
  );

  const activeStore = store?.slug === selectedSlug ? store : null;

  useEffect(() => {
    if (!token || !selectedSlug) return;
    if (fromDate && toDate && fromDate > toDate) return;
    let cancelled = false;
    const query = new URLSearchParams(); if (fromDate) query.set("from_date", fromDate); if (toDate) query.set("to_date", toDate);
    authorizedFetch(`/api/owner/stores/${encodeURIComponent(selectedSlug)}/analytics?${query}`)
      .then(async (response) => { if (!response.ok) throw new Error(await responseError(response)); return response.json() as Promise<AnalyticsSummary>; })
      .then((result) => { if (!cancelled) { setAnalytics(result); setAnalyticsSlug(selectedSlug); } })
      .catch(() => { if (!cancelled) setAnalyticsSlug(""); });
    return () => { cancelled = true; };
  }, [token, selectedSlug, fromDate, toDate, authorizedFetch]);

  async function saveSettings(changes: StoreChanges) {
    if (!activeStore) return;
    setError("");
    setNotice("");
    setSaving(true);
    try {
      await updateStore(activeStore, changes);
    } finally {
      setSaving(false);
    }
  }

  async function togglePublication() {
    if (!activeStore) return;
    setError("");
    setNotice("");
    setPublishing(true);
    try {
      const updated = await updateStore(activeStore, { is_published: !activeStore.is_published });
      if (updated) {
        setNotice(updated.is_published ? "Your store is now published." : "Your store is unpublished.");
      }
    } catch (caught) {
      if (!(caught instanceof SessionExpiredError)) {
        setError(caught instanceof Error ? caught.message : "Could not update publishing status.");
      }
    } finally {
      setPublishing(false);
    }
  }

  async function copyPublicUrl() {
    if (!activeStore) return;
    const url = `${window.location.origin}/stores/${encodeURIComponent(activeStore.slug)}`;
    try { await navigator.clipboard.writeText(url); setNotice("Public storefront URL copied."); setError(""); }
    catch { setError("Could not copy the URL. Copy the displayed store path instead."); }
  }

  if (!ready || !token) {
    return (
      <OwnerFrame eyebrow="YOUR STORE" adminNav>
        <p className="mt-8 text-center text-sm text-gray-500">Checking your sign-in…</p>
      </OwnerFrame>
    );
  }

  return (
    <OwnerFrame eyebrow="YOUR STORE" adminNav>
      <div className="mt-5 flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-4xl font-medium tracking-tight sm:text-5xl">Store dashboard.</h1>
          <p className="mt-3 text-base leading-7 text-gray-600">Update your store details and control when customers can see it.</p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Link href="/owner/setup" className="rounded-full border border-[#d9d8cf] px-5 py-2.5 text-sm font-semibold transition hover:bg-white">Store setup & categories</Link>
          <Link href="/owner/products" className="rounded-full border border-[#d9d8cf] px-5 py-2.5 text-sm font-semibold transition hover:bg-white">Products & inventory</Link>
          {activeStore?.role === "owner" && <Link href="/owner/customize" className="rounded-full border border-[#d9d8cf] px-5 py-2.5 text-sm font-semibold transition hover:bg-white">Customize storefront</Link>}
          <Link href="/owner/orders" className="rounded-full border border-[#d9d8cf] px-5 py-2.5 text-sm font-semibold transition hover:bg-white">Orders & analytics</Link>
          <button
            type="button"
            onClick={logout}
            className="rounded-full border border-[#d9d8cf] px-5 py-2.5 text-sm font-semibold transition hover:bg-white"
          >
            Sign out
          </button>
        </div>
      </div>

      <div className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)]">
        <OwnerPanel title="Store access" description="Stores where you are an owner or a staff member appear here.">
          {loadingStores ? (
            <p className="mt-5 text-sm text-gray-500">Loading your stores…</p>
          ) : stores.length === 0 ? (
            <div className="mt-5 space-y-4">
              <p className="text-sm leading-6 text-gray-600">There are no stores linked to this account yet.</p>
              <Link href="/owner/register" className="inline-block text-sm font-semibold text-[#243c30] underline underline-offset-4">
                Create a store
              </Link>
            </div>
          ) : (
            <>
              <label className="mt-5 block">
                <span className="mb-2 block text-sm font-medium">Choose a store</span>
                <select
                  className={inputClassName}
                  value={selectedSlug}
                  onChange={(event) => setSelectedSlug(event.target.value)}
                >
                  {stores.map((item) => (
                    <option value={item.slug} key={item.slug}>{item.name}</option>
                  ))}
                </select>
              </label>
              {activeStore && (
                <div className="mt-6 rounded-2xl bg-[#f4f3ed] p-4">
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Publishing status</p>
                  <div className="mt-2 flex items-center gap-2">
                    <span className={`h-2.5 w-2.5 rounded-full ${activeStore.is_published ? "bg-emerald-600" : "bg-amber-500"}`} />
                    <span className="font-semibold">{activeStore.is_published ? "Published" : "Unpublished"}</span>
                  </div>
                  <p className="mt-2 text-sm leading-6 text-gray-600">
                    {activeStore.is_published
                      ? "Your public storefront is visible to customers."
                      : "Your public storefront is hidden until you publish it."}
                  </p>
                  {activeStore.role === "owner" && <button
                    type="button"
                    onClick={togglePublication}
                    disabled={publishing || loadingStore}
                    className={`${primaryButtonClassName} mt-4 w-full`}
                  >
                    {publishing
                      ? "Updating…"
                      : activeStore.is_published
                        ? "Unpublish store"
                        : "Publish store"}
                  </button>}
                  <p className="mt-4 break-all font-mono text-xs text-gray-600">Path: /stores/{activeStore.slug}</p>
                  <button type="button" onClick={() => void copyPublicUrl()} className="mt-2 text-sm font-semibold underline">Copy storefront URL</button>
                </div>
              )}
            </>
          )}
        </OwnerPanel>

        <OwnerPanel title="Store details" description="These details are saved to your store profile.">
          {error && <FormError message={error} />}
          {notice && <p role="status" className="mb-4 rounded-xl bg-[#eef1e9] px-4 py-3 text-sm text-[#243c30]">{notice}</p>}
          {loadingStore ? (
            <p className="mt-5 text-sm text-gray-500">Loading store details…</p>
          ) : activeStore ? (
            activeStore.role === "owner" ? <StoreDetailsForm
              key={activeStore.slug}
              store={activeStore}
              saving={saving || loadingStore}
              onSave={saveSettings}
            /> : <div className="mt-5 rounded-xl bg-[#f4f3ed] p-4 text-sm text-gray-600">You have staff access. A store owner manages profile and publishing settings.</div>
          ) : !error && !loadingStores && stores.length === 0 ? (
            <p className="mt-5 text-sm text-gray-500">Create a store to manage its details.</p>
          ) : null}
        </OwnerPanel>
      </div>
      {activeStore?.role === "owner" && <div className="mt-6 grid gap-6 lg:grid-cols-2"><StaffManager key={activeStore.slug} store={activeStore} authorizedFetch={authorizedFetch} /><OwnerStoreChat key={`chat-${activeStore.slug}`} store={activeStore} authorizedFetch={authorizedFetch} /></div>}
      {analytics && analyticsSlug === selectedSlug && <section className="mt-6">
        <div className="mb-4 flex flex-wrap items-end gap-3 rounded-2xl border border-black/10 bg-white/70 p-4"><p className="mr-auto text-sm font-semibold">Analytics date range</p><label className="text-xs">From<input aria-label="Analytics from date" className="mt-1 block rounded-xl border px-3 py-2 text-sm" type="date" value={fromDate} max={toDate || undefined} onChange={(e) => setFromDate(e.target.value)} /></label><label className="text-xs">To<input aria-label="Analytics to date" className="mt-1 block rounded-xl border px-3 py-2 text-sm" type="date" value={toDate} min={fromDate || undefined} onChange={(e) => setToDate(e.target.value)} /></label><button className="rounded-full border px-4 py-2 text-sm" onClick={() => { setFromDate(""); setToDate(""); }}>Clear</button></div>
        {fromDate && toDate && fromDate > toDate ? <p role="alert" className="mb-4 text-sm text-red-700">The start date must be on or before the end date.</p> : <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><OwnerPanel title="Total orders"><p className="mt-3 text-3xl font-semibold">{analytics.total_orders}</p></OwnerPanel><OwnerPanel title="Delivered revenue"><p className="mt-3 text-2xl font-semibold">{new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(analytics.delivered_revenue)}</p><p className="mt-1 text-xs text-gray-500">Delivered only · demo checkout</p></OwnerPanel><OwnerPanel title="Pending order value"><p className="mt-3 text-2xl font-semibold">{new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(analytics.pending_revenue)}</p><p className="mt-1 text-xs text-gray-500">Placed, packed, and shipped</p></OwnerPanel><OwnerPanel title="Catalog inventory"><p className="mt-3 text-2xl font-semibold">{analytics.product_count} products · {analytics.stock_units} units</p><p className="mt-1 text-xs text-gray-500">{analytics.low_stock_products.length + analytics.low_stock_variants.length} low-stock products / variants</p><Link className="mt-2 inline-block text-sm underline" href="/owner/orders">View operations</Link></OwnerPanel></div>}
      </section>}
    </OwnerFrame>
  );
}
