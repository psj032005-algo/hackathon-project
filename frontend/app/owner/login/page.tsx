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

export default function OwnerLoginPage() {
  const router = useRouter();
  const { ready, token, setSession, sessionNotice } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (ready && token) router.replace("/owner/dashboard");
  }, [ready, token, router]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const response = await fetch(`${API_BASE}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim(), password }),
        cache: "no-store",
      });
      if (!response.ok) {
        setError(
          response.status === 401
            ? "That email and password do not match. Please try again."
            : await responseError(response),
        );
        return;
      }
      const result: { access_token?: string } = await response.json();
      if (!result.access_token) {
        setError("The sign-in response was incomplete. Please try again.");
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
    <OwnerFrame eyebrow="WELCOME BACK">
      <div className="mx-auto mt-6 max-w-lg">
        <h1 className="text-4xl font-medium tracking-tight sm:text-5xl">Sign in to your store.</h1>
        <p className="mt-4 text-base leading-7 text-gray-600">
          Manage your store details and decide when it is ready to go live.
        </p>
        <OwnerPanel className="mt-8">
          <form onSubmit={submit} className="space-y-5">
            {sessionNotice && <p role="status" className="rounded-xl bg-[#eef1e9] px-4 py-3 text-sm text-[#243c30]">{sessionNotice}</p>}
            <FormError message={error} />
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
            <FormField label="Password">
              <input
                className={inputClassName}
                type="password"
                autoComplete="current-password"
                required
                maxLength={128}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </FormField>
            <button className={`${primaryButtonClassName} w-full`} disabled={submitting}>
              {submitting ? "Signing in…" : "Sign in"}
            </button>
          </form>
          <p className="mt-6 text-center text-sm text-gray-600">
            New to Little Market?{" "}
            <Link href="/owner/register" className="font-semibold text-[#243c30] underline underline-offset-4">
              Create a store
            </Link>
          </p>
        </OwnerPanel>
      </div>
    </OwnerFrame>
  );
}
