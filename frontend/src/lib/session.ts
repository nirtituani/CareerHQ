import { cookies } from "next/headers";

import { ApiUnreachableError, type User } from "@/lib/api";

/**
 * The signed-in user, resolved in a server component.
 *
 * Server components have no browser to attach cookies for them, so the session
 * cookie is forwarded explicitly, and the backend is called directly rather
 * than through the proxy — there is no origin to be relative to on the server.
 *
 * Extracted from the dashboard page when a third screen needed it. Copying it
 * once more would have been the moment the copies started to drift.
 */
export async function fetchCurrentUser(): Promise<User | null> {
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

/**
 * Fetch any API path in a server component, forwarding the session cookie.
 *
 * Same reasoning as `fetchCurrentUser` above, generalised when the
 * applications screens needed a second and third resource. A 404 returns null
 * — "no such application, or not yours" is an ordinary answer the page turns
 * into `notFound()`, not an exception.
 */
export async function fetchFromApi<T>(path: string): Promise<T | null> {
  const cookieStore = await cookies();
  const backend = process.env.BACKEND_URL ?? "http://localhost:8000";

  const response = await fetch(`${backend}${path}`, {
    headers: { cookie: cookieStore.toString() },
    cache: "no-store",
  }).catch((cause) => {
    throw new ApiUnreachableError(cause);
  });

  if (response.status === 404 || response.status === 401) return null;
  if (!response.ok) throw new Error(`Unexpected ${response.status} from ${path}`);
  return (await response.json()) as T;
}
