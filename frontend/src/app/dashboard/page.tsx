import Link from "next/link";
import { redirect } from "next/navigation";

import { ApplicationsView } from "@/components/applications/applications-view";
import { ApiUnavailable } from "@/components/api-unavailable";
import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { ApiUnreachableError, type Application, type User } from "@/lib/api";
import { fetchCurrentUser, fetchFromApi } from "@/lib/session";

export const dynamic = "force-dynamic";

/**
 * The dashboard — docs/09 §6.1.
 *
 * Four stat tiles over a filtered table. **The tiles are filters, not
 * decoration**: clicking one filters the table beneath it and the active tile
 * is visibly selected, carried over from JobTracker where `StatsCards` already
 * rendered each tile as a button.
 *
 * Deferred deliberately (docs/09 §6.1): "what needs attention" and recent
 * activity. Both are useful and neither is required by any functional
 * requirement, so slice 003 ships the tiles and the filtered table only.
 */
export default async function DashboardPage() {
  let user: User | null;
  let applications: Application[];

  try {
    user = await fetchCurrentUser();
    applications = user
      ? ((await fetchFromApi<{ applications: Application[] }>("/api/applications"))
          ?.applications ?? [])
      : [];
  } catch (error) {
    if (error instanceof ApiUnreachableError) return <ApiUnavailable />;
    throw error;
  }

  if (!user) redirect("/login?next=/dashboard");

  return (
    <AppShell user={user}>
      <div className="mb-8 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Welcome{user.display_name ? `, ${user.display_name.split(" ")[0]}` : ""}
          </h1>
          <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
            {applications.length === 0
              ? "Import your CV, then record the jobs you are going after."
              : "Where everything stands today."}
          </p>
        </div>

        <div className="flex gap-2">
          <Button asChild variant="outline">
            <Link href="/import">Import a CV</Link>
          </Button>
          <Button asChild>
            <Link href="/applications">Record a job</Link>
          </Button>
        </div>
      </div>

      <ApplicationsView applications={applications} showTiles />
    </AppShell>
  );
}
