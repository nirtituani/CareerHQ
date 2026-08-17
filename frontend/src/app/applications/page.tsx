import { redirect } from "next/navigation";

import { ApplicationsPage } from "@/components/applications/applications-page";
import { ApiUnavailable } from "@/components/api-unavailable";
import { AppShell } from "@/components/app-shell";
import { ApiUnreachableError, type Application, type User } from "@/lib/api";
import { fetchCurrentUser, fetchFromApi } from "@/lib/session";

export const dynamic = "force-dynamic";

/** The full table — docs/09 §6.2. Dashboard answers "what should I do today". */
export default async function Applications() {
  let user: User | null;
  let applications: Application[];

  try {
    user = await fetchCurrentUser();
    // Only fetched once there is a session; kept inside the try because both
    // calls fail the same way when the API is down.
    applications = user
      ? ((await fetchFromApi<{ applications: Application[] }>("/api/applications"))
          ?.applications ?? [])
      : [];
  } catch (error) {
    if (error instanceof ApiUnreachableError) return <ApiUnavailable />;
    throw error;
  }

  // Outside the try: `redirect` signals by throwing, and a catch that inspects
  // the error would have to know not to swallow it.
  if (!user) redirect("/login?next=/applications");

  return (
    <AppShell user={user}>
      <ApplicationsPage applications={applications} />
    </AppShell>
  );
}
