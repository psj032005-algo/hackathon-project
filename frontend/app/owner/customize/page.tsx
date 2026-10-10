"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { SessionExpiredError, useAuth } from "../../auth-provider";
import { FormError, FormField, inputClassName, OwnerFrame, OwnerPanel, primaryButtonClassName, responseError } from "../owner-ui";

type Store = { slug: string; name: string };
type Settings = { theme_id: string; primary_color: string; accent_color: string; background_color: string; font_family: string; banner_url: string | null; homepage_sections: string[]; footer_text: string; contact_email: string; contact_phone: string; shipping_policy: string; returns_policy: string };
const palettes = {
  market: { primary_color: "#243c30", accent_color: "#9b7753", background_color: "#faf9f6", font_family: "sans" },
  botanical: { primary_color: "#315b43", accent_color: "#bd7e55", background_color: "#f4f7ef", font_family: "serif" },
  studio: { primary_color: "#25365a", accent_color: "#c28538", background_color: "#f5f5f5", font_family: "sans" },
  midnight: { primary_color: "#1f2937", accent_color: "#d6b56d", background_color: "#f0f0f0", font_family: "mono" },
};
const sectionChoices = [["hero", "Hero banner"], ["featured", "Featured products"], ["categories", "Category filters"], ["newsletter", "Newsletter panel"]];

