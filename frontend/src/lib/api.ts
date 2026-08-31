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
    /**
     * The `detail` the API sent, unflattened.
     *
     * Usually a string, and then this says nothing `message` does not. But a
     * refusal that needs the caller to *act* differently carries a structured
     * detail — `{ reason, message }` — because a client that has to
     * pattern-match on a sentence gets it wrong the first time the sentence is
     * reworded. Tailoring's two 422s are the case: "run a match analysis" and
     * "re-run it, your profile changed" are the same status code and different
     * next steps.
     */
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** The human-readable half of a `detail`, whatever shape it arrived in. */
function messageOf(detail: unknown): string | undefined {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail) {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === "string") return message;
  }
  return undefined;
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
      .then((body: { detail?: unknown }) => body.detail)
      .catch(() => undefined);
    throw new ApiError(response.status, messageOf(detail) ?? response.statusText, detail);
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
  /**
   * Whether there is posting content the analysis would actually read.
   *
   * **Computed server-side, by `scoreable_posting`.** Deriving it here would be
   * a second implementation of a rule that already disagreed with itself once —
   * the guard tested `requirements` while the prompt sent `job_description`, so
   * a job with requirements and no description was scored against nothing.
   */
  is_scoreable: boolean;
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
  /** The résumé this application sent, if it sent one through CareerHQ (FR-024).
   *
   *  **`null` is an answer, not a gap.** An application that reached `Applied` outside
   *  this system — every imported row — has no document here, and naming the nearest
   *  available one would describe something the employer never received.
   *
   *  **Optional, and the three states are distinct.** `undefined` means the list response,
   *  which does not carry it — resolving a reference per row would cost a query per row
   *  for something only the detail view shows. `null` means it was asked and the answer
   *  was none. Collapsing those two would make an unloaded field read as "sent nothing". */
  submission?: SubmissionSummary | null;
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

/** One retained upload. `storage_key` is deliberately not exposed. */
export type ImportRecord = {
  id: string;
  filename: string;
  content_type: string;
  byte_size: number;
  status: string;
  is_fixture: boolean;
  created_at: string;
  approved_at: string | null;
};

export type MatchState = "running" | "ready" | "failed" | "nothing_to_score";

/** One requirement, and how the profile answers it. */
export type MatchRequirement = {
  ordinal: number;
  text: string;
  /** What the posting **said**. */
  kind: "must_have" | "preferred";
  /** What the model **judged** it is worth for this role, 0-100. */
  importance: number;
  verdict: "confirmed" | "partial" | "transferable" | "gap" | "unverified";
  /** Absent on `confirmed` (nothing to explain) and on `unverified` (nothing
   *  to explain it with — guessing why a CV is silent is inference). */
  shortfall: "wording" | "evidence" | "capability" | null;
  /** Quoted from the profile. Null only on `unverified`. */
  evidence: string | null;
};

export type MatchAnalysis = {
  id: string;
  band: "strong" | "moderate" | "stretch" | "low_probability" | null;
  /** The weighted sum of `dimensions`. Shown beside the band, never alone. */
  overall_score: number | null;
  /**
   * What each verdict earns, as a share of a requirement's importance.
   *
   * The score is `sum(importance * credit) / sum(importance)`, so this is what
   * makes the total checkable against the requirement rows rather than a
   * number to be taken on trust.
   */
  credit: Record<string, number>;
  /**
   * The requirement holding the band below its arithmetic, if one is.
   *
   * The band is not the score bucketed. Without this the label and the number
   * disagree on screen and it reads as a bug; with it, it is the most useful
   * line on the page.
   */
  capped_by: { ordinal: number; text: string; importance: number } | null;
  verdict: string | null;
  criteria_version: string;
  error: string | null;
  coverage: Record<string, number>;
  requirements: MatchRequirement[];
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  /** A string, because a Decimal audit value must not become a float. */
  cost: string | null;
  is_fixture: boolean;
  created_at: string;
  completed_at: string | null;
};

