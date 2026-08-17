"use client";

import { Loader2, Sparkles, Wand2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ApiError, type JobExtraction, extractJob } from "@/lib/api";

/**
 * The automatic half of Add Application: a URL in, form fields out.
 *
 * Three steps, tried in order, because the first two fail often and the third
 * always works:
 *
 * 1. **Paste the URL.** Where the page publishes schema.org `JobPosting` data —
 *    most applicant tracking systems — the fields are read exactly, and no model
 *    call is billed at all.
 * 2. **Paste the posting text.** Offered the moment a fetch is refused, which is
 *    what LinkedIn, Indeed and Glassdoor do to any server-side request. Without
 *    this step "automatic" would drop to hand-typing on the sites people
 *    actually use, so it is the difference between a feature and a demo.
 * 3. **Fill it in by hand.** Always available, never a punishment.
 *
 * Nothing here saves anything. Extraction fills the form and the person
 * confirms it — Principle II puts a human between a model and the record, the
 * same way the CV review does.
 */
const FIELD =
  "h-9 w-full rounded-lg border-0 px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-brand-600)]";

export function JobImport({
  onExtracted,
  onManual,
}: {
  onExtracted: (extraction: JobExtraction, sourceUrl: string) => void;
  onManual: () => void;
}) {
  const [url, setUrl] = useState("");
  const [posting, setPosting] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Shown only after a fetch is refused, so the ordinary path stays one field.
  const [offerPaste, setOfferPaste] = useState(false);

  async function run(input: { url?: string; text?: string }) {
    setBusy(true);
    setError(null);
    try {
      // The URL travels with the result so the form can fill in the
      // posting link — we already have it, and asking for it again would
      // be asking for something just typed.
      onExtracted(await extractJob(input), input.url ?? "");
    } catch (cause) {
      const message =
        cause instanceof ApiError
          ? cause.message
          : "Could not read that posting. You can paste the text instead.";
      setError(message);
      // A refused fetch is not a dead end — it is the cue for step 2.
      if (input.url) setOfferPaste(true);
      setBusy(false);
    }
  }

  return (
    <div className="px-6 py-5">
      <div
        className="rounded-xl p-5"
        style={{ background: "var(--surface-sunken)" }}
      >
        <div className="mb-3 flex items-center gap-2">
          <Sparkles className="size-4" style={{ color: "var(--color-brand-600)" }} aria-hidden />
          <h3 className="text-sm font-medium">Add automatically</h3>
        </div>
        <p className="mb-4 text-sm" style={{ color: "var(--muted)" }}>
          Paste the job link and we&rsquo;ll fill in the company, title, location and description.
          You review everything before it&rsquo;s saved.
        </p>

        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (url.trim()) void run({ url: url.trim() });
          }}
          className="flex flex-wrap gap-2"
        >
          <label className="sr-only" htmlFor="job-url">
            Job URL
          </label>
          <input
            id="job-url"
            type="url"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://…"
            autoFocus
            disabled={busy}
            className={`${FIELD} min-w-56 flex-1`}
            style={{ background: "var(--background)" }}
          />
          <Button type="submit" disabled={busy || !url.trim()}>
            {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Wand2 aria-hidden />}
            {busy ? "Reading…" : "Fetch"}
          </Button>
        </form>

        {error && (
          <p
            className="mt-3 border-l-2 pl-3 text-sm"
            style={{ borderColor: "var(--color-attention)", color: "var(--muted)" }}
          >
            {error}
          </p>
        )}

        {offerPaste && (
          <div className="mt-4">
            <label className="block text-sm">
              <span className="mb-1.5 block font-medium">Paste the posting text</span>
              <span className="mb-2 block text-xs" style={{ color: "var(--muted)" }}>
                Select all on the job page and paste it here — we&rsquo;ll read it the same way.
              </span>
              <textarea
                value={posting}
                onChange={(event) => setPosting(event.target.value)}
                rows={7}
                disabled={busy}
                className="w-full rounded-lg border-0 px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-brand-600)]"
                style={{ background: "var(--background)" }}
              />
            </label>
            <Button
              type="button"
              className="mt-2"
              disabled={busy || posting.trim().length < 50}
              onClick={() => void run({ text: posting.trim() })}
            >
              {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Wand2 aria-hidden />}
              Read this text
            </Button>
          </div>
        )}
      </div>

      <div className="mt-5 flex items-center gap-3">
        <span className="h-px flex-1" style={{ background: "var(--border)" }} />
        <span className="text-xs" style={{ color: "var(--faint)" }}>
          or
        </span>
        <span className="h-px flex-1" style={{ background: "var(--border)" }} />
      </div>

      <Button variant="outline" className="mt-5 w-full" onClick={onManual} disabled={busy}>
        Enter the details manually
      </Button>
    </div>
  );
}
