"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
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
  const redirectToSetup = useRef(false);
  const [storeName, setStoreName] = useState("");
  const [storeSlug, setStoreSlug] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [businessType, setBusinessType] = useState("Home goods");
  const [addressLine1, setAddressLine1] = useState("");
  const [addressLine2, setAddressLine2] = useState("");
  const [city, setCity] = useState("");
  const [region, setRegion] = useState("");
  const [postalCode, setPostalCode] = useState("");
  const [country, setCountry] = useState("India");
  const [contactEmail, setContactEmail] = useState("");
  const [contactPhone, setContactPhone] = useState("");
  const [step, setStep] = useState(1);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (ready && token) router.replace(redirectToSetup.current ? "/owner/setup" : "/owner/dashboard");
  }, [ready, token, router]);

  function updateStoreName(value: string) {
    setStoreName(value);
    if (!slugEdited) setStoreSlug(slugify(value));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (step < 3) {
      setStep((current) => current + 1);
      return;
    }
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
          business_type: businessType,
          address_line1: addressLine1.trim(),
          address_line2: addressLine2.trim(),
          city: city.trim(),
          region: region.trim(),
          postal_code: postalCode.trim(),
          country: country.trim(),
          contact_email: contactEmail.trim(),
          contact_phone: contactPhone.trim(),
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
      redirectToSetup.current = true;
      setSession(result.access_token);
      router.replace("/owner/setup");
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
          A few quick details set up your owner account and storefront. You can publish when you are ready.
        </p>
        <OwnerPanel className="mt-8">
          <form onSubmit={submit} className="space-y-5">
            <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-[0.14em] text-gray-500" aria-live="polite">
              <span>Step {step} of 3</span><span>{[1, 2, 3].map((item) => <span key={item} className={`ml-2 inline-block h-2 w-8 rounded-full ${item <= step ? "bg-[#243c30]" : "bg-[#deddd5]"}`} />)}</span>
            </div>
            <FormError message={error} />
            {step === 1 && <>
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
            <FormField label="Business type">
              <select className={inputClassName} value={businessType} onChange={(event) => setBusinessType(event.target.value)}>
                {["Home goods", "Clothing & accessories", "Food & beverage", "Wellness", "Arts & crafts", "Other"].map((type) => <option key={type}>{type}</option>)}
              </select>
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
            </>}
            {step === 2 && <>
              <p className="text-sm text-gray-600">Where is your business based? Contact details can be changed later.</p>
              <FormField label="Street address"><input className={inputClassName} required maxLength={200} autoComplete="street-address" value={addressLine1} onChange={(e) => setAddressLine1(e.target.value)} /></FormField>
              <FormField label="Address line 2 (optional)"><input className={inputClassName} maxLength={200} value={addressLine2} onChange={(e) => setAddressLine2(e.target.value)} /></FormField>
              <div className="grid gap-4 sm:grid-cols-2">
                <FormField label="City"><input className={inputClassName} required maxLength={120} autoComplete="address-level2" value={city} onChange={(e) => setCity(e.target.value)} /></FormField>
                <FormField label="State / region"><input className={inputClassName} required maxLength={120} autoComplete="address-level1" value={region} onChange={(e) => setRegion(e.target.value)} /></FormField>
                <FormField label="Postal code"><input className={inputClassName} required maxLength={32} autoComplete="postal-code" value={postalCode} onChange={(e) => setPostalCode(e.target.value)} /></FormField>
                <FormField label="Country"><input className={inputClassName} required maxLength={120} autoComplete="country-name" value={country} onChange={(e) => setCountry(e.target.value)} /></FormField>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <FormField label="Store contact email"><input className={inputClassName} type="email" maxLength={254} autoComplete="email" value={contactEmail} onChange={(e) => setContactEmail(e.target.value)} /></FormField>
                <FormField label="Store contact phone"><input className={inputClassName} type="tel" maxLength={40} autoComplete="tel" value={contactPhone} onChange={(e) => setContactPhone(e.target.value)} /></FormField>
              </div>
            </>}
            {step === 3 && <>
              <p className="text-sm text-gray-600">Create the owner sign-in for {storeName || "your store"}.</p>
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
            </>}
            <div className="flex gap-3">
              {step > 1 && <button type="button" className="w-1/3 rounded-full border border-[#d9d8cf] px-5 py-3 text-sm font-semibold" onClick={() => setStep((current) => current - 1)}>Back</button>}
            <button className={`${primaryButtonClassName} w-full`} disabled={submitting}>
              {submitting ? "Creating your store…" : step < 3 ? "Continue" : "Create store"}
            </button>
            </div>
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