export type MatchResult = {
  state: MatchState;
  analysis: MatchAnalysis | null;
  /** The profile changed after this was scored. Computed by the server. */
  stale: boolean;
};

export function fetchMatch(applicationId: string): Promise<MatchResult> {
  return request<MatchResult>(`/api/applications/${applicationId}/match`);
}

export function runMatch(applicationId: string): Promise<MatchResult> {
  return request<MatchResult>(`/api/applications/${applicationId}/match`, { method: "POST" });
}

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
  /** The **whole posting**, which match analysis scores against. */
  job_description: string | null;
  /** The extracted list, kept beside the posting rather than in place of it. */
  requirements: string[];
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

// ---------------------------------------------------------------------------
// JobTracker import

/** The largest upload the API accepts — `MAX_UPLOAD_BYTES` in `imports.py`.
 *
 * Duplicated here **as a convenience, never as the guard**. The server refuses
 * oversized uploads with a 413 whatever the browser believes; checking first
 * only spares someone a long upload that was always going to be refused.
 */
export const MAX_IMPORT_BYTES = 10 * 1024 * 1024;

/** One row the importer would not map, and why. **It is not in the database.** */
export type ImportRejection = { source_id: string; reason: string };

/** One row that **did** import but wants a person's eye — an unfamiliar status,
 *  a date nobody could read. Deliberately not a rejection: the row is there. */
export type ImportNotice = { source_id: string; message: string };

/**
 * What an import did — four outcomes, and two pairs that must not be merged.
 *
 * `skipped` is a **success**: rows already imported, refused by the C3 unique
 * index rather than by a check that could be raced. Re-running an import is
 * safe by design, so a screen that renders this as a failure would make correct
 * behaviour look broken.
 *
 * `notices` are rows that imported. They are separate from `rejected` because
 * conflating them would send someone looking for history that is already there.
 */
export type JobtrackerImportReport = {
  imported: number;
  skipped: number;
  rejected: ImportRejection[];
  notices: ImportNotice[];
};

/**
 * Upload a JobTracker CSV export.
 *
 * **Not routed through `request()`**, which would be the tidier call, because a
 * `FormData` body must be handed to `fetch` without a `Content-Type`: the
 * browser has to set it itself so the multipart boundary matches. Setting the
 * header — or letting a helper set it — produces a 422 that reads as a bad
 * file rather than a bad request.
 *
 * Ownership comes from the session cookie; the export's own `user_id` column is
 * discarded server-side (FR-019), so nothing here identifies a user.
 */
export async function importJobtracker(file: File): Promise<JobtrackerImportReport> {
  const body = new FormData();
  body.append("file", file);

  let response: Response;
  try {
    response = await fetch("/api/applications/import/jobtracker", {
      method: "POST",
      credentials: "include",
      headers: { Accept: "application/json" },
      body,
    });
  } catch (cause) {
    throw new ApiUnreachableError(cause);
  }

  if (!response.ok) {
    const detail = await response
      .json()
      .then((payload: { detail?: unknown }) => payload.detail)
      .catch(() => undefined);
    throw new ApiError(response.status, messageOf(detail) ?? response.statusText, detail);
  }

  return (await response.json()) as JobtrackerImportReport;
}

// ---------------------------------------------------------------------------
// Resume tailoring
// ---------------------------------------------------------------------------

/**
 * Where one tailored resume has got to.
 *
 * **There is no `failed`**, deliberately, and the absence is load-bearing on
 * this side too: a run that fails returns the version to `draft` and records
 * why on the run. So "it broke" is `draft` plus a `failure_reason`, not a sixth
 * state — and a client that invented one would render a dead end for something
 * the owner can simply try again.
 *
 * `reviewing` and `awaiting_approval` are two states rather than one because
 * they mean *the agent is criticising its own draft* and *it has finished and
 * it is your turn* — a machine working for tens of seconds against a human
 * queue that may last days (FR-040).
 */
