import { redirect } from "next/navigation";

import { AdvisorView } from "@/components/advisor/advisor-view";
import { ApiUnavailable } from "@/components/api-unavailable";
import { AppShell } from "@/components/app-shell";
import { ApiUnreachableError, type User } from "@/lib/api";
import { fetchCurrentUser } from "@/lib/session";

export const dynamic = "force-dynamic";

/**
 * The Career Advisor's dedicated page (slice 009, clarification Q5) — the
 * navigation entry that was marked *Soon* since slice 003, activated in the
 * same slice that makes it real.
 *
 * The server half only authenticates; the memory state, run lifecycle and
 * dismissal all live in the client view, which polls a run while it is in
 * flight and keeps serving the previous memories through a failure.
 */
export default async function AdvisorPage() {
  let user: User | null;
  try {
    user = await fetchCurrentUser();
  } catch (error) {
    if (error instanceof ApiUnreachableError) return <ApiUnavailable />;
    throw error;
  }
  if (!user) redirect("/login?next=/advisor");

  return (
    <AppShell user={user}>
      <AdvisorView />
    </AppShell>
  );
}