export default function OwnerCustomizePage() {
  const { ready, token, authorizedFetch } = useAuth();
  const [stores, setStores] = useState<Store[]>([]);
  const [slug, setSlug] = useState("");
  const [savedSettings, setSettings] = useState<Settings | null>(null);
  const [settingsSlug, setSettingsSlug] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (!ready || !token) return;
    let cancelled = false;
    async function load() {
      try {
        const response = await authorizedFetch("/api/owner/stores");
        if (!response.ok) throw new Error(await responseError(response));
        const result: Store[] = await response.json();
        if (!cancelled) { setStores(result); setSlug((current) => result.some((item) => item.slug === current) ? current : result[0]?.slug || ""); }
      } catch (caught) { if (!cancelled && !(caught instanceof SessionExpiredError)) setError(caught instanceof Error ? caught.message : "Could not load stores."); }
    }
    void load();
    return () => { cancelled = true; };
  }, [ready, token, authorizedFetch]);

  useEffect(() => {
    if (!token || !slug) return;
    let cancelled = false;
    async function loadSettings() {
      setLoading(true);
      try {
        const response = await authorizedFetch("/api/owner/stores/" + encodeURIComponent(slug) + "/customization");
        if (!response.ok) throw new Error(await responseError(response));
        const result: Settings = await response.json();
        if (!cancelled) { setSettings(result); setSettingsSlug(slug); }
      } catch (caught) { if (!cancelled && !(caught instanceof SessionExpiredError)) setError(caught instanceof Error ? caught.message : "Could not load customization."); }
      finally { if (!cancelled) setLoading(false); }
    }
    void loadSettings();
    return () => { cancelled = true; };
  }, [token, slug, authorizedFetch]);

  function chooseTheme(theme: keyof typeof palettes) {
    if (!savedSettings) return;
    setSettings({ ...savedSettings, theme_id: theme, ...palettes[theme] });
  }
  function toggleSection(section: string) {
    if (!savedSettings) return;
    const active = savedSettings.homepage_sections.includes(section);
    if (active && savedSettings.homepage_sections.length === 1) {
      setError("Keep at least one homepage section enabled.");
      return;
    }
    const next = active ? savedSettings.homepage_sections.filter((item) => item !== section) : [...savedSettings.homepage_sections, section];
    setError("");
    setSettings({ ...savedSettings, homepage_sections: next });
  }
  async function save() {
    if (!savedSettings || settingsSlug !== slug || !slug) return;
    setSaving(true); setError(""); setNotice("");
    try {
      const payload = {
        theme_id: savedSettings.theme_id,
        primary_color: savedSettings.primary_color,
        accent_color: savedSettings.accent_color,
        background_color: savedSettings.background_color,
        font_family: savedSettings.font_family,
        banner_url: savedSettings.banner_url,
        homepage_sections: savedSettings.homepage_sections,
        footer_text: savedSettings.footer_text,
        contact_email: savedSettings.contact_email,
        contact_phone: savedSettings.contact_phone,
        shipping_policy: savedSettings.shipping_policy,
        returns_policy: savedSettings.returns_policy,
      };
      const response = await authorizedFetch("/api/owner/stores/" + encodeURIComponent(slug) + "/customization", { method: "PATCH", body: JSON.stringify(payload) });
      if (!response.ok) throw new Error(await responseError(response));
      setSettings(await response.json()); setNotice("Storefront customization saved.");
    } catch (caught) { if (!(caught instanceof SessionExpiredError)) setError(caught instanceof Error ? caught.message : "Could not save customization."); }
    finally { setSaving(false); }
  }

  if (!ready || !token) return <OwnerFrame eyebrow="CUSTOMIZE" adminNav><p className="mt-8 text-center text-sm text-gray-500">Checking your sign-in...</p></OwnerFrame>;
  const storeName = stores.find((item) => item.slug === slug)?.name || "Your Store";
  const settings = settingsSlug === slug ? savedSettings : null;
  const fontFamily = settings?.font_family === "serif" ? "Georgia, serif" : settings?.font_family === "mono" ? "monospace" : "Arial, sans-serif";

  return <OwnerFrame eyebrow="STORE DESIGN" adminNav>
    <div className="mt-5 flex flex-wrap items-end justify-between gap-4"><div><h1 className="text-4xl font-medium tracking-tight sm:text-5xl">Make it yours.</h1><p className="mt-3 text-sm text-gray-600">Choose a visual direction, then tune the details and preview your storefront.</p></div><div className="flex gap-3"><Link className="rounded-full border px-4 py-2 text-sm" href="/owner/dashboard">Dashboard</Link><Link className="rounded-full border px-4 py-2 text-sm" href="/owner/products">Products</Link></div></div>
    <div className="mt-6 max-w-md"><FormField label="Store"><select className={inputClassName} value={slug} onChange={(event) => setSlug(event.target.value)}>{stores.map((item) => <option key={item.slug} value={item.slug}>{item.name}</option>)}</select></FormField></div>
    {error && <div className="mt-4"><FormError message={error} /></div>}{notice && <p role="status" className="mt-4 rounded-xl bg-[#eef1e9] px-4 py-3 text-sm">{notice}</p>}
    {loading || !settings ? <p className="mt-8 text-sm text-gray-500">Loading theme settings...</p> : <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(360px,0.9fr)]">
      <div className="space-y-6">
        <OwnerPanel title="Four storefront themes" description="Each theme changes the color palette, typography, and product layout together.">
          <div className="mt-5 grid gap-3 sm:grid-cols-2">{Object.entries(palettes).map(([theme, palette]) => <button type="button" key={theme} onClick={() => chooseTheme(theme as keyof typeof palettes)} className={"rounded-2xl border p-4 text-left transition " + (settings.theme_id === theme ? "border-[#243c30] ring-2 ring-[#243c30]/15" : "border-[#e6e2d9]")}><div className="mb-3 flex gap-2"><span className="h-7 w-7 rounded-full" style={{ backgroundColor: palette.primary_color }} /><span className="h-7 w-7 rounded-full" style={{ backgroundColor: palette.accent_color }} /><span className="h-7 w-7 rounded-full border" style={{ backgroundColor: palette.background_color }} /></div><span className="font-semibold capitalize">{theme}</span><span className="mt-1 block text-xs text-gray-500">{theme === "market" ? "Warm everyday market" : theme === "botanical" ? "Natural, editorial shop" : theme === "studio" ? "Crisp modern catalog" : "Minimal monochrome"}</span></button>)}</div>
        </OwnerPanel>
        <OwnerPanel title="Colors and type" description="Colors accept six digit hex values. Fonts are a fixed safe list.">
          <div className="grid gap-4 sm:grid-cols-2"><FormField label="Primary color"><input className={inputClassName} type="color" value={settings.primary_color} onChange={(e) => setSettings({ ...settings, primary_color: e.target.value })} /></FormField><FormField label="Accent color"><input className={inputClassName} type="color" value={settings.accent_color} onChange={(e) => setSettings({ ...settings, accent_color: e.target.value })} /></FormField><FormField label="Background color"><input className={inputClassName} type="color" value={settings.background_color} onChange={(e) => setSettings({ ...settings, background_color: e.target.value })} /></FormField><FormField label="Font family"><select className={inputClassName} value={settings.font_family} onChange={(e) => setSettings({ ...settings, font_family: e.target.value })}><option value="sans">Modern sans</option><option value="serif">Editorial serif</option><option value="mono">Minimal mono</option></select></FormField></div>
        </OwnerPanel>
        <OwnerPanel title="Homepage content">
          <div className="space-y-3">{sectionChoices.map(([key, label]) => <label className="flex items-center gap-3 text-sm" key={key}><input type="checkbox" checked={settings.homepage_sections.includes(key)} onChange={() => toggleSection(key)} />{label}</label>)}</div>
          <div className="mt-5 grid gap-4"><FormField label="Banner image URL"><input className={inputClassName} type="url" placeholder="https://example.com/banner.jpg" value={settings.banner_url || ""} onChange={(e) => setSettings({ ...settings, banner_url: e.target.value || null })} /></FormField><FormField label="Footer message"><textarea className={inputClassName} maxLength={1000} value={settings.footer_text} onChange={(e) => setSettings({ ...settings, footer_text: e.target.value })} /></FormField></div>
        </OwnerPanel>
        <OwnerPanel title="Contact and store policies"><div className="grid gap-4 sm:grid-cols-2"><FormField label="Contact email"><input className={inputClassName} type="email" maxLength={254} value={settings.contact_email} onChange={(e) => setSettings({ ...settings, contact_email: e.target.value })} /></FormField><FormField label="Contact phone"><input className={inputClassName} type="tel" maxLength={40} value={settings.contact_phone} onChange={(e) => setSettings({ ...settings, contact_phone: e.target.value })} /></FormField><FormField label="Shipping policy" hint="Plain text only; the store helper can answer questions using this text."><textarea className={inputClassName} maxLength={2000} value={settings.shipping_policy || ""} onChange={(e) => setSettings({ ...settings, shipping_policy: e.target.value })} /></FormField><FormField label="Returns and refunds policy"><textarea className={inputClassName} maxLength={2000} value={settings.returns_policy || ""} onChange={(e) => setSettings({ ...settings, returns_policy: e.target.value })} /></FormField></div></OwnerPanel>
        <button className={primaryButtonClassName} onClick={() => void save()} disabled={saving}>{saving ? "Saving..." : "Save storefront design"}</button>
      </div>
      <OwnerPanel title="Live preview" description="Preview updates as you change settings. Saving updates this store's public appearance; unpublished stores stay hidden.">
        <div className="storefront-page overflow-hidden rounded-2xl border" data-store-theme={settings.theme_id} style={{ color: "#22251f", backgroundColor: settings.background_color, fontFamily, "--store-primary": settings.primary_color, "--store-accent": settings.accent_color, "--store-surface": settings.background_color } as CSSProperties}>
          <div className="px-4 py-2 text-center text-xs text-white" style={{ backgroundColor: settings.primary_color }}>{storeName}</div>
          <div className="flex items-center justify-between border-b px-4 py-4"><strong style={{ color: settings.primary_color, fontFamily }}>{storeName}</strong><span className="rounded-full px-4 py-2 text-xs text-white" style={{ backgroundColor: settings.primary_color }}>Shop now</span></div>
          {settings.homepage_sections.includes("hero") && <div className="p-5 sm:p-8" style={{ backgroundImage: settings.banner_url ? "linear-gradient(#0004,#0004),url(" + settings.banner_url + ")" : undefined, backgroundSize: "cover", backgroundPosition: "center", color: settings.banner_url ? "white" : undefined }}><p className="text-xs uppercase tracking-[0.2em]" style={{ color: settings.banner_url ? "white" : settings.accent_color }}>A LITTLE SOMETHING SPECIAL</p><h2 className="mt-3 text-3xl font-semibold">{storeName}</h2><p className="mt-2 text-sm">Thoughtful things, chosen with care.</p></div>}
          {settings.homepage_sections.includes("categories") && <div className="flex flex-wrap gap-2 px-4 py-3"><span className="rounded-full px-3 py-1 text-xs text-white" style={{ backgroundColor: settings.accent_color }}>Home</span><span className="rounded-full border px-3 py-1 text-xs">Accessories</span><span className="rounded-full border px-3 py-1 text-xs">Wellness</span></div>}
          {settings.homepage_sections.includes("featured") && <div className="storefront-grid grid grid-cols-2 gap-3 p-4"><div className="storefront-card h-20 rounded-xl bg-black/10" /><div className="storefront-card h-20 rounded-xl bg-black/10" /><div className="storefront-card hidden h-20 rounded-xl bg-black/10 sm:block" /></div>}
          {settings.homepage_sections.includes("newsletter") && <div className="mx-4 mb-4 rounded-xl p-4 text-sm text-white" style={{ backgroundColor: settings.primary_color }}>A note from {storeName}</div>}
          <div className="border-t px-4 py-3 text-xs" style={{ borderColor: settings.accent_color }}>{settings.footer_text || settings.contact_email || settings.contact_phone || "Footer and contact information"}</div>
        </div>
        <p className="mt-4 text-xs text-gray-500">Public path: <Link className="font-mono underline" href={"/stores/" + slug} target="_blank">/stores/{slug}</Link></p>
      </OwnerPanel>
    </div>}
  </OwnerFrame>;
}
