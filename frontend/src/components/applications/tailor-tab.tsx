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

import { Finding, KIND_LABEL, TailorDiffItem } from "@/components/applications/tailor-diff-item";
import { Button } from "@/components/ui/button";
import {
  type ProposalDecision,
  type RefusalReason,
  type ResumeVersion,
  type TailoringRun,
  type VersionItem,
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

/**
 * Split an `uncovered` finding's detail into WHAT the posting asks for (its
 * first sentence — measured across all 293 recorded findings, the Reviewer
 * consistently opens with the requirement) and WHY it could not be addressed
 * (the rest). **A substring split, never a paraphrase**: the two parts
 * concatenate back to the original text. Sentence boundaries respect closing
 * quotes/brackets and skip abbreviations (the `e.g.` trap was real: one
 * recorded detail reads "framework (e.g. LangGraph)"). A single-sentence
 * detail returns `explanation: null` and renders whole in the header.
 */
export function splitGapDetail(detail: string): {
  requirement: string;
  explanation: string | null;
} {
  const boundary = /[.!?]["”’)\]]?\s+(?=["‘“(A-Z0-9])/g;
  const abbrev = /\b(?:e\.g|i\.e|etc|vs|approx)\.$/i;
  let match: RegExpExecArray | null;
  while ((match = boundary.exec(detail)) !== null) {
    const punctuationEnd =
      match.index + 1 + (/["”’)\]]/.test(detail[match.index + 1] ?? "") ? 1 : 0);
    const first = detail.slice(0, punctuationEnd);
    if (abbrev.test(first.replace(/["”’)\]]+$/, ""))) continue;
    return { requirement: first, explanation: detail.slice(match.index + match[0].length) };
  }
  return { requirement: detail, explanation: null };
}

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

/** Every distinct model the run used, for the provenance line.
 *
 * **Not `version.model`, which is the *drafting* model alone.** A run puts
 * Review on a stronger model by configuration and escalates Revise to it on a
 * second attempt, so a two-model run is the normal case rather than the
 * exception. Naming one of them beside the run's *total* cost reads as "this
 * model cost that much" — understating attribution on the one screen where a
 * person sees what a run spent (T088: Sonnet drafted, Opus reviewed at 5x the
 * input price, and the line said Sonnet).
 *
 * Falls back to the version's own field when there is no run to read — a
 * failed or in-flight version still has to say what wrote it.
 */
function modelsUsed(version: ResumeVersion, run: TailoringRun | null): string {
  const distinct = run ? [...new Set(Object.values(run.models))].sort() : [];
  return distinct.length > 0 ? distinct.join(" + ") : (version.model ?? "unknown");
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
  // Which item ids entered this version's change list — sticky per version id;
  // see the comment where it is (re)built below.
  const membership = useRef<{ versionId: string | null; ids: Set<string> }>({
    versionId: null,
    ids: new Set(),
  });
  // The redesign's one-open-at-a-time accordion. **Derived, not effectful**:
  // until the owner touches it for this version, the open card is the first
  // pending proposal (the mockup's "expanded recommendation" default); after
  // that, it is exactly what they chose. An effect-based init raced the first
  // click in tests — a selection that exists only after a flush is a
  // selection that sometimes is not there.
  const [openSel, setOpenSel] = useState<{ versionId: string; id: string | null } | null>(null);
  const [gapsOpen, setGapsOpen] = useState(false);
  const [openGap, setOpenGap] = useState<number | null>(null);
  const gapsRef = useRef<HTMLDivElement>(null);
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

  /** Accept every pending proposal, one decision at a time through the same
   *  endpoint the buttons use. Deliberately not `approve`: FR-025's blanket
   *  accept lives on the Approve button and also transitions the version —
   *  this only records decisions, and approving stays a separate, explicit
   *  step. */
  async function acceptAll() {
    if (!version) return;
    const pending = version.items.filter(
      (item) => (item.proposed_text !== null || !item.included) && item.decision === "pending",
    );
    setBusy(true);
    setError(null);
    try {
      for (const item of pending) {
        const updated = await decideItem(version.id, item.id, "accepted");
        if (!live.current) return;
        setVersion((current) =>
          current
            ? { ...current, items: current.items.map((i) => (i.id === updated.id ? updated : i)) }
            : current,
        );
      }
      if (live.current) setOpenSel({ versionId: version.id, id: null });
    } catch (cause: unknown) {
      if (live.current) setError(cause instanceof Error ? cause.message : String(cause));
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
      // would discard any edit in progress on a neighbouring row. A functional
      // updater, because two decisions can be in flight at once — the render
      // closure's snapshot would let the later response erase the earlier
      // item's update, exactly as `acceptAll` already avoids.
      if (live.current) {
        setVersion((current) =>
          current
            ? {
                ...current,
                items: current.items.map((item) => (item.id === updated.id ? updated : item)),
              }
            : current,
        );
        // The mockup collapses a card once it is decided — the decision shows
        // in its header, and the next undecided card is one click away.
        setOpenSel({ versionId: version.id, id: null });
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
  // Only items with a surviving proposal are decisions; they get a row and the
  // controls. An item whose proposal was discarded at finalisation (FR-018 —
  // `proposed_text` null, findings attached) is **not rendered**: the owner's
  // wording already stands, there is nothing to decide, and the old
  // "Withdrawn before saving" entry read as a verdict on the owner's own
  // bullet. The finding stays in the run record; it just is not an entry here.
  // A drop (`included: false`) is a proposed change to existing content —
  // FR-024 makes it per-item decidable, so it renders with the same controls
  // as a rewrite. Rejecting one restores the line (`included` comes back
  // true), at which point the row is again indistinguishable from unchanged —
  // one representation of "no change", the same rule finalisation follows —
  // and it leaves this list.
  const decidable = (item: VersionItem) => item.proposed_text !== null || !item.included;
  // **Membership is sticky for the life of this version on screen.** A
  // rejected drop's stored shape becomes identical to unchanged content, so a
  // filter over current shape alone would remove the row the instant the
  // owner clicks Reject — a decision that vanishes from under the click looks
  // like a glitch, not an answer. The set is rebuilt only when the version id
  // changes; a retried run reusing the id still surfaces new proposals via
  // the shape check below.
  if (membership.current.versionId !== version.id) {
    membership.current = {
      versionId: version.id,
      ids: new Set(version.items.filter(decidable).map((item) => item.id)),
    };
  }
  const proposals = version.items.filter(
    (item) => decidable(item) || membership.current.ids.has(item.id),
  );
  // A position-only proposal moved a line in the document. Ordering is
  // approved at version level (FR-025), so it gets no per-item controls — but
  // counting it "left unchanged" was a false statement about the resume, so
  // it is counted as what it is. `displaced_position` is the record that a
  // proposal arrived; findings exclude the discarded-proposal shape, which
  // also carries it.
  const reordered = version.items.filter(
    (item) =>
      !decidable(item) &&
      !membership.current.ids.has(item.id) &&
      item.displaced_position !== null &&
      item.findings.length === 0,
  ).length;
  const untouched = version.items.length - proposals.length - reordered;
  // Every entry above is decidable — a rewrite and a drop alike — so pending
  // alone is the count the approve note needs (FR-025).
  const undecided = proposals.filter((item) => item.decision === "pending").length;
  const decided = proposals.length - undecided;
  const rewrites = proposals.filter((item) => item.proposed_text !== null).length;
  const removals = proposals.filter((item) => !item.included).length;
  // The section chips: every kind, with how many proposals it carries.
  const kinds = Object.keys(KIND_LABEL) as (keyof typeof KIND_LABEL)[];
  const proposalsByKind = new Map(
    kinds.map((kind) => [kind, proposals.filter((item) => item.source_kind === kind)]),
  );
  const sectionsTouched = kinds.filter((kind) => (proposalsByKind.get(kind) ?? []).length > 0);
  const pendingByKind = new Map(
    kinds.map((kind) => [
      kind,
      (proposalsByKind.get(kind) ?? []).filter((item) => item.decision === "pending").length,
    ]),
  );
  const openItemId =
    openSel && openSel.versionId === version.id
      ? openSel.id
      : (proposals.find((item) => item.decision === "pending")?.id ?? null);

  return (
    <div className="py-6" data-testid="tailor-diff" data-status={version.status}>
      {/* The redesign's summary card: grounding on the left, the proposal
          arithmetic in the middle, the actions on the right. Same facts as
          before — confidence (FR-043's own label), counts derived from the
          rows, the FR-025 approve semantics — arranged as one surface. */}
      <div
        data-testid="tailor-summary"
        className="flex flex-wrap items-start gap-6 rounded-xl border p-5"
        style={{ borderColor: "var(--border)", background: "var(--surface)" }}
      >
        {version.confidence_score !== null && (
          <>
            <div className="w-44 flex-none">
              <p
                className="text-[10px] tracking-widest uppercase"
                style={{ fontFamily: "var(--font-mono)", color: "var(--faint)" }}
              >
                Grounding score
              </p>
              <p
                className="mt-1 text-4xl leading-none"
                style={{ fontFamily: "var(--font-display)", color: "var(--color-brand-500)" }}
              >
                {version.confidence_score}
                <span className="text-base" style={{ color: "var(--faint)" }}>
                  /100
                </span>
              </p>
              <div
                className="mt-2 h-1 overflow-hidden rounded-full"
                style={{ background: "color-mix(in srgb, var(--foreground) 8%, transparent)" }}
              >
                <div
                  className="h-full"
                  style={{
                    width: `${version.confidence_score}%`,
                    background: "var(--color-brand-500)",
                  }}
                />
              </div>
              {/* The canonical label (FR-043) — the number above is this same
                  score, never a second one. */}
              <p className="mt-2 text-xs">
                <Confidence score={version.confidence_score} />
              </p>
            </div>
            <div className="hidden w-px self-stretch sm:block" style={{ background: "var(--border)" }} />
          </>
        )}

        <div className="min-w-0 flex-1">
          <p
            className="text-2xl leading-none"
            style={{ fontFamily: "var(--font-display)", color: "var(--foreground)" }}
          >
            {submitted ? "Sent" : approved ? "Approved" : "Ready for your approval"}
          </p>
          {/* Said once the request has actually resolved, never on the click. */}
          {submitted && (
            <p data-testid="submitted-note" className="mt-1.5 text-sm" style={{ color: "var(--muted)" }}>
              This is the résumé on record for this job. To change it, tailor this job
              again — that produces a new version and leaves this one as it was sent.
            </p>
          )}
          <p className="mt-2 text-sm" style={{ color: "var(--muted)" }}>
            <span className="tabular" style={{ fontFamily: "var(--font-mono)" }}>
              {proposals.length}
            </span>{" "}
            proposed change{proposals.length === 1 ? "" : "s"} across {sectionsTouched.length} CV{" "}
            section{sectionsTouched.length === 1 ? "" : "s"}.
            {version.draft_findings.length > 0 && (
              <span style={{ color: "var(--faint)" }}>
                {" "}
                {version.draft_findings.length} requirement
                {version.draft_findings.length === 1 ? "" : "s"} could not be supported from your
                profile.
              </span>
            )}
          </p>
          {/* Counts by what the change *is* — the payload carries no impact
              tiers, and inventing High/Medium/Low here would be a claim the
              agent never made. */}
          <div className="mt-3 flex gap-5 text-xs" style={{ color: "var(--muted)" }}>
            {(
              [
                ["Rewrites", rewrites],
                ["Removals", removals],
                ["Reordered", reordered],
                ["Decided", decided],
              ] as const
            ).map(([label, count]) => (
              <span key={label} className="flex flex-col gap-0.5">
                <span
                  className="text-base font-bold"
                  style={{ color: count > 0 ? "var(--foreground)" : "var(--faint)" }}
                >
                  {count}
                </span>
                {label}
              </span>
            ))}
          </div>
        </div>

        {approved && (
          /* Export renders the approved items to a PDF and stores it (FR-015).
             The download is a separate link because downloading again must not
             export again. */
          <div className="flex flex-none items-center gap-3" data-testid="export-controls">
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
            {locked && (
              <Button data-testid="retailor" variant="outline" disabled={busy} onClick={tailor}>
                {busy ? "Starting…" : "Tailor this job again"}
              </Button>
            )}
            {exported && (
              <Button data-testid="submit-version" disabled={busy} onClick={markSubmitted}>
                {busy ? "Marking…" : "Mark as submitted"}
              </Button>
            )}
          </div>
        )}

        {!approved && (
          <div className="flex w-44 flex-none flex-col gap-2 text-right">
            {/* Everything still undecided counts as accepted (FR-025) — said
                out loud below, because a person who has read two of eleven
                rows should know what the button means before pressing it. */}
            <Button disabled={busy} onClick={approve}>
              {busy ? "Approving…" : "Approve this version"}
            </Button>
            {undecided > 0 && (
              <Button variant="outline" disabled={busy} onClick={acceptAll}>
                Accept all {undecided}
              </Button>
            )}
            {undecided > 0 && (
              <p data-testid="approve-note" className="text-xs" style={{ color: "var(--faint)" }}>
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

      {/* **Locked, not merely approved.** `application/immutability.py` freezes
          content at `exported` and `submitted` and nowhere else, so every
          `Accept`, `Reject` and `Edit` on one of those is a guaranteed 409 —
          the import reviewer's old `Keep` button, which changed nothing, by
          another name. `ready` is deliberately excluded: FR-029 requires an
          approved version to stay editable, and reusing `approved` here — the
          flag the export controls are gated on — is the plausible stricter
          reading that would take that away. The rows still render in full; what
          is withdrawn is the offer to change them, not the document. */}
      {/* CV sections, as chips: every kind the résumé can hold, with how many
          proposals it carries. Clicking opens that section's first card. */}
      <div className="mt-6">
        <p
          className="text-[10px] tracking-widest uppercase"
          style={{ fontFamily: "var(--font-mono)", color: "var(--faint)" }}
        >
          CV sections
        </p>
        <div className="mt-2 flex flex-wrap gap-2" data-testid="section-chips">
          {kinds.map((kind) => {
            const inKind = proposalsByKind.get(kind) ?? [];
            const pending = pendingByKind.get(kind) ?? 0;
            const touched = inKind.length > 0;
            // The chips speak the tab's semantic palette: amber while one or
            // more of the section's proposals still await a decision — the
            // count is the *pending* count, not the historical total — green
            // once every proposal in the section is decided, the quiet clear
            // treatment when nothing was proposed, red only on the gaps chip.
            const accent = pending > 0 ? "var(--color-attention)" : "var(--color-brand-500)";
            return (
              <button
                key={kind}
                type="button"
                disabled={!touched}
                onClick={() => setOpenSel({ versionId: version.id, id: inKind[0]?.id ?? null })}
                className="flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs font-semibold"
                style={{
                  borderColor: touched
                    ? `color-mix(in srgb, ${accent} 35%, transparent)`
                    : "var(--border)",
                  background: touched ? "var(--surface)" : "transparent",
                  color: touched ? accent : "var(--faint)",
                }}
              >
                {KIND_LABEL[kind]}
                {touched && pending > 0 && (
                  <span
                    className="rounded px-1.5 py-0.5 text-[10px]"
                    style={{
                      fontFamily: "var(--font-mono)",
                      color: "var(--color-attention)",
                      background: "color-mix(in srgb, var(--color-attention) 14%, transparent)",
                    }}
                  >
                    {pending}
                  </span>
                )}
                {touched && pending === 0 && <span aria-hidden>✓</span>}
                {!touched && <span style={{ color: "var(--faint)", fontWeight: 400 }}>clear</span>}
              </button>
            );
          })}
          {version.draft_findings.length > 0 && (
            <button
              type="button"
              data-testid="gaps-chip"
              onClick={() => gapsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })}
              className="flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs font-semibold"
              style={{
                borderColor: "color-mix(in srgb, var(--color-failure) 35%, transparent)",
                background: "var(--surface)",
                color: "var(--color-failure)",
              }}
            >
              Gaps
              <span
                className="rounded px-1.5 py-0.5 text-[10px]"
                style={{
                  fontFamily: "var(--font-mono)",
                  color: "var(--color-failure)",
                  background: "color-mix(in srgb, var(--color-failure) 14%, transparent)",
                }}
              >
                {version.draft_findings.length}
              </span>
            </button>
          )}
        </div>
      </div>

      <div className="mt-6 flex items-baseline justify-between">
        <h2
          className="text-base font-bold"
          style={{ color: "var(--foreground)", letterSpacing: "-0.01em" }}
        >
          Changes we recommend
        </h2>
        <span className="text-xs" style={{ color: "var(--muted)" }}>
          {undecided} of {proposals.length} awaiting your decision
        </span>
      </div>

      <ul className="mt-3">
        {proposals.map((item) => (
          <TailorDiffItem
            key={item.id}
            item={item}
            disabled={locked}
            open={openItemId === item.id}
            onToggle={() =>
              setOpenSel({ versionId: version.id, id: openItemId === item.id ? null : item.id })
            }
            onDecide={(decision, text) => decide(item.id, decision, text)}
          />
        ))}
      </ul>

      {(untouched > 0 || reordered > 0) && (
        <p className="mt-3 text-xs" style={{ color: "var(--faint)" }}>
          {untouched > 0 && `${untouched} item${untouched === 1 ? "" : "s"} left unchanged.`}
          {untouched > 0 && reordered > 0 && " "}
          {reordered > 0 && `${reordered} reordered by the agent.`}
        </p>
      )}

      {/* `uncovered` findings concern the draft as a whole — there is no item
          for an unaddressed requirement to attach to, and inventing one would
          demand a reference the Reviewer has no honest basis to give. The
          redesign renders them as a collapsed section with one expandable row
          per requirement. **No REQUIRED/PREFERRED tiers**: the payload does
          not carry requirement importance, and inventing a tier here would be
          a claim nobody made. */}
      {version.draft_findings.length > 0 && (
        <div
          ref={gapsRef}
          data-testid="draft-findings"
          className="mt-6 overflow-hidden rounded-xl border"
          style={{
            // Red, deliberately: the tab's convention is green = keep,
            // amber = proposed change, red = missing/unsupported. Soft mixes
            // keep it reading as "gap", not as a system error.
            borderColor: "color-mix(in srgb, var(--color-failure) 30%, transparent)",
            background: "var(--surface)",
          }}
        >
          <button
            type="button"
            data-testid="gaps-toggle"
            onClick={() => setGapsOpen((current) => !current)}
            className="flex w-full items-center gap-3.5 px-4 py-3.5 text-left"
          >
            <span
              className="flex-none rounded px-2 py-1 text-[10px] tracking-wider"
              style={{
                fontFamily: "var(--font-mono)",
                color: "var(--color-failure)",
                background: "color-mix(in srgb, var(--color-failure) 13%, transparent)",
              }}
            >
              GAPS
            </span>
            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
              <span className="flex items-center gap-2">
                <span
                  className="text-xs font-semibold tracking-wider"
                  style={{ fontFamily: "var(--font-mono)", color: "var(--foreground)" }}
                >
                  GAPS WE COULDN'T ADDRESS
                </span>
                <span
                  className="rounded px-1.5 py-0.5 text-[10px]"
                  style={{
                    fontFamily: "var(--font-mono)",
                    color: "var(--color-failure)",
                    background: "color-mix(in srgb, var(--color-failure) 12%, transparent)",
                  }}
                >
                  {version.draft_findings.length} requirement
                  {version.draft_findings.length === 1 ? "" : "s"}
                </span>
              </span>
              <span className="text-xs" style={{ color: "var(--muted)" }}>
                Job requirements with no supporting evidence in your profile
              </span>
            </span>
            <span
              aria-hidden
              className="flex h-6 w-6 flex-none items-center justify-center rounded-md text-sm"
              style={{
                color: "var(--color-failure)",
                background: "color-mix(in srgb, var(--color-failure) 12%, transparent)",
              }}
            >
              {gapsOpen ? "−" : "+"}
            </span>
          </button>
          {gapsOpen && (
            <div className="flex flex-col gap-2 px-4 pt-0.5 pb-4">
              {version.draft_findings.map((finding, index) => (
                <div
                  key={index}
                  className="overflow-hidden rounded-lg border"
                  style={{
                    borderColor: "color-mix(in srgb, var(--color-failure) 18%, transparent)",
                  }}
                >
                  <button
                    type="button"
                    onClick={() => setOpenGap((current) => (current === index ? null : index))}
                    className="flex w-full items-center gap-3 px-3.5 py-3 text-left"
                  >
                    {/* WHAT the posting asks for — the detail's own first
                        sentence, verbatim. The WHY lives in the expansion. */}
                    <span className="min-w-0 flex-1 truncate text-sm font-semibold">
                      {splitGapDetail(finding.detail).requirement}
                    </span>
                    <span aria-hidden className="flex-none text-sm" style={{ color: "var(--color-failure)" }}>
                      {openGap === index ? "−" : "+"}
                    </span>
                  </button>
                  {openGap === index && (
                    <div className="px-3.5 pb-3.5">
                      <p className="text-xs font-bold" style={{ color: "var(--foreground)" }}>
                        Why we couldn't address this
                      </p>
                      <ul>
                        {/* The explanatory remainder of the same detail — the
                            header already said the requirement. A
                            single-sentence detail has nothing further, so the
                            whole text stands rather than an invented reason. */}
                        <Finding
                          finding={finding}
                          detailText={splitGapDetail(finding.detail).explanation ?? undefined}
                        />
                      </ul>
                      <p className="mt-2 text-xs" style={{ color: "var(--faint)" }}>
                        No change was proposed. Nothing was added to your résumé to cover this
                        requirement.
                      </p>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
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
          Written by AI · {modelsUsed(version, run)} · ${version.cost ?? "0"}
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
