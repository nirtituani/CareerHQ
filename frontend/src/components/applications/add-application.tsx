"use client";

import { X } from "lucide-react";
import { useRouter } from "next/navigation";
import { Dialog } from "radix-ui";
import { useState } from "react";

import { JobImport } from "@/components/applications/job-import";
import { Button } from "@/components/ui/button";
import {
  ApiError,
  type Application,
  type JobExtraction,
  createApplication,
  updateApplication,
} from "@/lib/api";

/**
 * Add Application — the modal, carried over from the author's JobTracker.
 *
 * Field set and two-column layout follow the source app, with three deliberate
 * differences:
 *
 * **No "Mark as rejected" toggle.** The source keeps a `rejected` boolean
 * beside the status, and its own dashboard has to reconcile them at every read
 * (`WHERE rejected IS TRUE OR status='Rejected'`) because the two disagree.
 * Rejection here is a value of the normalized status and nothing else (FR-016).
 * Nothing is lost: `rejected=true` with status "Interview Round 2" keeps the
 * label — how far you got — and normalizes to `rejected` — the outcome.
 *
 * **Applied Via and Date Applied appear only once the status is Applied or
 * later.** Both are meaningless on a job nobody has applied to yet, and asking
 * for them up front is what makes the source's form long.
 *
 * **No Job Match field.** It comes from the match-score mechanism against the
 * user's profile, not from a number typed at creation.
 *
 * The modal opens on the automatic step — paste a link, get the fields — and
 * falls through to this form with them filled in. Both routes end here, at a
 * form the person confirms, because an extraction that saved itself would put a
 * model's reading of a web page into the record with nobody having looked
 * (Principle II).
 */
const STATUSES = [
  "Pre-Applied",
  "Applied",
  "Online Assessment",
  "Phone Screen",
  "Interview Round 1",
  "Interview Round 2",
  "Interview Round 3",
  "Final Interview",
  "Offer Received",
  "Rejected",
  "Ghosted",
  "Withdrawn",
];

/** From the source app's settings. Free text underneath, so any value saves. */
const APPLIED_VIA = [
  "Company Website",
  "LinkedIn",
  "Recruiter",
  "Direct Email",
  "Referral",
  "Headhunter",
];

/** Statuses that mean the application has actually been sent. */
const PRE_SUBMISSION = new Set(["Pre-Applied", "Wishlist", "Saved"]);

const FIELD =
  "h-9 w-full rounded-lg border-0 px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-brand-600)]";
const FIELD_STYLE = { background: "var(--surface-sunken)" } as const;

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

function Labelled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1.5 block font-medium">{label}</span>
      {children}
    </label>
  );
}

