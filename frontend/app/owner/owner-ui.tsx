import Link from "next/link";
import type { PropsWithChildren, ReactNode } from "react";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8002";

export function OwnerFrame({
  children,
  eyebrow = "STORE OWNER",
  adminNav = false,
}: PropsWithChildren<{ eyebrow?: string; adminNav?: boolean }>) {
  return (
    <main className="min-h-screen bg-[#faf9f6] text-[#22251f]">
      <div className="bg-[#243c30] px-4 py-2.5 text-center text-xs font-medium tracking-wide text-white">
        YOUR STORE, YOUR WAY · READY WHEN YOU ARE
      </div>
      <header className="border-b border-black/5 bg-[#faf9f6]">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-4 sm:px-8">
          <Link href="/" className="text-2xl font-semibold tracking-tight">
            little<span className="text-[#9b7753]">market.</span>
          </Link>
          <Link href="/" className="text-sm font-medium text-gray-600 hover:text-[#243c30]">
            Visit storefront
          </Link>
        </div>
      </header>
      {adminNav && <nav aria-label="Store admin" className="border-b border-black/5 bg-white/70"><div className="mx-auto flex max-w-6xl gap-2 overflow-x-auto px-5 py-3 text-sm sm:px-8"><Link className="shrink-0 rounded-full px-3 py-2 hover:bg-[#f4f3ed]" href="/owner/dashboard">Overview & settings</Link><Link className="shrink-0 rounded-full px-3 py-2 hover:bg-[#f4f3ed]" href="/owner/setup">Setup & categories</Link><Link className="shrink-0 rounded-full px-3 py-2 hover:bg-[#f4f3ed]" href="/owner/products">Products & imports</Link><Link className="shrink-0 rounded-full px-3 py-2 hover:bg-[#f4f3ed]" href="/owner/orders">Orders & analytics</Link></div></nav>}
      <section className="mx-auto w-full max-w-6xl px-5 py-10 sm:px-8 sm:py-14">
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[#9b7753]">
          {eyebrow}
        </p>
        {children}
      </section>
    </main>
  );
}

export function OwnerPanel({
  title,
  description,
  children,
  className = "",
}: PropsWithChildren<{
  title?: string;
  description?: string;
  className?: string;
}>) {
  return (
    <section className={`rounded-3xl border border-[#e6e2d9] bg-white p-6 shadow-sm sm:p-8 ${className}`}>
      {title && <h2 className="text-xl font-semibold tracking-tight">{title}</h2>}
      {description && <p className="mt-2 text-sm leading-6 text-gray-600">{description}</p>}
      {children}
    </section>
  );
}

export function FormField({
  label,
  hint,
  children,
}: PropsWithChildren<{ label: string; hint?: ReactNode }>) {
  return (
    <label className="block">
      <span className="mb-2 block text-sm font-medium text-[#30332d]">{label}</span>
      {children}
      {hint && <span className="mt-1.5 block text-xs leading-5 text-gray-500">{hint}</span>}
    </label>
  );
}

export const inputClassName =
  "w-full rounded-xl border border-[#d9d8cf] bg-[#fffefa] px-4 py-3 text-sm outline-none transition focus:border-[#607c62] focus:ring-2 focus:ring-[#607c62]/15";

export const primaryButtonClassName =
  "inline-flex min-h-11 items-center justify-center rounded-full bg-[#243c30] px-6 py-3 text-sm font-semibold text-white transition hover:bg-[#355642] disabled:cursor-not-allowed disabled:opacity-50";

export function FormError({ message }: { message: string }) {
  if (!message) return null;
  return (
    <p role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
      {message}
    </p>
  );
}

export async function responseError(response: Response): Promise<string> {
  if (response.status === 503) {
    return "Authentication is not configured. Set a strong JWT_SECRET in backend/.env and restart the backend.";
  }
  try {
    const body = await response.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      const issues = body.detail as { loc?: unknown[]; msg?: string; type?: string }[];
      const extraFields = [...new Set(issues
        .filter((item) => item.type === "extra_forbidden")
        .map((item) => item.loc?.at(-1))
        .filter((field): field is string => typeof field === "string"))];
      if (extraFields.length) {
        const message = issues.find((item) => item.type === "extra_forbidden")?.msg || "Unexpected inputs are not permitted";
        return `${message}: ${extraFields.join(", ")}.`;
      }
      return [...new Set(issues.map((item) => item.msg).filter((message): message is string => Boolean(message)))].join(" ");
    }
  } catch {
    // Fall through to a status-based message for non-JSON API responses.
  }
  return `The request failed (HTTP ${response.status}). Please try again.`;
}
