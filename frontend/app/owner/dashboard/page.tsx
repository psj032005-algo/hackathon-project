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
};

type StoreChanges = Partial<Pick<Store, "name" | "description" | "logo_url" | "is_published">>;
type AnalyticsSummary = { total_orders: number; delivered_revenue: number; orders_by_status: Record<string, number>; low_stock_products: { id: number; name: string; stock: number }[] };

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
        <FormField label="Store address" hint="This address is fixed after registration.">
          <input className={`${inputClassName} bg-[#f4f3ed] text-gray-600`} value={`/stores/${store.slug}`} readOnly />
        </FormField>
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
    let cancelled = false;
    authorizedFetch(`/api/owner/stores/${encodeURIComponent(selectedSlug)}/analytics`)
      .then(async (response) => { if (!response.ok) throw new Error(await responseError(response)); return response.json() as Promise<AnalyticsSummary>; })
      .then((result) => { if (!cancelled) { setAnalytics(result); setAnalyticsSlug(selectedSlug); } })
      .catch(() => { if (!cancelled) setAnalyticsSlug(""); });
    return () => { cancelled = true; };
  }, [token, selectedSlug, authorizedFetch]);

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

  if (!ready || !token) {
    return (
      <OwnerFrame eyebrow="YOUR STORE">
        <p className="mt-8 text-center text-sm text-gray-500">Checking your sign-in…</p>
      </OwnerFrame>
    );
  }

  return (
    <OwnerFrame eyebrow="YOUR STORE">
      <div className="mt-5 flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-4xl font-medium tracking-tight sm:text-5xl">Store dashboard.</h1>
          <p className="mt-3 text-base leading-7 text-gray-600">Update your store details and control when customers can see it.</p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Link href="/owner/products" className="rounded-full border border-[#d9d8cf] px-5 py-2.5 text-sm font-semibold transition hover:bg-white">Products & inventory</Link>
          <Link href="/owner/customize" className="rounded-full border border-[#d9d8cf] px-5 py-2.5 text-sm font-semibold transition hover:bg-white">Customize storefront</Link>
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
        <OwnerPanel title="Store access" description="Only stores linked to your owner account appear here.">
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
                  <button
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
                  </button>
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
            <StoreDetailsForm
              key={activeStore.slug}
              store={activeStore}
              saving={saving || loadingStore}
              onSave={saveSettings}
            />
          ) : !error && !loadingStores && stores.length === 0 ? (
            <p className="mt-5 text-sm text-gray-500">Create a store to manage its details.</p>
          ) : null}
        </OwnerPanel>
      </div>
      {analytics && analyticsSlug === selectedSlug && <section className="mt-6 grid gap-4 sm:grid-cols-3"><OwnerPanel title="Total orders"><p className="mt-3 text-3xl font-semibold">{analytics.total_orders}</p></OwnerPanel><OwnerPanel title="Delivered order value"><p className="mt-3 text-3xl font-semibold">{new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(analytics.delivered_revenue)}</p><p className="mt-1 text-xs text-gray-500">Delivered orders only</p></OwnerPanel><OwnerPanel title="Low-stock products"><p className="mt-3 text-3xl font-semibold">{analytics.low_stock_products.length}</p><p className="mt-1 text-xs text-gray-500">At 5 or fewer units</p><Link className="mt-2 inline-block text-sm underline" href="/owner/orders">View operations</Link></OwnerPanel></section>}
    </OwnerFrame>
  );
}
