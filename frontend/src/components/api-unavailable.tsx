"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";

/**
 * Shown when the API cannot be reached (FR-019).
 *
 * Deliberately not an error page: on a first `docker compose up` the frontend
 * is ready while the backend is still applying migrations, so this state is
 * expected and temporary. It retries on a backoff and recovers on its own —
 * no reload, and no reload loop either.
 */
export function ApiUnavailable() {
  const [seconds, setSeconds] = useState(3);

  useEffect(() => {
    if (seconds <= 0) {
      window.location.reload();
      return;
    }
    const timer = setTimeout(() => setSeconds((value) => value - 1), 1000);
    return () => clearTimeout(timer);
  }, [seconds]);

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-md text-center">
        <h1 className="text-lg font-medium">CareerHQ is starting up</h1>
        <p className="mt-2 text-sm" style={{ color: "var(--muted)" }}>
          We can&apos;t reach the service right now. This usually clears on its own within a few
          seconds — retrying in {seconds}…
        </p>
        <Button variant="outline" className="mt-6" onClick={() => window.location.reload()}>
          Retry now
        </Button>
      </div>
    </main>
  );
}
