import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { DetailTabs } from "@/components/applications/detail-tabs";
import { StatusPill } from "@/components/applications/status-pill";
import { ApiUnavailable } from "@/components/api-unavailable";
import { AppShell } from "@/components/app-shell";
import { ApiUnreachableError, type Application, type MatchResult, type User } from "@/lib/api";
import { fetchCurrentUser, fetchFromApi } from "@/lib/session";

export const dynamic = "force-dynamic";

/**
 * One application — docs/09 §6.3.
 *
 * **The header's `Tailor CV` button is gone, as of slice 005.** It sat there
 * disabled, titled "Resume tailoring arrives in the next release", on the
 * reasoning that a button which looks live and does nothing is worse than one
 * admitting it is not ready. That was right while it was true. Now tailoring
 * *is* built and lives one tab down, and a disabled primary action announcing
 * the opposite is worse than either — it tells a person the capability they are
 * looking at does not exist yet.
 *
 * It was not replaced with a live button. The action depends on tab state, so a
 * working one would have to hoist that state out of `DetailTabs` and into this
 * page, and what it would buy is a second way to reach a tab that is already in
 * the tab list and already unmarked. The tab is the affordance.
 *
 * Someone else's application arrives here as a 404, not a 403 (FR-019): the
 * backend does not confirm that the id names anything, and neither does this.
 */
export default async function ApplicationDetail({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let user: User | null;
  let application: Application | null;
  // Defaulted rather than left null: the four states already describe every
  // way an analysis can be absent, so a fetch that fails degrades to "nothing
  // to score" instead of taking the whole page down with it.
  let match: MatchResult = { state: "nothing_to_score", analysis: null, stale: false };

  try {
    user = await fetchCurrentUser();
    application = user ? await fetchFromApi<Application>(`/api/applications/${id}`) : null;
    if (application) {
      // `?? match` keeps the default: a 404 here means no analysis, which is
      // the `nothing_to_score` state rather than a broken page.
      match = (await fetchFromApi<MatchResult>(`/api/applications/${id}/match`)) ?? match;
    }
  } catch (error) {
    if (error instanceof ApiUnreachableError) return <ApiUnavailable />;
    throw error;
  }

  if (!user) redirect(`/login?next=/applications/${id}`);
  if (!application) notFound();

  const appliedOn = application.date_applied
    ? new Date(application.date_applied).toLocaleDateString(undefined, {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
      })
    : null;

  return (
    <AppShell user={user}>
      <Link
        href="/applications"
        className="mb-5 inline-flex items-center gap-1.5 text-sm"
        style={{ color: "var(--muted)" }}
      >
        <ArrowLeft className="size-4" aria-hidden />
        Applications
      </Link>

      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">
            {application.company.name}
            <span style={{ color: "var(--muted)" }}> · </span>
            <span className="font-normal">{application.job_title}</span>
          </h1>

          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm" style={{ color: "var(--muted)" }}>
            <StatusPill status={application.status} normalized={application.normalized_status} />
            {appliedOn && <span className="font-mono text-xs tabular-nums">{appliedOn}</span>}
            {application.source && <span>· {application.source}</span>}
          </div>
        </div>
      </div>

      <DetailTabs application={application} match={match} />
    </AppShell>
  );
}
