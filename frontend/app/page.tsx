"use client";

import { useEffect, useState } from "react";

type BackendStatus = "loading" | "ok" | "error";

export default function Home() {
  const [backendStatus, setBackendStatus] = useState<BackendStatus>("loading");

  useEffect(() => {
    fetch("http://localhost:8000/api/health")
      .then((response) => {
        if (!response.ok) {
          throw new Error("Backend request failed");
        }

        return response.json();
      })
      .then((data) => {
        if (data.status === "ok") {
          setBackendStatus("ok");
        } else {
          setBackendStatus("error");
        }
      })
      .catch((error) => {
        console.error("Backend connection error:", error);
        setBackendStatus("error");
      });
  }, []);

  return (
    <main className="min-h-screen flex items-center justify-center bg-gray-100">
      <div className="w-full max-w-md rounded-2xl bg-white p-10 shadow-lg text-center">
        <h1 className="text-3xl font-bold text-gray-900">
          Hackathon Boilerplate
        </h1>

        <p className="mt-3 text-gray-600">Frontend ↔ Backend Connection Test</p>

        <div className="mt-8">
          {backendStatus === "loading" && (
            <div className="rounded-lg bg-yellow-100 px-6 py-4 text-yellow-800">
              🟡 Connecting to backend...
            </div>
          )}

          {backendStatus === "ok" && (
            <div className="rounded-lg bg-green-100 px-6 py-4 text-green-800">
              🟢 Backend Connected
            </div>
          )}

          {backendStatus === "error" && (
            <div className="rounded-lg bg-red-100 px-6 py-4 text-red-800">
              🔴 Backend Connection Failed
            </div>
          )}
        </div>

        <div className="mt-6 text-sm text-gray-500">
          <p>Frontend: localhost:3000</p>
          <p>Backend: localhost:8000</p>
          <p>Endpoint: /api/health</p>
        </div>
      </div>
    </main>
  );
}