export function AddApplication({
  open,
  onOpenChange,
  editing,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** When set, the same modal edits this record instead of creating one. */
  editing?: Application | null;
}) {
  const router = useRouter();
  // Editing skips the automatic route: the job is already recorded, so there
  // is nothing to read off a URL that the record does not already hold.
  const [step, setStep] = useState<"import" | "form">(editing ? "form" : "import");
  const [extracted, setExtracted] = useState<JobExtraction | null>(null);
  const [sourceUrl, setSourceUrl] = useState("");
  const [status, setStatus] = useState(editing?.status ?? "Pre-Applied");
  const [showDescription, setShowDescription] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** Values the form opens with: the record being edited, or an extraction. */
  const filled = editing
    ? {
        company: editing.company.name,
        company_domain: editing.company.domain,
        job_title: editing.job_title,
        location: editing.location,
        salary_text: editing.salary_text,
        job_description: editing.job_description,
      }
    : extracted?.posting;

  /** Reset to the first step whenever the modal is reopened. */
  function change(next: boolean) {
    if (!next) {
      setStep(editing ? "form" : "import");
      setExtracted(null);
      setSourceUrl("");
      setStatus(editing?.status ?? "Pre-Applied");
      setShowDescription(false);
      setError(null);
    }
    onOpenChange(next);
  }

  const applied = !PRE_SUBMISSION.has(status.trim());

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const text = (key: string) => (data.get(key) as string | null)?.trim() || undefined;

    const company = text("company");
    const jobTitle = text("job_title");
    if (!company || !jobTitle) {
      setError("A company name and a job title are required.");
      return;
    }

    setSaving(true);
    setError(null);

    try {
      const payload = {
        company,
        job_title: jobTitle,
        location: text("location"),
        status: text("status") || "Pre-Applied",
        date_added: text("date_added"),
        salary_text: text("salary_text"),
        job_description_url: text("job_description_url"),
        company_domain: text("company_domain"),
        contact_name: text("contact_name"),
        contact_email: text("contact_email"),
        notes: text("notes"),
        job_description: text("job_description"),
        // Only sent once the job has actually been applied to.
        ...(applied ? { source: text("source"), date_applied: text("date_applied") } : {}),
      };

      if (editing) {
        // PATCH, so a status change writes its history row like any other move.
        await updateApplication(editing.id, payload);
        onOpenChange(false);
        router.refresh();
      } else {
        const created = await createApplication(payload);
        router.push(`/applications/${created.id}`);
      }
    } catch (cause) {
      setError(
        cause instanceof ApiError ? cause.message : "Could not save this job. Please try again.",
      );
      setSaving(false);
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={change}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/40" />
        <Dialog.Content
          className="fixed top-1/2 left-1/2 flex max-h-[90vh] w-[92vw] max-w-xl -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-2xl shadow-2xl"
          style={{ background: "var(--background)" }}
        >
          <div
            className="flex items-start justify-between border-b px-6 py-5"
            style={{ borderColor: "var(--border)" }}
          >
            <div>
              <Dialog.Title
                className="text-lg tracking-tight"
                style={{ fontFamily: "var(--font-display)" }}
              >
                {editing ? "Edit Application" : "Add Application"}
              </Dialog.Title>
              <Dialog.Description className="mt-0.5 text-sm" style={{ color: "var(--muted)" }}>
                {editing
                  ? `${editing.company.name} · ${editing.job_title}`
                  : "Track a new job application"}
              </Dialog.Description>
            </div>
            <Dialog.Close
              className="rounded-md p-1 transition-colors"
              style={{ color: "var(--muted)" }}
              aria-label="Close"
            >
              <X className="size-5" />
            </Dialog.Close>
          </div>

          {step === "import" ? (
            <JobImport
              onExtracted={(result, url) => {
                setExtracted(result);
                setSourceUrl(url);
                setStep("form");
              }}
              onManual={() => setStep("form")}
            />
          ) : (
          <form onSubmit={submit} className="flex min-h-0 flex-1 flex-col">
            {extracted && (
              // Provenance, stated plainly. "The employer published this" and "a
              // model read the page" deserve different trust, and the person is
              // about to approve these values into their record.
              <p
                className="mx-6 mt-4 rounded-lg px-3 py-2 text-xs"
                style={{ background: "var(--surface-sunken)", color: "var(--muted)" }}
              >
                {extracted.provenance === "structured_data"
                  ? "Filled in from the posting's own published data. Check it before saving."
                  : "Filled in by reading the posting. Check it before saving."}
              </p>
            )}
            <div className="grid min-h-0 flex-1 gap-4 overflow-y-auto px-6 py-5 sm:grid-cols-2">
              <Labelled label="Company Name *">
                <input name="company" required autoFocus defaultValue={filled?.company ?? ""} placeholder="e.g. Google" className={FIELD} style={FIELD_STYLE} />
              </Labelled>

              <Labelled label="Job Title *">
                <input name="job_title" required defaultValue={filled?.job_title ?? ""} placeholder="e.g. Software Engineer" className={FIELD} style={FIELD_STYLE} />
              </Labelled>

              <Labelled label="Location">
                <input name="location" defaultValue={filled?.location ?? ""} placeholder="e.g. Tel Aviv" className={FIELD} style={FIELD_STYLE} />
              </Labelled>

              <Labelled label="Date Added">
                {/* Prefilled with today. This is what makes a job that sat in
                    Pre-Applied for weeks visible; the applied date is separate
                    and set when you actually apply. */}
                <input
                  name="date_added"
                  type="date"
                  defaultValue={editing?.date_added?.slice(0, 10) ?? today()}
                  className={FIELD}
                  style={FIELD_STYLE}
                />
              </Labelled>

              <Labelled label="Status">
                {/* A dropdown, as in the source app. The record's own status is
                    added to the list when it is not one of these, so editing a
                    row imported with a custom label does not silently rewrite it
                    to something from our vocabulary — the source keeps its
                    statuses in browser storage, so custom labels reach an export
                    and are the common case rather than the exotic one (R8). */}
                <select
                  name="status"
                  value={status}
                  onChange={(event) => setStatus(event.target.value)}
                  className={FIELD}
                  style={FIELD_STYLE}
                >
                  {(STATUSES.includes(status) || !status ? STATUSES : [status, ...STATUSES]).map(
                    (label) => (
                      <option key={label} value={label}>
                        {label}
                      </option>
                    ),
                  )}
                </select>
              </Labelled>

              <Labelled label="Salary Range">
                {/* Free text: "90-110k" and "competitive" are both real
                    answers, and parsing them into numbers invents precision. */}
                <input name="salary_text" defaultValue={filled?.salary_text ?? ""} placeholder="e.g. 30K-40K" className={FIELD} style={FIELD_STYLE} />
              </Labelled>

              <Labelled label="Job Description Link">
                {/* Prefilled with the link that was just fetched. */}
                <input
                  name="job_description_url"
                  type="url"
                  defaultValue={editing?.job_description_url ?? editing?.job_url ?? sourceUrl}
                  placeholder="https://…"
                  className={FIELD}
                  style={FIELD_STYLE}
                />
              </Labelled>

              <Labelled label="Company Website (for logo)">
                <input name="company_domain" defaultValue={filled?.company_domain ?? ""} placeholder="https://company.com" className={FIELD} style={FIELD_STYLE} />
              </Labelled>

              <Labelled label="Contact Person">
                <input name="contact_name" defaultValue={editing?.contact_name ?? ""} placeholder="e.g. Jane Smith" className={FIELD} style={FIELD_STYLE} />
              </Labelled>

              <Labelled label="Contact Email">
                <input name="contact_email" type="email" defaultValue={editing?.contact_email ?? ""} placeholder="email@company.com" className={FIELD} style={FIELD_STYLE} />
              </Labelled>

              {applied && (
                <>
                  <Labelled label="Applied Via">
                    <select name="source" defaultValue={editing?.source ?? ""} className={FIELD} style={FIELD_STYLE}>
                      <option value="">Select…</option>
                      {APPLIED_VIA.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                  </Labelled>

                  <Labelled label="Date Applied">
                    <input
                      name="date_applied"
                      type="date"
                      defaultValue={editing?.date_applied?.slice(0, 10) ?? today()}
                      className={FIELD}
                      style={FIELD_STYLE}
                    />
                  </Labelled>
                </>
              )}

              <div className="sm:col-span-2">
                <Labelled label="Notes">
                  <textarea
                    name="notes"
                    defaultValue={editing?.notes ?? ""}
                    rows={3}
                    placeholder="Add any notes…"
                    className="w-full rounded-lg border-0 px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-brand-600)]"
                    style={FIELD_STYLE}
                  />
                </Labelled>
              </div>

              <div className="sm:col-span-2">
                {/* Collapsed by design: pasting a posting is not something to
                    ask for up front. It stays reachable because the tailoring
                    in the next slice works from stored text, so an application
                    with nothing here cannot be tailored against. */}
                {showDescription || filled?.job_description ? (
                  <Labelled label="Requirements">
                    <textarea
                      name="job_description"
                      rows={8}
                      defaultValue={filled?.job_description ?? ""}
                      placeholder="One requirement per line…"
                      autoFocus={!filled?.job_description}
                      className="w-full rounded-lg border-0 px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-brand-600)]"
                      style={FIELD_STYLE}
                    />
                  </Labelled>
                ) : (
                  <button
                    type="button"
                    onClick={() => setShowDescription(true)}
                    className="text-sm underline underline-offset-4"
                    style={{ color: "var(--muted)" }}
                  >
                    + Add the requirements
                  </button>
                )}
              </div>
            </div>

            {error && (
              <p
                className="mx-6 mb-2 border-l-2 pl-3 text-sm"
                style={{ borderColor: "var(--color-failure)", color: "var(--color-failure)" }}
              >
                {error}
              </p>
            )}

            <div
              className="flex justify-end gap-2 border-t px-6 py-4"
              style={{ borderColor: "var(--border)" }}
            >
              <Button type="button" variant="outline" onClick={() => change(false)} disabled={saving}>
                Cancel
              </Button>
              <Button type="submit" disabled={saving}>
                {saving ? "Saving…" : editing ? "Save changes" : "Add Application"}
              </Button>
            </div>
          </form>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
