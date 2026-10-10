"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { useAuth } from "../../auth-provider";
import {
  API_BASE,
  FormError,
  FormField,
  inputClassName,
  OwnerFrame,
  OwnerPanel,
  primaryButtonClassName,
  responseError,
} from "../owner-ui";

function slugify(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 80);
}

export default function OwnerRegisterPage() {
  const router = useRouter();
  const { ready, token, setSession } = useAuth();
  const [storeName, setStoreName] = useState("");
  const [storeSlug, setStoreSlug] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (ready && token) router.replace("/owner/dashboard");
  }, [ready, token, router]);

  function updateStoreName(value: string) {
    setStoreName(value);
    if (!slugEdited) setStoreSlug(slugify(value));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const response = await fetch(`${API_BASE}/api/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: email.trim(),
          password,
          store_name: storeName.trim(),
          store_slug: storeSlug.trim().toLowerCase(),
        }),
        cache: "no-store",
      });
      if (!response.ok) {
        setError(
          response.status === 409
            ? "That email or store address is already in use. Try signing in or choose another."
            : await responseError(response),
        );
        return;
      }
      const result: { access_token?: string } = await response.json();
      if (!result.access_token) {
        setError("Your account was created, but sign-in could not be completed. Please sign in.");
        router.replace("/owner/login");
        return;
      }
      setSession(result.access_token);
      router.replace("/owner/dashboard");
    } catch {
      setError("Could not connect to the store service. Check that the backend is running.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <OwnerFrame eyebrow="START SOMETHING LOVELY">
      <div className="mx-auto mt-6 max-w-xl">
        <h1 className="text-4xl font-medium tracking-tight sm:text-5xl">Create your store.</h1>
        <p className="mt-4 text-base leading-7 text-gray-600">
          Set up your owner account and store address. You can publish when you are ready.
        </p>
        <OwnerPanel className="mt-8">
          <form onSubmit={submit} className="space-y-5">
            <FormError message={error} />
            <FormField label="Store name">
              <input
                className={inputClassName}
                autoComplete="organization"
                required
                minLength={1}
                maxLength={120}
                value={storeName}
                onChange={(event) => updateStoreName(event.target.value)}
              />
            </FormField>
            <FormField label="Store address" hint="Use lowercase letters, numbers, and hyphens.">
              <div className="flex overflow-hidden rounded-xl border border-[#d9d8cf] bg-[#fffefa] focus-within:border-[#607c62] focus-within:ring-2 focus-within:ring-[#607c62]/15">
                <span className="flex items-center border-r border-[#e6e2d9] px-3 text-sm text-gray-500">/stores/</span>
                <input
                  className="min-w-0 flex-1 bg-transparent px-3 py-3 text-sm outline-none"
                  autoComplete="off"
                  required
                  pattern="[a-z0-9]+(-[a-z0-9]+)*"
                  maxLength={80}
                  value={storeSlug}
                  onChange={(event) => {
                    setSlugEdited(true);
                    setStoreSlug(event.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""));
                  }}
                />
              </div>
            </FormField>
            <FormField label="Email address">
              <input
                className={inputClassName}
                type="email"
                autoComplete="email"
                required
                maxLength={254}
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </FormField>
            <FormField label="Password" hint="Use at least 12 characters.">
              <input
                className={inputClassName}
                type="password"
                autoComplete="new-password"
                required
                minLength={12}
                maxLength={128}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </FormField>
            <button className={`${primaryButtonClassName} w-full`} disabled={submitting}>
              {submitting ? "Creating your store…" : "Create store"}
            </button>
          </form>
          <p className="mt-6 text-center text-sm text-gray-600">
            Already have an account?{" "}
            <Link href="/owner/login" className="font-semibold text-[#243c30] underline underline-offset-4">
              Sign in
            </Link>
          </p>
        </OwnerPanel>
      </div>
    </OwnerFrame>
  );
}