export type VersionStatus =
  | "draft"
  | "tailoring"
  | "reviewing"
  | "awaiting_approval"
  | "ready"
  /** Rendered to a PDF and stored (FR-019). Re-exportable: the same approved content
   *  renders to identical bytes, so a second export is a second copy, not a change. */
  | "exported"
  /** Sent, and frozen (FR-021). Terminal: nothing edits it again, and revising the
   *  résumé for this job produces a **new** version rather than moving this one
   *  (FR-025). Added at T043, which gave the interface a way to reach it — until then
   *  a state the UI could name was a claim the code did not support. */
  | "submitted";

/** What the owner did with one proposal. `pending` is the initial state, not a
 *  choice, and there is no way back to it. */
export type ProposalDecision = "pending" | "accepted" | "rejected" | "edited";

/**
 * What the Reviewer objected to.
 *
 * `ungrounded` never arrives beside a surviving `proposed_text` — the claim was
 * discarded before it was ever saved (FR-018). The finding is here as the
 * evidence that the guardrail ran, which is a different thing from a choice.
 */
export type FindingKind = "ungrounded" | "overstated" | "uncovered";

export type SourceKind =
  | "summary"
  | "title"
  | "experience_bullet"
  | "skill"
  | "project"
  | "education"
  | "certification"
  | "language";

export type ReviewerFinding = {
  kind: FindingKind;
  detail: string;
  /** The exact words objected to. Always present on `ungrounded`. */
  quoted_text: string | null;
  /** Which review pass caught it — 0 is the first draft. */
  attempt: number;
};

export type VersionItem = {
  id: string;
  source_kind: SourceKind;
  source_item_id: string | null;
  position: number;
  included: boolean;
  /** The master's wording, copied rather than referenced, so an approved diff
   *  cannot change underneath the person who approved it. */
  original_text: string;
  /** Null when the agent proposed no change to this item. */
  proposed_text: string | null;
  /** Materialised by the server, never derived here. Slice 006's PDF export
   *  reads the same column, and two implementations of one rule is one too
   *  many when a wrong answer becomes a document sent to an employer. */
  final_text: string;
  decision: ProposalDecision;
  /** Nested under the item they concern (FR-042). */
  findings: ReviewerFinding[];
};

export type ResumeVersion = {
  id: string;
  application_id: string;
  name: string;
  professional_title: string | null;
  status: VersionStatus;
  /**
   * How sure the Reviewer was, 0-100.
   *
   * **Not the match score, and never shown as one** (FR-043). The match score
   * says how well you fit the job; this says how well the draft is grounded in
   * your profile. Same shape of number, entirely different question.
   */
  confidence_score: number | null;
  /** Set when a run failed. The version is back at `draft` and can be retried. */
  failure_reason: string | null;
  /** The model that wrote these words. The full per-task configuration is on
   *  the run. */
  model: string | null;
  is_fixture: boolean;
  /** A string, because a Decimal audit value must not become a float. */
  cost: string | null;
  source_profile_updated_at: string;
  created_at: string;
  /** Empty while the run is in flight — the interface renders progress from
   *  that, because an empty diff reads as "nothing was proposed" (FR-039). */
  items: VersionItem[];
  /** Findings with no item: `uncovered`, which concerns the draft as a whole. */
  draft_findings: ReviewerFinding[];
};

export type VersionSummary = {
  id: string;
  name: string;
  status: VersionStatus;
  confidence_score: number | null;
  created_at: string;
};

export type TailoringRun = {
  id: string;
  version_id: string;
  status: "running" | "succeeded" | "failed" | "abandoned";
  failure_reason: string | null;
  plan: {
    emphasise: { what: string; serves_requirement: string }[];
    de_emphasise: string[];
    protected_gaps: { requirement: string; why_protected: string }[];
    strategy: string;
  } | null;
  attempts: number;
  match_analysis_id: string;
  guidelines_used: { text: string; source: string }[];
  /** Task name to model, as resolved when the run happened — not what the
   *  configuration says now. */
  models: Record<string, string>;
  finalisation_rules_version: string;
  input_tokens: number;
  output_tokens: number;
  cost: string;
  is_fixture: boolean;
  started_at: string;
  finished_at: string | null;
};

