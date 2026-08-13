import { redirect } from "next/navigation";

import { ApiUnavailable } from "@/components/api-unavailable";
import { AppShell } from "@/components/app-shell";
import { ImportFlow } from "@/components/import-review/import-flow";
import { cookies } from "next/headers";

import { ApiUnreachableError, type User } from "@/lib/api";
import type { ImportedResume } from "@/lib/imports";
import { fetchCurrentUser } from "@/lib/session";

export const dynamic = "force-dynamic";

/**
 * Load a review already in progress.
 *
 * Without this a refresh, a closed tab, or a laptop lid mid-review meant
 * re-uploading and paying for extraction again — on a screen designed for
 * working through several dozen items, which is exactly when an interruption
 * is likely.
 */
async function fetchImport(id: string): Promise<ImportedResume | null> {
  const cookieStore = await cookies();
  const backend = process.env.BACKEND_URL ?? "http://localhost:8000";
  const response = await fetch(`${backend}/api/imports/${id}`, {
    headers: { cookie: cookieStore.toString() },
    cache: "no-store",
  }).catch((cause) => {
    throw new ApiUnreachableError(cause);
  });
  if (!response.ok) return null;
  return (await response.json()) as ImportedResume;
}

export default async function ImportPage({
  searchParams,
}: {
  searchParams: Promise<{ id?: string }>;
}) {
  let user: User | null;
  try {
    user = await fetchCurrentUser();
  } catch (error) {
    if (error instanceof ApiUnreachableError) return <ApiUnavailable />;
    throw error;
  }
  if (!user) redirect("/login?next=/import");

  const { id } = await searchParams;
  const resumed = id ? await fetchImport(id) : null;

  return (
    <AppShell user={user}>
      <div className="mb-8">
        <h1 className="text-2xl tracking-tight" style={{ fontFamily: "var(--font-display)" }}>
          Import your CV
        </h1>
        <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
          {resumed ? "Picking up where you left off." : "Nothing is saved until you review it and say so."}
        </p>
      </div>

      <ImportFlow initial={resumed} />
    </AppShell>
  );
}
