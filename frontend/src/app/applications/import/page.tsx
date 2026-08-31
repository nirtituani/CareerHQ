import { redirect } from "next/navigation";

import { ApiUnavailable } from "@/components/api-unavailable";
import { AppShell } from "@/components/app-shell";
import { JobtrackerImport } from "@/components/applications/jobtracker-import";
import { ApiUnreachableError, type User } from "@/lib/api";
import { fetchCurrentUser } from "@/lib/session";

export const dynamic = "force-dynamic";

/**
 * T083 — the import screen over the endpoint T084 exercised in production.
 *
 * **Declared under `/applications`, not beside `/import`.** `/import` is the CV
 * extraction flow; this imports *application history*. The two upload a file
 * and share nothing else — different endpoint, different data, different
 * outcome vocabulary — and putting them on one screen would make a person
 * choose between them before knowing which they wanted.
 */
export default async function JobtrackerImportPage() {
  let user: User | null;
  try {
    user = await fetchCurrentUser();
  } catch (error) {
    if (error instanceof ApiUnreachableError) return <ApiUnavailable />;
    throw error;
  }
  if (!user) redirect("/login?next=/applications/import");

  return (
    <AppShell user={user}>
      <div className="mb-8">
        <h1 className="text-2xl tracking-tight" style={{ fontFamily: "var(--font-display)" }}>
          Import from JobTracker
        </h1>
        <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
          Bring your application history across. Nothing already here is replaced.
        </p>
      </div>

      <JobtrackerImport />
    </AppShell>
  );
}
