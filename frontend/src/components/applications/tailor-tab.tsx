"use client";

/**
 * The Tailor tab — the agent's draft, and your approval on every line of it.
 *
 * This is the screen Principle II is actually about. Everything else in this
 * project can be described as automation; this one proposes changes to how a
 * person describes their own career, so nothing here may take effect because
 * the machine was confident. Every proposal is shown beside what it replaces
 * and waits.
 *
 * **Five states, rendered distinctly** (FR-039), and the two in the middle are
 * the ones a naive version conflates:
 *
 * | State | What the person sees |
 * |---|---|
 * | not yet tailored | an offer, or the specific reason it cannot start |
 * | tailoring / reviewing | progress, and **which of the two is happening** |
 * | awaiting approval | the diff, and an Approve button |
 * | approved | the finished version, still editable |
 * | failed | what went wrong, and the retry that recovers it |
 *
 * **"Writing" and "checking its own work" are separate lines** (FR-040), and
 * that split is the whole reason `AWAITING_APPROVAL` exists as a status. A
 * person watching one spinner cannot tell a machine working for forty seconds
 * from a queue that is waiting on them, and they will wait for the wrong one.
 *
 * **There is no `failed` version status.** A run that fails puts the version
 * back to `draft` and records why on the run, so "failed" here is `draft` plus
 * a `failure_reason` — and the recovery is simply tailoring again, which reuses
 * the draft rather than accumulating dead versions.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { TailorDiffItem, Finding } from "@/components/applications/tailor-diff-item";
import { Button } from "@/components/ui/button";
import {
  type ProposalDecision,
  type RefusalReason,
  type ResumeVersion,
  type TailoringRun,
  approveVersion,
  exportVersion,
  submitVersion,
  versionDocumentUrl,
  decideItem,
  getTailoringRun,
  getVersion,
  listVersions,
  refusalReason,
  startTailoring,
} from "@/lib/api";

/** Statuses during which the workflow is still running. */
const IN_FLIGHT = ["tailoring", "reviewing"] as const;

function isInFlight(version: ResumeVersion | null): boolean {
  return version !== null && (IN_FLIGHT as readonly string[]).includes(version.status);
}

/**
 * What the server refused for, in the owner's terms, with the action it needs.
 *
 * Read from the `reason` field rather than the sentence: "score this job first"
 * and "re-score it, your profile changed" are the same status code and
 * different next steps, and matching on prose breaks the first time the prose
 * is reworded.
 */
const REFUSAL: Record<RefusalReason, string> = {
  no_analysis:
    "This job has not been scored against your profile yet. Run a match analysis on the Match tab first — tailoring works from what that found.",
  stale_analysis:
    "Your profile has changed since this job was scored. Score it again on the Match tab, then tailor — otherwise the draft would be written against evidence that has moved.",
  no_profile: "There is no profile to tailor from yet.",
  no_master:
    "You have not approved a CV import yet, so there is no master resume to tailor. Import your CV first.",
};

/** Progress, with the step named. */
function Working({ status }: { status: "tailoring" | "reviewing" }) {
  return (
    <div role="status" aria-busy="true" className="flex items-center gap-4 py-8">
      <svg width="40" height="40" viewBox="0 0 40 40" aria-hidden className="shrink-0">
        <circle cx="20" cy="20" r="15" fill="none" strokeWidth="3" stroke="var(--border)" />
        {/* The same travelling arc the Match tab uses while scoring — a partial
            ring that stayed still would read as a finished, poor result. Under
            reduced motion it rests where it started, which paired with the line
            beside it and `aria-busy` is a placeholder rather than a claim. */}
        <circle
          className="score-pending"
          cx="20"
          cy="20"
          r="15"
          fill="none"
          strokeWidth="3"
          strokeLinecap="round"
          stroke="var(--color-brand-500)"
          strokeDasharray={`${(2 * Math.PI * 15) / 4} ${2 * Math.PI * 15}`}
        />
      </svg>
      <div>
        <p
          data-testid="working-step"
          className="text-2xl leading-none"
          style={{ fontFamily: "var(--font-display)", color: "var(--muted)" }}
        >
          {status === "tailoring" ? "Writing" : "Checking its own work"}
        </p>
        <p className="mt-1.5 max-w-prose text-sm" style={{ color: "var(--muted)" }}>
          {status === "tailoring"
            ? "Planning the draft and rewriting your resume against this posting."
            : "Reviewing the draft against your profile and removing anything it cannot support. This is the step that takes longest."}
        </p>
      </div>
    </div>
  );
}

