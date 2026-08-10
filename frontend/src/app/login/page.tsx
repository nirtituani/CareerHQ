import Link from "next/link";

import { GoogleIcon } from "@/components/google-icon";
import { Button } from "@/components/ui/button";
import { loginUrl } from "@/lib/api";

/** Messages for the reasons Google can send the user back. */
const ERRORS: Record<string, string> = {
  access_denied: "Sign-in was cancelled. Nothing was saved.",
  session_expired: "Your session expired. Please sign in again.",
};

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; next?: string }>;
}) {
  const { error, next } = await searchParams;
  const message = error ? (ERRORS[error] ?? "Sign-in could not be completed.") : null;

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-sm">
        <div className="mb-10 text-center">
          <h1 className="text-2xl font-semibold tracking-tight text-brand-700">CareerHQ</h1>
          <p className="mt-2 text-sm" style={{ color: "var(--muted)" }}>
            Your AI-powered headquarters for every job application.
          </p>
        </div>

        {message && (
          <div
            role="alert"
            className="mb-6 rounded-lg border px-4 py-3 text-sm"
            style={{ borderColor: "var(--border)", color: "var(--muted)" }}
          >
            {message}
          </div>
        )}

        <Button asChild size="lg" className="w-full">
          {/* A plain link, not fetch(): the OAuth flow is a full-page redirect
              to Google and back, which an XHR cannot perform. */}
          <a href={loginUrl(next)}>
            <GoogleIcon className="size-4" />
            Continue with Google
          </a>
        </Button>

        <p className="mt-8 text-center text-xs" style={{ color: "var(--muted)" }}>
          By continuing you agree that CareerHQ stores your professional profile so it can
          tailor resumes on your behalf. You approve every change before it is applied.
        </p>

        <p className="mt-4 text-center text-xs">
          <Link href="/" className="underline underline-offset-4" style={{ color: "var(--muted)" }}>
            Back
          </Link>
        </p>
      </div>
    </main>
  );
}
