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
/** Whether the profile already holds anything, so a repeat import can say so. */
async function profileHasContent(): Promise<boolean> {
  const cookieStore = await cookies();
  const backend = process.env.BACKEND_URL ?? "http://localhost:8000";
  const response = await fetch(`${backend}/api/profile/content`, {
    headers: { cookie: cookieStore.toString() },
    cache: "no-store",
  }).catch(() => null);

  if (!response?.ok) return false;
  const content = (await response.json()) as Record<string, unknown[]>;
  return ["work_experience", "skills", "titles", "education"].some(
    (key) => (content[key]?.length ?? 0) > 0,
  );
}

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
  const isRepeat = await profileHasContent();

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

      {isRepeat && !resumed && (
        // Said before the upload, not after. Someone importing a second CV
        // reasonably fears it will duplicate or overwrite what they already
        // corrected — and until FR-009's merge existed, the first of those
        // fears was justified.
        <div
          className="mb-6 rounded-md py-3 pr-4 text-sm"
          style={{
            borderLeft: "2px solid var(--color-brand-500)",
            paddingLeft: "0.75rem",
          }}
        >
          <p className="font-medium">You already have a profile</p>
          <p className="mt-1" style={{ color: "var(--muted)" }}>
            This CV will be merged into it. Anything already there stays as it is — including
            corrections you made — and only what is genuinely new gets added. Nothing is
            replaced without you seeing it first.
          </p>
        </div>
      )}

      <ImportFlow initial={resumed} />
    </AppShell>
  );
}