export type TailoringStarted = {
  version_id: string;
  status: VersionStatus;
  run_id: string | null;
};

/** Why the server refused to start a run, when it did. */
export type RefusalReason = "no_analysis" | "stale_analysis" | "no_profile" | "no_master";

/**
 * The refusal reason carried by a 422, or null for any other failure.
 *
 * Reading the `reason` rather than the sentence is the whole point of the
 * server sending one: "score this job first" and "re-score it, your profile
 * changed" are different actions, and the interface must offer the right one.
 */
export function refusalReason(error: unknown): RefusalReason | null {
  if (!(error instanceof ApiError) || error.status !== 422) return null;
  const detail = error.detail;
  if (detail && typeof detail === "object" && "reason" in detail) {
    return (detail as { reason: RefusalReason }).reason;
  }
  return null;
}

/** Start a run. **No body** — a model or budget from the browser would put
 *  cost under the client's control. */
export function startTailoring(applicationId: string): Promise<TailoringStarted> {
  return request<TailoringStarted>(`/api/applications/${applicationId}/tailor`, {
    method: "POST",
  });
}

export function getVersion(versionId: string): Promise<ResumeVersion> {
  return request<ResumeVersion>(`/api/versions/${versionId}`);
}

export function listVersions(applicationId: string): Promise<{ versions: VersionSummary[] }> {
  return request<{ versions: VersionSummary[] }>(`/api/applications/${applicationId}/versions`);
}

