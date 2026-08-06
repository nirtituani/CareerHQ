import { redirect } from "next/navigation";
import { cookies } from "next/headers";

import { ApiUnavailable } from "@/components/api-unavailable";
import { AppShell } from "@/components/app-shell";
import { ApiUnreachableError, type User } from "@/lib/api";

export const dynamic = "force-dynamic";

/**
 * Fetch the signed-in user from the server component.
 *
 * Server components have no browser to attach cookies for them, so the session
 * cookie is forwarded explicitly, and the backend is called directly rather
 * than through the proxy (there is no origin to be relative to on the server).
 */
async function fetchCurrentUser(): Promise<User | null> {
  const cookieStore = await cookies();
  const backend = process.env.BACKEND_URL ?? "http://localhost:8000";

  const response = await fetch(`${backend}/api/auth/me`, {
    headers: { cookie: cookieStore.toString() },
    cache: "no-store",
  }).catch((cause) => {
    throw new ApiUnreachableError(cause);
  });

  if (response.status === 401) return null;
  if (!response.ok) throw new Error(`Unexpected ${response.status} from /api/auth/me`);
  return (await response.json()) as User;
}

export default async function DashboardPage() {
  let user: User | null;

  try {
    user = await fetchCurrentUser();
  } catch (error) {
    if (error instanceof ApiUnreachableError) return <ApiUnavailable />;
    throw error;
  }

  if (!user) redirect("/login?next=/dashboard");

  return (
    <AppShell user={user}>
      <div className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">
          Welcome{user.display_name ? `, ${user.display_name.split(" ")[0]}` : ""}
        </h1>
        <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
          Your workspace is ready. There is nothing here yet.
        </p>
      </div>

      <div
        className="rounded-xl border border-dashed p-10 text-center"
        style={{ borderColor: "var(--border)" }}
      >
        <h2 className="text-base font-medium">Nothing to show yet</h2>
        <p className="mx-auto mt-2 max-w-md text-sm" style={{ color: "var(--muted)" }}>
          Once the next releases land, this is where your applications, tailored resumes, and
          career insights will appear.
        </p>

        <ul
          className="mx-auto mt-6 grid max-w-md gap-2 text-left text-sm"
          style={{ color: "var(--muted)" }}
        >
          <li>• Import your CV to build your professional profile</li>
          <li>• Track every application in one place</li>
          <li>• Tailor your resume to a job description, with your approval on every change</li>
          <li>• See which skills keep coming up in the roles you want</li>
        </ul>
      </div>
    </AppShell>
  );
}
