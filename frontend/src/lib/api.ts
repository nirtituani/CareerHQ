/**
 * Typed client for the CareerHQ API.
 *
 * Every request is same-origin — Next.js proxies /api/* to the backend — so
 * cookies are sent automatically and there is no CORS surface. The session
 * cookie is HttpOnly, so this code cannot read it; authentication state is
 * discovered by calling the API, never by inspecting document.cookie.
 */

export type User = {
  id: string;
  email: string;
  display_name: string | null;
  avatar_url: string | null;
  created_at: string;
};

export type Profile = {
  id: string;
  user_id: string;
  created_at: string;
  updated_at: string;
};

/** The API answered, but with an error status. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** The API could not be reached at all — distinct from it rejecting us. */
export class ApiUnreachableError extends Error {
  constructor(cause?: unknown) {
    super("The API is unreachable.");
    this.name = "ApiUnreachableError";
    this.cause = cause;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;

  try {
    response = await fetch(path, {
      ...init,
      credentials: "include",
      headers: { Accept: "application/json", ...init?.headers },
    });
  } catch (cause) {
    // fetch only rejects on network failure, not on a 4xx/5xx. Separating the
    // two matters: "not signed in" and "backend is down" need different
    // interfaces, and conflating them produces the classic bug where an outage
    // silently signs everyone out.
    throw new ApiUnreachableError(cause);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  if (!response.ok) {
    const detail = await response
      .json()
      .then((body: { detail?: string }) => body.detail)
      .catch(() => undefined);
    throw new ApiError(response.status, detail ?? response.statusText);
  }

  return (await response.json()) as T;
}

/**
 * The signed-in user, or null when there is no valid session.
 *
 * A 401 is an expected answer here, not an exception — "nobody is signed in"
 * is ordinary. Anything else propagates.
 */
export async function getCurrentUser(): Promise<User | null> {
  try {
    return await request<User>("/api/auth/me");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

export function getProfile(): Promise<Profile> {
  return request<Profile>("/api/profile");
}

export function logout(): Promise<void> {
  return request<void>("/api/auth/logout", { method: "POST" });
}

/** Where to send the browser to begin Google sign-in. */
export function loginUrl(next?: string): string {
  const params = next ? `?next=${encodeURIComponent(next)}` : "";
  return `/api/auth/google/login${params}`;
}