/** Record a decision on one proposal. Rejecting starts no AI work (FR-026). */
export function decideItem(
  versionId: string,
  itemId: string,
  decision: Exclude<ProposalDecision, "pending">,
  text?: string,
): Promise<VersionItem> {
  return request<VersionItem>(`/api/versions/${versionId}/items/${itemId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(text === undefined ? { decision } : { decision, text }),
  });
}

/** Confirm the draft. Everything still pending counts as accepted (FR-025),
 *  and nothing further is started (FR-028). */
export function approveVersion(versionId: string): Promise<ResumeVersion> {
  return request<ResumeVersion>(`/api/versions/${versionId}/approve`, { method: "POST" });
}

/** What one export recorded. **No storage key**: that is an internal address, and the
 *  document is reached through `versionDocumentUrl` rather than by object path. */
export type ExportSummary = {
  /** SHA-256 over the exact stored bytes, which is what makes FR-021's later
   *  re-verification a comparison rather than a re-render. */
  checksum_sha256: string;
  byte_size: number;
  exported_at: string;
};

export type ExportedVersion = ResumeVersion & { export: ExportSummary };

/** What one submission recorded. **No storage key**, for the same reason as the export
 *  above: it is an internal address, and the document is reached through
 *  `versionDocumentUrl`. */
export type SubmissionSummary = {
  /** The version this names — the one that was sent, which a later revision does not
   *  displace (FR-025). */
  resume_version_id: string;
  /** SHA-256 over the stored bytes, re-verified against them at submission (FR-021). */
  checksum_sha256: string;
  byte_size: number;
  submitted_at: string;
};

export type SubmittedVersion = ResumeVersion & { submission: SubmissionSummary };

/** Record that this exported PDF is what was sent (FR-020/FR-021).
 *
 *  Refused with 409 in two different situations that the status code cannot tell apart:
 *  the version was never exported or was already sent, and — separately — the stored
 *  document no longer matches the checksum recorded for it. The **message** is the
 *  difference, which is why it has to be shown rather than replaced with one of ours.
 *
 *  This changes nothing about the application: its status and the date the person said
 *  they applied are theirs, and are edited on the application itself. */
export function submitVersion(versionId: string): Promise<SubmittedVersion> {
  return request<SubmittedVersion>(`/api/versions/${versionId}/submit`, { method: "POST" });
}

/** Render an approved version to a PDF and store it (FR-015/FR-019).
 *
 *  Refused with 409 for a version that has not been approved, or that was already
 *  submitted. Calling it again on an exported version is legitimate and produces a
 *  second copy — the download link below does not need it. */
export function exportVersion(versionId: string): Promise<ExportedVersion> {
  return request<ExportedVersion>(`/api/versions/${versionId}/export`, { method: "POST" });
}

/** Where the browser fetches the stored PDF.
 *
 *  A plain URL rather than a `request` call: this is a navigation the browser performs
 *  itself, so the response becomes a download instead of a string this code would have
 *  to turn back into one. */
export function versionDocumentUrl(versionId: string): string {
  return `/api/versions/${versionId}/document`;
}

/** The audit record — plan, models, tokens, cost, timings (FR-034). */
export function getTailoringRun(versionId: string): Promise<TailoringRun> {
  return request<TailoringRun>(`/api/versions/${versionId}/run`);
}

/* -- Application research (slice 010; tiered shape retained from 008) ----- */

export type ResearchClaim = {
  id: string;
  text: string;
  tier: "fact" | "interpretation" | "inference";
  evidence: { source_id: string; excerpt: string }[];
  rests_on: string[];
};

export type ResearchSection = {
  claims: ResearchClaim[];
  empty_reason: string | null;
};

export type ResearchSource = {
  source_id: string;
  url: string;
  title: string | null;
  fetch_status: "retrieved" | "failed" | "refused";
  excerpt: string | null;
};

export type CompanyIdentification = {
  official_name: string;
  website: string;
  headquarters: string | null;
  /** The wrong-entity tripwire (FR-007): how this company was told apart from
   *  same-named ones. Always shown. */
  how_identified: string;
};

/** The slice 010 sections-first result (`shape: "sections"`). */
export type SectionsResearch = {
  company_identification: CompanyIdentification;
  company_overview: string;
  products_and_services: string;
  business_and_market: string;
  relevant_to_your_role: string;
  what_to_know_before_the_interview: string[];
  questions_worth_asking: string[];
};

/** The 008-era tiered result (`shape: "tiered"`): fallback runs and legacy
 *  company snapshots. */
export type TieredResearch = Record<string, ResearchSection>;

export type ResearchPayload = {
  snapshot_id: string;
  /** The entity this research was requested for — the tiered shape's only
   *  visible identity (review fix, FR-014). */
  company: string;
  /** A newer failed refresh riding along the still-current result: FR-016
   *  keeps the success, US3 keeps the failure visible (review fix). */
  last_failure: { failure_reason: string | null; retrieved_at: string } | null;
  status: "running" | "succeeded" | "failed";
  /** The renderer dispatch — never sniff the payload. */
  shape: "sections" | "tiered";
  /** Truthful producer: `provider:tavily-research`, `builtin`, or
   *  `legacy-company` (derived for 008-era snapshots). */
  produced_by: string;
  failure_reason: string | null;
  retrieved_at: string;
  /** Derived at read time, never stored — a row keeps ageing (FR-013). */
  freshness: "fresh" | "aging" | "stale";
  cost: string;
  /** `recorded` is exact seam usage; `estimate` is a documented-rate figure —
   *  the two must never be summed unlabelled. */
  cost_basis: "recorded" | "estimate";
  research: SectionsResearch | TieredResearch;
  sources: ResearchSource[];
};

/** `{status: "none"}` is an answer: nobody has researched this application. */
export type ResearchState = ResearchPayload | { status: "none" };

export type ResearchStarted = {
  snapshot_id: string;
  status: string;
  /** True when a fresh snapshot already existed and nothing was spent (FR-013). */
  reused: boolean;
};

/** Start research, or get back the snapshot already worth reusing. */
export function startResearch(applicationId: string): Promise<ResearchStarted> {
  return request<ResearchStarted>(`/api/applications/${applicationId}/research`, {
    method: "POST",
  });
}

/** Never 404s for an unresearched application; it answers `{status: "none"}`. */
export function getResearch(applicationId: string): Promise<ResearchState> {
  return request<ResearchState>(`/api/applications/${applicationId}/research`);
}
