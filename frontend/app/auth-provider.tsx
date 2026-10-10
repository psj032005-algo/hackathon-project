"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type PropsWithChildren,
} from "react";
import { useRouter } from "next/navigation";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8002";

export class SessionExpiredError extends Error {
  constructor() {
    super("Your session expired. Please sign in again.");
    this.name = "SessionExpiredError";
  }
}

type AuthContextValue = {
  token: string | null;
  ready: boolean;
  sessionNotice: string;
  setSession: (token: string) => void;
  logout: () => void;
  authorizedFetch: (path: string, init?: RequestInit) => Promise<Response>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function subscribeToNothing() {
  return () => {};
}

function getClientReadySnapshot() {
  return true;
}

function getServerReadySnapshot() {
  return false;
}

function readTokenExpiry(token: string): number | null {
  try {
    const payloadPart = token.split(".")[1];
    if (!payloadPart) return null;
    const base64 = payloadPart.replace(/-/g, "+").replace(/_/g, "/");
    const payload = JSON.parse(window.atob(base64.padEnd(Math.ceil(base64.length / 4) * 4, "=")));
    return typeof payload.exp === "number" ? payload.exp * 1000 : null;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: PropsWithChildren) {
  const router = useRouter();
  // The access token stays in memory; it is never written to local/session storage.
  const [token, setToken] = useState<string | null>(null);
  const [sessionNotice, setSessionNotice] = useState("");
  const ready = useSyncExternalStore(
    subscribeToNothing,
    getClientReadySnapshot,
    getServerReadySnapshot,
  );

  const endSession = useCallback(
    (expired: boolean) => {
      setToken(null);
      setSessionNotice(expired ? "Your session expired. Please sign in again." : "");
      router.replace("/owner/login");
    },
    [router],
  );

  useEffect(() => {
    if (!token) return;
    const expiry = readTokenExpiry(token);
    if (!expiry || expiry <= Date.now()) {
      const timer = window.setTimeout(() => endSession(true), 0);
      return () => window.clearTimeout(timer);
    }

    const timer = window.setTimeout(() => endSession(true), expiry - Date.now());
    return () => window.clearTimeout(timer);
  }, [token, endSession]);

  const authorizedFetch = useCallback(
    async (path: string, init: RequestInit = {}) => {
      if (!token) throw new SessionExpiredError();
      const headers = new Headers(init.headers);
      headers.set("Authorization", `Bearer ${token}`);
      if (init.body && !headers.has("Content-Type")) {
        headers.set("Content-Type", "application/json");
      }

      const response = await fetch(`${API_BASE}${path}`, {
        ...init,
        headers,
        cache: "no-store",
      });
      if (response.status === 401) {
        endSession(true);
        throw new SessionExpiredError();
      }
      return response;
    },
    [token, endSession],
  );

  const value = useMemo(
    () => ({
      token,
      ready,
      sessionNotice,
      setSession: (nextToken: string) => {
        setSessionNotice("");
        setToken(nextToken);
      },
      logout: () => endSession(false),
      authorizedFetch,
    }),
    [token, ready, sessionNotice, endSession, authorizedFetch],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