/**
 * The confidence score, labelled so it cannot be read as the match score.
 *
 * Same shape of number, entirely different question (FR-043): the match score
 * says how well you fit the job, this says how well the draft is grounded in
 * your profile. Two unlabelled percentages on one record is how a person comes
 * away believing their fit improved because a draft was rewritten.
 */
function Confidence({ score }: { score: number }) {
  return (
    <span data-testid="confidence" className="text-sm" style={{ color: "var(--muted)" }}>
      <span className="tabular" style={{ fontFamily: "var(--font-mono)" }}>
        {score}/100
      </span>{" "}
      grounded in your profile
    </span>
  );
}

/** How this was produced — Principle V's audit record, at reading distance. */
function RunDetail({ run }: { run: TailoringRun }) {
  return (
    <details className="mt-6" data-testid="run-detail">
      <summary className="cursor-pointer text-sm" style={{ color: "var(--muted)" }}>
        How this draft was written
      </summary>
      <div
        className="mt-2 rounded-lg p-5 text-sm"
        style={{ background: "var(--surface-sunken)" }}
      >
        {run.plan && (
          <>
            <p>{run.plan.strategy}</p>
            {run.plan.protected_gaps.length > 0 && (
              <>
                {/* The gaps the plan was told not to paper over. This is the
                    most reassuring thing on the page and the least obvious:
                    the agent was given the match analysis's unmet requirements
                    and instructed to leave them alone rather than write around
                    them. */}
                <p className="mt-3 text-xs tracking-wide uppercase" style={{ color: "var(--muted)" }}>
                  Left alone on purpose
                </p>
                <ul className="mt-1 space-y-1">
                  {run.plan.protected_gaps.map((gap, index) => (
                    <li key={index} className="text-sm" style={{ color: "var(--muted)" }}>
                      {gap.requirement} — {gap.why_protected}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </>
        )}

        <p
          className="mt-4 text-xs"
          style={{ fontFamily: "var(--font-mono)", color: "var(--faint)" }}
        >
          {Object.entries(run.models)
            .map(([task, model]) => `${task.replace("tailor_", "")}: ${model}`)
            .join(" · ")}
        </p>
        <p
          className="mt-1 text-xs"
          style={{ fontFamily: "var(--font-mono)", color: "var(--faint)" }}
        >
          {run.attempts} revision{run.attempts === 1 ? "" : "s"} · {run.input_tokens} in ·{" "}
          {run.output_tokens} out · ${run.cost} · {run.finalisation_rules_version}
        </p>
      </div>
    </details>
  );
}

export function TailorTab({ applicationId }: { applicationId: string }) {
  const [version, setVersion] = useState<ResumeVersion | null>(null);
  const [run, setRun] = useState<TailoringRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<RefusalReason | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Guards every `setState` after an await. Without it, switching applications
  // mid-request lands the previous job's version on the new job's tab.
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);

  const load = useCallback(async () => {
    const { versions } = await listVersions(applicationId);
    if (versions.length === 0) {
      if (live.current) setVersion(null);
      return null;
    }
    // Newest first from the server; the newest is the one this tab is about.
    const latest = await getVersion(versions[0].id);
    if (live.current) setVersion(latest);
    return latest;
  }, [applicationId]);

  useEffect(() => {
    setLoading(true);
    load()
      .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : String(cause)))
      .finally(() => {
        if (live.current) setLoading(false);
      });
  }, [load]);

  // Poll only while the workflow is actually running, and stop the moment it
  // is not. Keyed on the status as well as the id so the interval is torn down
  // by the transition itself rather than by a check inside it — a stale closure
  // here would keep polling a finished run forever.
  const versionId = version?.id;
  const versionStatus = version?.status;
  useEffect(() => {
    if (!versionId || !(IN_FLIGHT as readonly string[]).includes(versionStatus ?? "")) return;
    const timer = setInterval(() => {
      getVersion(versionId)
        .then((next) => {
          if (live.current) setVersion(next);
        })
        .catch(() => undefined);
    }, 2000);
    return () => clearInterval(timer);
  }, [versionId, versionStatus]);

  // The audit record, once there is one to read. Deliberately a second request
  // rather than a field on the version: it is inspection rather than the
  // document, and it is not needed to render the diff.
  useEffect(() => {
    if (!versionId || versionStatus === "tailoring" || versionStatus === "reviewing") return;
    getTailoringRun(versionId)
      .then((next) => {
        if (live.current) setRun(next);
      })
      .catch(() => undefined);
  }, [versionId, versionStatus]);

  async function tailor() {
    setBusy(true);
    setRefusal(null);
    setError(null);
    try {
      const started = await startTailoring(applicationId);
      const fresh = await getVersion(started.version_id);
      if (live.current) setVersion(fresh);
    } catch (cause) {
      const reason = refusalReason(cause);
      if (reason) setRefusal(reason);
      else setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      if (live.current) setBusy(false);
    }
  }

  async function decide(
    itemId: string,
    decision: Exclude<ProposalDecision, "pending">,
    text?: string,
  ) {
    if (!version) return;
    setError(null);
    try {
      const updated = await decideItem(version.id, itemId, decision, text);
      // Replace the one item rather than refetching the version: a refetch here
      // would discard any edit in progress on a neighbouring row.
      if (live.current) {
        setVersion({
          ...version,
          items: version.items.map((item) => (item.id === updated.id ? updated : item)),
        });
      }
    } catch (cause: unknown) {
      // **The T037 fix, on the one path that never got it.** Without this the
      // rejected promise went nowhere: the row did not move, no error rendered,
      // and silence after a click reads as success. The controls are now hidden
      // on a locked version, so what still arrives here is the refusal for a
      // version locked somewhere else while this screen was open — which is
      // exactly the case a person cannot otherwise tell from a successful one.
      if (live.current) setError(cause instanceof Error ? cause.message : String(cause));
    }
  }

  async function exportPdf() {
    if (!version) return;
    setBusy(true);
    setError(null);
    try {
      const result = await exportVersion(version.id);
      if (live.current) setVersion(result);
    } catch (cause: unknown) {
      if (live.current) setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      if (live.current) setBusy(false);
    }
  }

  async function markSubmitted() {
    if (!version) return;
    setBusy(true);
    setError(null);
    try {
      const result = await submitVersion(version.id);
      // **Only after it resolves.** The screen must not describe a résumé as sent while
      // the request is still in flight: this is the action a person stops thinking about
      // the job after, and a premature "Submitted" is indistinguishable from one that
      // worked.
      if (live.current) setVersion(result);
    } catch (cause: unknown) {
      if (live.current) setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      if (live.current) setBusy(false);
    }
  }

  async function approve() {
    if (!version) return;
    setBusy(true);
    try {
      const approved = await approveVersion(version.id);
      if (live.current) setVersion(approved);
    } finally {
      if (live.current) setBusy(false);
    }
  }

  if (loading) {
    return (
      <p className="py-8 text-sm" style={{ color: "var(--muted)" }}>
        Loading…
      </p>
    );
  }

  // -- not yet tailored, and the specific reason it cannot start ------------
  if (version === null || (version.status === "draft" && !version.failure_reason)) {
    return (
      <div className="py-8">
        <p className="max-w-prose text-sm" style={{ color: "var(--muted)" }}>
          Tailor your resume to this posting. The agent proposes changes to your own wording; it
          cannot add experience you do not have, and nothing is saved until you approve it.
        </p>

        {refusal && (
          <p
            data-testid="refusal"
            data-reason={refusal}
            className="mt-3 max-w-prose border-l-2 pl-3 text-sm"
            style={{ borderColor: "var(--color-attention)", color: "var(--muted)" }}
          >
            {REFUSAL[refusal]}
          </p>
        )}
        {error && (
          <p role="alert" className="mt-3 text-sm" style={{ color: "var(--muted)" }}>
            {error}
          </p>
        )}

        <Button className="mt-4" disabled={busy} onClick={tailor}>
          {busy ? "Starting…" : "Tailor for this job"}
        </Button>
      </div>
    );
  }

  // -- in progress, with the step named ------------------------------------
  if (isInFlight(version)) {
    return <Working status={version.status as "tailoring" | "reviewing"} />;
  }

  // -- failed: `draft` carrying a reason, never a status of its own ---------
  if (version.status === "draft") {
    return (
      <div className="py-8">
        <p
          role="alert"
          className="max-w-prose border-l-2 pl-3 text-sm"
          style={{ borderColor: "var(--color-failure)" }}
        >
          {version.failure_reason}
        </p>
        <p className="mt-2 max-w-prose text-sm" style={{ color: "var(--muted)" }}>
          Nothing was saved and nothing else about this job is affected — your profile and your
          master resume are untouched. Trying again reuses this draft.
        </p>
        <Button className="mt-4" variant="outline" disabled={busy} onClick={tailor}>
          {busy ? "Starting…" : "Try again"}
        </Button>
      </div>
    );
  }

  const submitted = version.status === "submitted";
  const exported = version.status === "exported";
  // A submitted version still has a stored document, so the download stays; what it no
  // longer has is a way forward. Export is refused for it by `ensure_exportable` — the
  // state is terminal — so offering the button would be offering a 409.
  const approved = version.status === "ready" || exported || submitted;
  // Content frozen — `LOCKED_STATUSES` in `application/immutability.py`, which
  // is these two and not `ready`.
  const locked = exported || submitted;
  const proposals = version.items.filter(
    (item) => item.proposed_text !== null || item.findings.length > 0,
  );
  const untouched = version.items.length - proposals.length;
  const undecided = proposals.filter(
    (item) => item.decision === "pending" && item.proposed_text !== null,
  ).length;

  return (
    <div className="py-6" data-testid="tailor-diff" data-status={version.status}>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <p
            className="text-2xl leading-none"
            style={{ fontFamily: "var(--font-display)", color: "var(--foreground)" }}
          >
            {submitted ? "Sent" : approved ? "Approved" : "Ready for your approval"}
          </p>
          {/* Said once the request has actually resolved, never on the click. This is
              the state a person stops checking the job after, so it has to describe
              what happened rather than what was asked for — and it says the one thing
              that is not obvious: this version is finished, and changing the résumé for
              this job means tailoring it again (FR-025). */}
          {submitted && (
            <p data-testid="submitted-note" className="mt-1.5 text-sm" style={{ color: "var(--muted)" }}>
              This is the résumé on record for this job. To change it, tailor this job
              again — that produces a new version and leaves this one as it was sent.
            </p>
          )}
          <p className="mt-1.5 text-sm" style={{ color: "var(--muted)" }}>
            {version.confidence_score !== null && (
              <>
                <Confidence score={version.confidence_score} />
                {" · "}
              </>
            )}
            <span className="tabular" style={{ fontFamily: "var(--font-mono)" }}>
              {proposals.length}
            </span>{" "}
            proposed change{proposals.length === 1 ? "" : "s"}
          </p>
        </div>

        {/* Everything still undecided counts as accepted (FR-025) — the
            import-review precedent, where an untouched review adds everything
            not discarded. Said out loud, because a person who has read two of
            eleven rows should know what the button means before pressing it. */}
        {approved && (
          /* Export renders the approved items to a PDF and stores it (FR-015).
             The download is a separate link because downloading again must not
             export again — a second export is a second stored copy and a second
             record, which is not what a person pressing "download" is asking for. */
          <div className="flex items-center gap-3" data-testid="export-controls">
            {(exported || submitted) && (
              <a
                data-testid="download-pdf"
                href={versionDocumentUrl(version.id)}
                className="text-sm underline"
                style={{ color: "var(--foreground)" }}
              >
                Download PDF
              </a>
            )}
            {!submitted && (
              <Button variant="outline" disabled={busy} onClick={exportPdf}>
                {busy ? "Exporting…" : exported ? "Export again" : "Export as PDF"}
              </Button>
            )}
            {/* **The action this screen already instructs** (FR-025). A locked
                version's content cannot change, so tailoring again is the only
                way forward — it produces a new version and leaves this one as
                it was sent, which is what `create_pending_version` does by
                reusing a `draft` and nothing else. It was implemented, tested
                and unreachable: the submitted view said these words and offered
                no control that performed them.

                Not offered while the version is still `ready`, where the action
                a person wants is Edit rather than a second paid run. */}
            {locked && (
              <Button
                data-testid="retailor"
                variant="outline"
                disabled={busy}
                onClick={tailor}
              >
                {busy ? "Starting…" : "Tailor this job again"}
              </Button>
            )}
            {/* Offered only once a document exists, because a submission is a record
                *of that document* — there is nothing to freeze before then, and the
                endpoint refuses it. */}
            {exported && (
              <Button data-testid="submit-version" disabled={busy} onClick={markSubmitted}>
                {busy ? "Marking…" : "Mark as submitted"}
              </Button>
            )}
          </div>
        )}

        {!approved && (
          <div className="text-right">
            <Button disabled={busy} onClick={approve}>
              {busy ? "Approving…" : "Approve this version"}
            </Button>
            {undecided > 0 && (
              <p data-testid="approve-note" className="mt-1 text-xs" style={{ color: "var(--faint)" }}>
                {undecided} undecided will be accepted
              </p>
            )}
          </div>
        )}
      </div>

      {/* A refused or failed action has to say so **here**. Until T037 the only
          error surface was the start view, so a failure on this screen — an
          export refused with 409, an item decision rejected — set state nobody
          rendered and the button simply stopped being busy. Silence after a
          click reads as success. */}
      {error && (
        <p role="alert" data-testid="tailor-error" className="mt-4 text-sm" style={{ color: "var(--muted)" }}>
          {error}
        </p>
      )}

      {/* A refused *start* sets `refusal`, not `error`, and only the start view
          used to render it — so re-tailoring from here would have set state
          nobody displayed. `stale_analysis` is the likely refusal at this point
          rather than an edge case: this version was written against a match
          that is by now several actions old. */}
      {refusal && (
        <p
          data-testid="refusal"
          data-reason={refusal}
          className="mt-4 max-w-prose border-l-2 pl-3 text-sm"
          style={{ borderColor: "var(--color-attention)", color: "var(--muted)" }}
        >
          {REFUSAL[refusal]}
        </p>
      )}

      {/* `uncovered` findings concern the draft as a whole — there is no item
          for an unaddressed requirement to attach to, and inventing one would
          demand a reference the Reviewer has no honest basis to give. */}
      {version.draft_findings.length > 0 && (
        <ul className="mt-5" data-testid="draft-findings">
          {version.draft_findings.map((finding, index) => (
            <Finding key={index} finding={finding} />
          ))}
        </ul>
      )}

      {/* **Locked, not merely approved.** `application/immutability.py` freezes
          content at `exported` and `submitted` and nowhere else, so every
          `Accept`, `Reject` and `Edit` on one of those is a guaranteed 409 —
          the import reviewer's old `Keep` button, which changed nothing, by
          another name. `ready` is deliberately excluded: FR-029 requires an
          approved version to stay editable, and reusing `approved` here — the
          flag the export controls are gated on — is the plausible stricter
          reading that would take that away. The rows still render in full; what
          is withdrawn is the offer to change them, not the document. */}
      <ul className="mt-5">
        {proposals.map((item) => (
          <TailorDiffItem
            key={item.id}
            item={item}
            disabled={locked}
            onDecide={(decision, text) => decide(item.id, decision, text)}
          />
        ))}
      </ul>

      {untouched > 0 && (
        <p className="mt-3 text-xs" style={{ color: "var(--faint)" }}>
          {untouched} item{untouched === 1 ? "" : "s"} left unchanged.
        </p>
      )}

      {run && <RunDetail run={run} />}

      {/* Principle III, at the surface a person approves from (FR-022):
          visibly AI-generated, naming what produced it and what it cost.
          Monospace, because it is reported verbatim (docs/09 §1). */}
      <p
        data-testid="version-provenance"
        className="mt-8 border-t pt-3 text-xs"
        style={{ borderColor: "var(--border)", color: "var(--faint)" }}
      >
        <span style={{ fontFamily: "var(--font-mono)" }}>
          Written by AI · {version.model ?? "unknown"} · ${version.cost ?? "0"}
        </span>
        {version.is_fixture && (
          <span data-testid="fixture" style={{ color: "var(--color-fixture)" }}>
            {" · FIXTURE DATA — not a real draft"}
          </span>
        )}
      </p>
    </div>
  );
}
