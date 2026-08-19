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

// ---------------------------------------------------------------------------
// Applications
// ---------------------------------------------------------------------------

/**
 * The analytics category, derived from the user's label by the backend.
 *
 * Never sent *to* the API. It is derived from `status` server-side (FR-013),
 * because a client-settable normalized status is a second source of truth for
 * the same fact and the two drift the first time one is written without the
 * other.
 */
export type NormalizedStatus =
  | "wishlist"
  | "applied"
  | "interviewing"
  | "offer"
  | "rejected"
  | "withdrawn"
  | "ghosted"
  | "other";

export type StatusChange = {
  from_status: string | null;
  to_status: string;
  normalized_to_status: NormalizedStatus;
  changed_at: string;
  note: string | null;
};

export type Application = {
  id: string;
  company: { id: string; name: string; domain: string | null };
  job_title: string;
  location: string | null;
  /** The **full posting**, which match analysis scores against. */
  job_description: string | null;
  /**
   * What the posting asks of the candidate.
   *
   * `null` and `[]` are different facts. `null` means no posting was ever
   * captured — a row recorded before slice 004, whose `job_description` holds a
   * joined requirements list rather than an advert. `[]` means the posting was
   * read and stated none. Only `null` rows are unscoreable for want of a
   * posting, so collapsing these loses the thing that tells them apart.
   */
  requirements: string[] | null;
  /** Computed against the profile. Never `imported_match_rating`, which is the
   *  person's own 1–5 judgement and a separate fact (FR-013). */
  match?: MatchSummary;
  job_url: string | null;
  job_description_url: string | null;
  /** The user's own words, verbatim. */
  status: string;
  normalized_status: NormalizedStatus;
  date_added: string;
  date_applied: string | null;
  source: string | null;
  /** Free text: the source stores "90-110k" and "competitive" alike. */
  salary_text: string | null;
  /** 0 means unset. Preserved from a JobTracker import. */
  imported_match_rating: number;
  contact_name: string | null;
  contact_email: string | null;
  notes: string | null;
  import_source: string | null;
  archived_at: string | null;
  status_history: StatusChange[];
};

export type MatchSummary = {
  state: "running" | "ready" | "failed" | "nothing_to_score";
  band: "strong" | "moderate" | "stretch" | "low_probability" | null;
  overall_score: number | null;
};

/** Fields a client may write. `normalized_status` is deliberately absent. */
export type ApplicationInput = {
  company: string;
  job_title: string;
  /** Belongs to the employer, so a second job there inherits it. */
  company_domain?: string;
  job_description?: string;
  requirements?: string[];
  location?: string;
  status?: string;
  /** When the job was recorded — the staleness signal for a Pre-Applied row. */
  date_added?: string;
  /** When it was actually applied to. Null until then; never the same fact. */
  date_applied?: string;
  job_url?: string;
  /** The posting link, filled in automatically after a fetch. */
  job_description_url?: string;
  /** "Applied Via" — only meaningful once the status is Applied or later. */
  source?: string;
  salary_text?: string;
  contact_name?: string;
  contact_email?: string;
  notes?: string;
};

export function listApplications(): Promise<{ applications: Application[] }> {
  return request<{ applications: Application[] }>("/api/applications");
}

export function getApplication(id: string): Promise<Application> {
  return request<Application>(`/api/applications/${id}`);
}

export function createApplication(input: ApplicationInput): Promise<Application> {
  return request<Application>("/api/applications", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function updateApplication(
  id: string,
  changes: Partial<ApplicationInput>,
): Promise<Application> {
  return request<Application>(`/api/applications/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(changes),
  });
}

/** Fields read off a posting. Every one optional — a posting may name none. */
export type JobPostingExtraction = {
  company: string | null;
  job_title: string | null;
  location: string | null;
  salary_text: string | null;
  job_description: string | null;
  company_domain: string | null;
};

/**
 * How the fields were obtained.
 *
 * `structured_data` means the employer published them in the page and they were
 * read exactly, with no model call. `model` means a model read the page text.
 * The form marks the difference, because they deserve different trust.
 */
export type ExtractionProvenance = "structured_data" | "model" | "manual";

export type JobExtraction = {
  posting: JobPostingExtraction;
  provenance: ExtractionProvenance;
  usage: { model: string; cost: string; is_fixture: boolean } | null;
};

/**
 * Read a posting into form fields. **Saves nothing** — the person confirms it.
 *
 * Throws `ApiError` with a readable message when a site refuses automated
 * access, which is the common case on the large job boards. The caller turns
 * that into the offer to paste the posting text instead.
 */
export function extractJob(input: { url?: string; text?: string }): Promise<JobExtraction> {
  return request<JobExtraction>("/api/applications/extract", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

/** Undo a rejection, restoring the status held before it (appends history). */
export function unrejectApplication(id: string): Promise<Application> {
  return request<Application>(`/api/applications/${id}/unreject`, { method: "POST" });
}

export function deleteApplication(id: string): Promise<void> {
  return request<void>(`/api/applications/${id}`, { method: "DELETE" });
}
