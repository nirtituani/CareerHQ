import { redirect } from "next/navigation";

import { ApiUnavailable } from "@/components/api-unavailable";
import { AppShell } from "@/components/app-shell";
import { ImportFlow } from "@/components/import-review/import-flow";
import { ApiUnreachableError, type User } from "@/lib/api";
import { fetchCurrentUser } from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function ImportPage() {
  let user: User | null;
  try {
    user = await fetchCurrentUser();
  } catch (error) {
    if (error instanceof ApiUnreachableError) return <ApiUnavailable />;
    throw error;
  }
  if (!user) redirect("/login?next=/import");

  return (
    <AppShell user={user}>
      <div className="mb-8">
        <h1 className="text-2xl tracking-tight" style={{ fontFamily: "var(--font-display)" }}>
          Import your CV
        </h1>
        <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
          Nothing is saved until you review it and say so.
        </p>
      </div>

      <ImportFlow />
    </AppShell>
  );
}
