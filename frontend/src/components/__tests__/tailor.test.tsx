import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TailorDiffItem } from "@/components/applications/tailor-diff-item";
import { TailorTab } from "@/components/applications/tailor-tab";
import { ApiError } from "@/lib/api";
import type {
  ExportedVersion,
  ResumeVersion,
  TailoringRun,
  ReviewerFinding,
  SubmittedVersion,
  VersionItem,
} from "@/lib/api";

/**
 * The Tailor tab, at the surface where Principle II is actually enforced.
 *
 * Every display bug this project has shipped was found by a person looking at
 * real data, never by the suite — contact fields, bullet attribution, skill
 * categories and project URLs were each extracted correctly and dropped by the
 * renderer. So these tests deliberately do not try to prove the screen looks
 * right. They prove the things a person cannot check by looking:
 *
 * * that the five states render as **five different things** (FR-039), because
 *   each one is perfectly convincing on its own and only the set is wrong;
 * * that a discarded claim reaches **no approve button** (FR-018), which is a
 *   release blocker and is invisible on a screen where it correctly does not
 *   appear;
 * * that rejecting starts **no** AI work (FR-026), which looks identical to
 *   working code right up until it bills someone.
 */

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    listVersions: vi.fn(),
    getVersion: vi.fn(),
    getTailoringRun: vi.fn(),
    startTailoring: vi.fn(),
    decideItem: vi.fn(),
    approveVersion: vi.fn(),
    exportVersion: vi.fn(),
    submitVersion: vi.fn(),
  };
});

const api = await import("@/lib/api");
const mocked = vi.mocked(api);

function finding(overrides: Partial<ReviewerFinding> = {}): ReviewerFinding {
  return {
    kind: "overstated",
    detail: "“Owned” inflates a team lead role.",
    quoted_text: "Owned the payments platform",
    attempt: 0,
    ...overrides,
  };
}

function item(overrides: Partial<VersionItem> = {}): VersionItem {
  return {
    id: "item-1",
    source_kind: "experience_bullet",
    source_item_id: "bullet-1",
    position: 0,
    included: true,
    original_text: "Led the payments platform team for six years.",
    proposed_text: "Owned the payments platform for six years.",
    final_text: "Owned the payments platform for six years.",
    decision: "pending",
    findings: [],
    ...overrides,
  };
}

function version(overrides: Partial<ResumeVersion> = {}): ResumeVersion {
  return {
    id: "version-1",
    application_id: "app-1",
    name: "Senior Backend Engineer — tailored",
    professional_title: null,
    status: "awaiting_approval",
    confidence_score: 82,
    failure_reason: null,
    model: "anthropic/claude-sonnet-5",
    is_fixture: false,
    cost: "0.081000",
    source_profile_updated_at: "2026-08-24T10:00:00+00:00",
    created_at: "2026-08-24T10:00:00+00:00",
    items: [item()],
    draft_findings: [],
    ...overrides,
  };
}

/** Render the tab against one version, resolved as the API would. */
async function renderTab(value: ResumeVersion | null) {
  mocked.listVersions.mockResolvedValue({
    versions: value
      ? [
          {
            id: value.id,
            name: value.name,
            status: value.status,
            confidence_score: value.confidence_score,
            created_at: value.created_at,
          },
        ]
      : [],
  });
  if (value) mocked.getVersion.mockResolvedValue(value);
  mocked.getTailoringRun.mockRejectedValue(new ApiError(404, "No run for this version."));

  const rendered = render(<TailorTab applicationId="app-1" />);
  await waitFor(() => expect(screen.queryByText("Loading…")).toBeNull());
  return rendered;
}

/** Render against a version whose run *is* available, with a given model map.
 *
 * `renderTab` rejects `getTailoringRun` with a 404, so `run` is null in every
 * test that uses it — which is why nothing caught the two-model attribution
 * bug. A run has to actually be present for that line to be testable at all.
 */
async function renderTabWithRun(value: ResumeVersion, models: Record<string, string>) {
  mocked.listVersions.mockResolvedValue({
    versions: [
      {
        id: value.id,
        name: value.name,
        status: value.status,
        confidence_score: value.confidence_score,
        created_at: value.created_at,
      },
    ],
  });
  mocked.getVersion.mockResolvedValue(value);
  mocked.getTailoringRun.mockResolvedValue({
    id: "run-1",
    version_id: value.id,
    status: "succeeded",
    failure_reason: null,
    plan: null,
    attempts: 0,
    match_analysis_id: "match-1",
    guidelines_used: [],
    models,
    finalisation_rules_version: "v1",
    input_tokens: 35785,
    output_tokens: 18808,
    cost: value.cost ?? "0",
    is_fixture: false,
    started_at: value.created_at,
    finished_at: value.created_at,
  } satisfies TailoringRun);

  const rendered = render(<TailorTab applicationId="app-1" />);
  await waitFor(() => expect(screen.queryByText("Loading…")).toBeNull());
  return rendered;
}

beforeEach(() => {
  vi.clearAllMocks();
});

// -- FR-039: five states, and they must be five -----------------------------

describe("the five states", () => {
  it("renders each one as something different", async () => {
    const states: { label: string; value: ResumeVersion | null }[] = [
      { label: "not yet tailored", value: null },
      { label: "tailoring", value: version({ status: "tailoring", items: [] }) },
      { label: "awaiting approval", value: version({ status: "awaiting_approval" }) },
      { label: "approved", value: version({ status: "ready" }) },
      {
        label: "failed",
        value: version({
          status: "draft",
          items: [],
          confidence_score: null,
          failure_reason: "RuntimeError: the provider timed out",
        }),
      },
    ];

    const rendered: string[] = [];
    for (const state of states) {
      await renderTab(state.value);
      rendered.push((document.body.textContent ?? "").trim());
      document.body.innerHTML = "";
    }

    // Not "all five differ from each other in some way" — five *distinct*
    // renderings. A version that conflated two would still pass a per-state
    // assertion, which is exactly how "not scored yet" came to read as
    // "failed" on the Match tab before docs/09 §5 was written.
    expect(new Set(rendered).size).toBe(5);
  });

  it("distinguishes writing from checking its own work", async () => {
    await renderTab(version({ status: "tailoring", items: [] }));
    const writing = screen.getByTestId("working-step").textContent;
    document.body.innerHTML = "";

    await renderTab(version({ status: "reviewing", items: [] }));
    const checking = screen.getByTestId("working-step").textContent;

    // FR-040, and the entire reason `awaiting_approval` exists as a status.
    // One spinner for both means a person cannot tell a machine working for
    // forty seconds from a queue that has been waiting on them since Tuesday.
    expect(writing).not.toEqual(checking);
  });

  it("does not present a failed run as a status of its own", async () => {
    await renderTab(
      version({
        status: "draft",
        items: [],
        failure_reason: "RuntimeError: the provider timed out",
      }),
    );

    // The version returns to `draft` and the run carries the reason. What is
    // left is an untailored resume plus an explanation, and the recovery is
    // simply tailoring again.
    expect(screen.getByRole("alert")).toHaveTextContent("the provider timed out");
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });

  it("says nothing was saved when a run fails", async () => {
    await renderTab(
      version({ status: "draft", items: [], failure_reason: "TimeoutError: no response" }),
    );

    // FR-044. A failed run must not read as damage to the profile — which is
    // the first thing a person fears when an agent that rewrites their resume
    // reports an error.
    expect(document.body.textContent).toMatch(/untouched/i);
  });
});

// -- FR-018: a discarded claim reaches no button ----------------------------

describe("a claim the Reviewer could not ground", () => {
  it("offers no way to approve it", async () => {
    await renderTab(
      version({
        items: [
          item({
            // Discarded before persistence: the proposal is gone, the finding
            // remains as the evidence the guardrail ran.
            proposed_text: null,
            final_text: "Led the payments platform team for six years.",
            findings: [
              finding({
                kind: "ungrounded",
                detail: "The profile never mentions Kubernetes.",
                quoted_text: "Ran Kubernetes clusters across three regions",
              }),
            ],
          }),
        ],
      }),
    );

    const row = screen.getByTestId("diff-item");
    expect(within(row).queryByRole("button", { name: /^accept$/i })).toBeNull();
    expect(within(row).queryByRole("button", { name: /^reject$/i })).toBeNull();
    expect(within(row).getByTestId("discarded")).toBeInTheDocument();
  });

  it("does not reprint the fabricated wording as though it were on offer", async () => {
    const fabricated = "Ran Kubernetes clusters across three regions";
    await renderTab(
      version({
        items: [
          item({
            proposed_text: null,
            final_text: "Led the payments platform team for six years.",
            findings: [finding({ kind: "ungrounded", detail: "Not in the profile.", quoted_text: fabricated })],
          }),
        ],
      }),
    );

    // The finding quotes it once, in the Reviewer's own words, as the thing
    // that was removed. Showing it a second time under "Proposed" would put
    // the invented claim back on the page beside an approve control, which is
    // the discard defeated by presentation rather than by logic.
    const occurrences = (document.body.textContent ?? "").split(fabricated).length - 1;
    expect(occurrences).toBe(1);
  });
});

// -- FR-042: a finding sits against what it concerns ------------------------

describe("Reviewer findings", () => {
  it("renders against the proposal rather than as a page banner", async () => {
    await renderTab(version({ items: [item({ findings: [finding()] }), item({ id: "item-2" })] }));

    const rows = screen.getAllByTestId("diff-item");
    expect(within(rows[0]).getByTestId("finding")).toBeInTheDocument();
    expect(within(rows[1]).queryByTestId("finding")).toBeNull();
  });

  it("keeps an unaddressed requirement at draft level, with no item", async () => {
    await renderTab(
      version({
        draft_findings: [
          finding({ kind: "uncovered", detail: "Kubernetes is never addressed.", quoted_text: null }),
        ],
      }),
    );

    // `uncovered` concerns the draft as a whole. Attaching it to an arbitrary
    // item would demand a reference the Reviewer has no honest basis to give —
    // the same trap slice 004 fell into demanding a shortfall on `unverified`.
    const banner = screen.getByTestId("draft-findings");
    expect(within(banner).getByTestId("finding")).toHaveAttribute("data-kind", "uncovered");
    expect(within(screen.getByTestId("diff-item")).queryByTestId("finding")).toBeNull();
  });
});

// -- FR-041, FR-024, FR-026, FR-027: the decision controls ------------------

describe("deciding one proposal", () => {
  it("shows the original beside the proposal", () => {
    render(<TailorDiffItem item={item()} onDecide={vi.fn()} />);

    // FR-041. A proposal shown without what it replaces asks a person to
    // approve a change they cannot see.
    expect(screen.getByTestId("original-text")).toHaveTextContent("Led the payments platform");
    expect(screen.getByTestId("proposed-text")).toHaveTextContent("Owned the payments platform");
  });

  it("offers accept, reject and edit on every item", () => {
    render(<TailorDiffItem item={item()} onDecide={vi.fn()} />);

    // FR-024: per item, not only for the draft as a whole.
    for (const name of [/^accept$/i, /^reject$/i, /^edit$/i]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
  });

  it("offers the same three controls whatever the item is", () => {
    // One render path for every source kind. The import reviewer had two and
    // lost an affordance from the second one three separate times — Edit, then
    // Add, then Remove — because nothing required them to match.
    const kinds = ["summary", "skill", "project", "education", "language"] as const;
    for (const kind of kinds) {
      const { unmount } = render(<TailorDiffItem item={item({ source_kind: kind })} onDecide={vi.fn()} />);
      expect(screen.getByRole("button", { name: /^accept$/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /^reject$/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /^edit$/i })).toBeInTheDocument();
      unmount();
    }
  });

  it("rejecting records the decision and triggers no AI work", async () => {
    mocked.decideItem.mockResolvedValue(
      item({ decision: "rejected", final_text: "Led the payments platform team for six years." }),
    );
    await renderTab(version());

    await userEvent.click(screen.getByRole("button", { name: /^reject$/i }));

    await waitFor(() => expect(mocked.decideItem).toHaveBeenCalledWith("version-1", "item-1", "rejected", undefined));
    // FR-026. Rejecting is the action that means "stop"; a re-draft here would
    // be a provider call the person explicitly declined.
    expect(mocked.startTailoring).not.toHaveBeenCalled();
  });

  it("an edit is stored as the owner's words, distinguishable from both", async () => {
    mocked.decideItem.mockResolvedValue(item({ decision: "edited", final_text: "My own wording." }));
    await renderTab(version());

    await userEvent.click(screen.getByRole("button", { name: /^edit$/i }));
    const field = screen.getByLabelText(/edit experience/i);
    await userEvent.clear(field);
    await userEvent.type(field, "My own wording.");
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() =>
      expect(mocked.decideItem).toHaveBeenCalledWith("version-1", "item-1", "edited", "My own wording."),
    );
    // FR-027: `edited` is what keeps owner-written text tellable apart from
    // both the agent's proposal and the master's original.
    expect(screen.getByTestId("decision-label")).toHaveTextContent(/your words/i);
  });

  it("will not save an empty edit", async () => {
    render(<TailorDiffItem item={item()} onDecide={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: /^edit$/i }));
    await userEvent.clear(screen.getByLabelText(/edit experience/i));

    expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
  });
});

// -- FR-025: what approval means, said before it is pressed -----------------

describe("approval", () => {
  it("says how many undecided items it will accept", async () => {
    await renderTab(version({ items: [item(), item({ id: "item-2" })] }));

    // The import-review precedent — an untouched review adds everything not
    // discarded — but a person who has read two of eleven rows should know
    // what the button means before pressing it, not after.
    expect(screen.getByTestId("approve-note")).toHaveTextContent("2 undecided will be accepted");
  });

  it("starts nothing further", async () => {
    mocked.approveVersion.mockResolvedValue(version({ status: "ready" }));
    await renderTab(version());

    await userEvent.click(screen.getByRole("button", { name: /approve this version/i }));

    await waitFor(() => expect(mocked.approveVersion).toHaveBeenCalledWith("version-1"));
    // FR-028, and the reason the workflow needs no durable pause and resume.
    expect(mocked.startTailoring).not.toHaveBeenCalled();
  });

  it("leaves an approved version readable and still editable", async () => {
    await renderTab(version({ status: "ready", items: [item({ decision: "accepted" })] }));

    // FR-029. Approved is not frozen in this slice; export is what will lock
    // it, in slice 006.
    expect(screen.getByTestId("tailor-diff")).toHaveAttribute("data-status", "ready");
    expect(screen.getByRole("button", { name: /^edit$/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /approve this version/i })).toBeNull();
  });
});

// -- FR-043 and FR-022: what the numbers mean, and who wrote this -----------

describe("provenance", () => {
  it("labels the confidence score as grounding, never as fit", async () => {
    await renderTab(version({ confidence_score: 82 }));

    // FR-043. Two unlabelled percentages on one record is how a person comes
    // away believing their fit improved because a draft was rewritten.
    const confidence = screen.getByTestId("confidence");
    expect(confidence).toHaveTextContent("82/100");
    expect(confidence).toHaveTextContent(/grounded in your profile/i);
    expect(confidence.textContent).not.toMatch(/match/i);
  });

  it("names the model and the cost", async () => {
    await renderTab(version());

    // FR-022 and Principle III: visibly AI-generated, at the surface a person
    // approves from rather than in a settings panel.
    const line = screen.getByTestId("version-provenance");
    expect(line).toHaveTextContent(/written by ai/i);
    expect(line).toHaveTextContent("claude-sonnet-5");
    expect(line).toHaveTextContent("0.081000");
  });

  it("names every model a run used, not only the one that drafted", async () => {
    // T088 ran Plan and Draft on Sonnet and Review on **Opus**, and the line
    // reported a single Sonnet beside the run's *total* cost — which reads as
    // "this model cost $0.31" when Opus billed part of it at 5x the input
    // price. FR-022 asks the surface to name what produced the draft; on a
    // two-model run naming one of them is not that.
    await renderTabWithRun(version(), {
      tailor_plan: "anthropic/claude-sonnet-5",
      tailor_draft: "anthropic/claude-sonnet-5",
      tailor_review: "anthropic/claude-opus-5",
    });

    // **`waitFor`, because two effects race here.** `getTailoringRun` resolves
    // in its own effect while `setLoading(false)` belongs to the *version*
    // fetch, so "Loading…" disappearing does not mean the run has landed. A
    // bare `getByTestId` therefore samples whichever arrived first and sees
    // the `version.model` fallback — one model, and the assertion fails on the
    // other. Measured at roughly 1 run in 8 before this.
    await waitFor(() => {
      const line = screen.getByTestId("version-provenance");
      expect(line).toHaveTextContent("claude-sonnet-5");
      expect(line).toHaveTextContent("claude-opus-5");
    });
  });

  it("marks fixture output as not real", async () => {
    await renderTab(version({ is_fixture: true }));

    // Canned content mistaken for real output would mean approving invented
    // history, which is the one mistake this project cannot let a person make.
    expect(screen.getByTestId("fixture")).toBeInTheDocument();
  });
});

// -- the two refusals, which need different actions -------------------------

describe("a refusal to start", () => {
  it.each([
    ["no_analysis", /match analysis/i],
    ["stale_analysis", /changed since/i],
  ] as const)("tells the owner what to do about %s", async (reason, expected) => {
    mocked.startTailoring.mockRejectedValue(
      new ApiError(422, "Refused.", { reason, message: "Refused." }),
    );
    await renderTab(null);

    await userEvent.click(screen.getByRole("button", { name: /tailor for this job/i }));

    const refusal = await screen.findByTestId("refusal");
    expect(refusal).toHaveAttribute("data-reason", reason);
    expect(refusal).toHaveTextContent(expected);
  });

  it("reads the reason field rather than the sentence", async () => {
    mocked.startTailoring.mockRejectedValue(
      // A message reworded on the server. The interface must still offer the
      // right next step, which is precisely why the reason travels as a field.
      new ApiError(422, "Something else entirely.", {
        reason: "stale_analysis",
        message: "Something else entirely.",
      }),
    );
    await renderTab(null);

    await userEvent.click(screen.getByRole("button", { name: /tailor for this job/i }));

    expect(await screen.findByTestId("refusal")).toHaveTextContent(/score it again/i);
  });
});

// -- T072: what survives when the motion is taken away ----------------------

describe("the progress state under reduced motion", () => {
  it("carries its meaning in text, never in the animation", async () => {
    await renderTab(version({ status: "reviewing", items: [] }));

    // The global `prefers-reduced-motion` rule collapses every animation to
    // 0.01ms. Whatever the arc is doing then, it stops doing — so nothing about
    // the state may be carried by the movement alone.
    expect(screen.getByTestId("working-step")).toHaveTextContent(/checking its own work/i);
    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-busy", "true");
  });

  it("rests on a partial arc, which is a placeholder rather than a claim", async () => {
    const { container } = { container: document.body };
    await renderTab(version({ status: "tailoring", items: [] }));

    const arc = container.querySelector<SVGCircleElement>(".score-pending");
    expect(arc).not.toBeNull();

    // A **quarter turn**: long enough to read as motion, short enough that a
    // still frame is plainly unfinished. This is the opposite construction to
    // the match ring, and deliberately so — that one animates *to* a real
    // value, so its base style is the finished state and the keyframe supplies
    // only the start. Here there is no value yet, so a full ring resting still
    // would read as a completed run and an empty one as a failed draft.
    const circumference = 2 * Math.PI * 15;
    const [dash] = (arc?.getAttribute("stroke-dasharray") ?? "").split(" ").map(Number);
    expect(dash).toBeCloseTo(circumference / 4, 1);
    expect(dash).toBeLessThan(circumference);
    expect(dash).toBeGreaterThan(0);
  });

  it("keeps the reduced-motion rule that makes all of this true", () => {
    // The assertions above are only meaningful while the global rule exists. If
    // it were deleted, they would keep passing and say nothing — so the rule
    // itself is asserted here rather than assumed.
    const css = readFileSync(
      resolve(__dirname, "../../app/globals.css"),
      "utf8",
    );
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)/);
    expect(css).toMatch(/animation-duration:\s*0\.01ms\s*!important/);
  });
});

// -- User Story 3: the owner's own words ------------------------------------

describe("correcting a proposal by hand", () => {
  it("can be reached after rejecting, which is the case US3 is about", async () => {
    // The spec's scenario: the agent was wrong about *how* to say it, not
    // *whether*, and the owner's original line was not right either. Rejecting
    // restores their wording; editing then replaces it.
    //
    // Edit is a peer of Accept and Reject rather than a field that springs open
    // on rejection (T077, amended). Most rejections mean "my wording was fine",
    // and an editor that opens unprompted every time asks a question nobody
    // asked. It also keeps one render path, which is the thing this project has
    // repeatedly lost affordances to.
    const rejected = item({
      decision: "rejected",
      final_text: "Led the payments platform team for six years.",
    });
    mocked.decideItem.mockResolvedValue(rejected);
    await renderTab(version());

    await userEvent.click(screen.getByRole("button", { name: /^reject$/i }));
    await waitFor(() => expect(screen.getByTestId("decision-label")).toBeInTheDocument());

    // Still there, and it edits the *restored* text rather than the proposal.
    const edit = screen.getByRole("button", { name: /^edit$/i });
    expect(edit).toBeInTheDocument();
    await userEvent.click(edit);
    expect(screen.getByLabelText(/edit experience/i)).toHaveValue(
      "Led the payments platform team for six years.",
    );
  });

  it("stays identifiable as the owner's when the version is reopened", async () => {
    // Scenario 2, rendered from stored data rather than from the state left
    // behind by the interaction that produced it — which is the only version of
    // this claim that means anything. `user_corrected` exists on the profile
    // for the same reason: a correction nobody can identify later is
    // indistinguishable from something the machine wrote.
    await renderTab(
      version({
        status: "ready",
        items: [item({ decision: "edited", final_text: "My own account of the work." })],
      }),
    );

    expect(screen.getByTestId("decision-label")).toHaveTextContent(/your words/i);
    expect(screen.getByTestId("diff-item")).toHaveAttribute("data-decision", "edited");
  });

  it("keeps all three authorships on screen at once", async () => {
    await renderTab(
      version({ items: [item({ decision: "edited", final_text: "My own account of the work." })] }),
    );

    // The master's original and the agent's proposal both survive an edit and
    // both stay visible. Replacing either with the owner's text would destroy
    // the lineage the version exists to record, and the diff would stop being
    // a diff.
    const row = screen.getByTestId("diff-item");
    expect(within(row).getByTestId("original-text")).toHaveTextContent("Led the payments platform");
    expect(within(row).getByTestId("proposed-text")).toHaveTextContent("Owned the payments platform");
    expect(within(row).getByTestId("decision-label")).toHaveTextContent(/your words/i);
  });

  it("offers a plain text field, never an editor", async () => {
    // A WYSIWYG resume editor is an explicit project non-goal (docs/05 §7).
    await renderTab(version());

    await userEvent.click(screen.getByRole("button", { name: /^edit$/i }));
    const field = screen.getByLabelText(/edit experience/i);
    expect(field.tagName).toBe("TEXTAREA");
    expect(field).not.toHaveAttribute("contenteditable");
  });
});

/**
 * T037 — the export affordance.
 *
 * Export and download are separate controls on purpose: downloading again must not
 * export again, because a second export is a second stored copy and a second record,
 * which is not what someone pressing "download" is asking for.
 */
describe("exporting an approved version", () => {
  const exported = (overrides: Partial<ResumeVersion> = {}) =>
    ({
      ...version({ status: "exported", ...overrides }),
      export: {
        checksum_sha256: "a".repeat(64),
        byte_size: 10096,
        exported_at: "2026-08-28T10:00:00+00:00",
      },
    }) as ExportedVersion;

  it("offers no export until the version is approved", async () => {
    await renderTab(version({ status: "awaiting_approval" }));

    expect(screen.queryByTestId("export-controls")).toBeNull();
  });

  it("exports an approved version through the API and shows the download", async () => {
    mocked.exportVersion.mockResolvedValue(exported());
    await renderTab(version({ status: "ready" }));

    // Approved but not yet exported: nothing to download.
    expect(screen.queryByTestId("download-pdf")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Export as PDF" }));

    expect(mocked.exportVersion).toHaveBeenCalledWith("version-1");
    await waitFor(() => expect(screen.getByTestId("download-pdf")).toBeTruthy());
    expect(screen.getByTestId("download-pdf").getAttribute("href")).toBe(
      "/api/versions/version-1/document",
    );
  });

  it("keeps export available for an already-exported version", async () => {
    await renderTab(exported());

    expect(screen.getByRole("button", { name: "Export again" })).toBeTruthy();
    expect(screen.getByTestId("download-pdf")).toBeTruthy();
  });

  it("shows the refusal instead of pretending the export happened", async () => {
    mocked.exportVersion.mockRejectedValue(
      new ApiError(409, "This version was already submitted and cannot be exported again."),
    );
    await renderTab(version({ status: "ready" }));

    await userEvent.click(screen.getByRole("button", { name: "Export as PDF" }));

    await waitFor(() =>
      expect(screen.getByText(/already submitted/)).toBeTruthy(),
    );
    expect(screen.queryByTestId("download-pdf")).toBeNull();
  });
});

/**
 * T043 — the submit affordance.
 *
 * Submission is the one action in this slice that cannot be taken back: it freezes what
 * was sent (FR-021), locks the version (FR-022), and a change of mind afterwards means a
 * **new** version rather than an edit to this one (FR-025). So the two things worth
 * proving here are that it is not offered where it is not possible, and that a refusal is
 * visible — a 409 that leaves the screen looking unchanged reads as success, which on
 * this button means a person believes a résumé is on record when none is.
 */
describe("submitting an exported version", () => {
  const exported = (overrides: Partial<ResumeVersion> = {}) =>
    ({
      ...version({ status: "exported", ...overrides }),
      export: {
        checksum_sha256: "a".repeat(64),
        byte_size: 10096,
        exported_at: "2026-08-28T10:00:00+00:00",
      },
    }) as ExportedVersion;

  const submitted = () =>
    ({
      ...version({ status: "submitted" }),
      submission: {
        resume_version_id: "version-1",
        checksum_sha256: "b".repeat(64),
        byte_size: 10096,
        submitted_at: "2026-08-28T12:00:00+00:00",
      },
    }) as SubmittedVersion;

  it("does not offer submission for a version that has not been exported", async () => {
    await renderTab(version({ status: "ready" }));

    expect(screen.getByTestId("export-controls")).toBeTruthy();
    expect(screen.queryByTestId("submit-version")).toBeNull();
  });

  it("submits an exported version through the API", async () => {
    mocked.submitVersion.mockResolvedValue(submitted());
    await renderTab(exported());

    await userEvent.click(screen.getByTestId("submit-version"));

    expect(mocked.submitVersion).toHaveBeenCalledWith("version-1");
    await waitFor(() => expect(screen.getByTestId("submitted-note")).toBeTruthy());
  });

  it("offers no further submission or export once the version is submitted", async () => {
    await renderTab(submitted());

    expect(screen.queryByTestId("submit-version")).toBeNull();
    expect(screen.queryByRole("button", { name: /Export/ })).toBeNull();
    // The document is still readable — downloading is not exporting, and a person is
    // entitled to a copy of what they sent.
    expect(screen.getByTestId("download-pdf")).toBeTruthy();
  });

  it("shows the refusal instead of pretending the submission happened", async () => {
    mocked.submitVersion.mockRejectedValue(
      new ApiError(409, "This version is ready and has not been exported."),
    );
    await renderTab(exported());

    await userEvent.click(screen.getByTestId("submit-version"));

    await waitFor(() => expect(screen.getByTestId("tailor-error")).toBeTruthy());
    expect(screen.getByText(/has not been exported/)).toBeTruthy();
    expect(screen.queryByTestId("submitted-note")).toBeNull();
  });

  it("does not report success while the request is still in flight", async () => {
    let settle: (value: SubmittedVersion) => void = () => {};
    mocked.submitVersion.mockReturnValue(
      new Promise<SubmittedVersion>((resolve) => {
        settle = resolve;
      }),
    );
    await renderTab(exported());

    await userEvent.click(screen.getByTestId("submit-version"));

    // **The claim being tested.** A button that says "Submitted" the moment it is
    // pressed is indistinguishable from one that worked, and this is the action where
    // that matters most: the person stops thinking about the job.
    expect(screen.queryByTestId("submitted-note")).toBeNull();
    expect(screen.getByTestId("submit-version").textContent).toContain("Marking");

    settle(submitted());
    await waitFor(() => expect(screen.getByTestId("submitted-note")).toBeTruthy());
  });

  it("shows no internal storage address anywhere on the screen", async () => {
    const { container } = await renderTab(submitted());

    expect(container.textContent ?? "").not.toContain("exports/");
  });
});

// -- T054: a locked version must not offer controls that are guaranteed 409s --

describe("a version whose content is locked", () => {
  /**
   * `application/immutability.py` freezes content at `exported` and `submitted`
   * and nowhere else. Every `Accept`, `Reject` and `Edit` on such a version is
   * a guaranteed 409, and a button whose only outcome is a refusal is the
   * import reviewer's old `Keep` button by another name.
   *
   * **`ready` is deliberately not in this set.** FR-029 requires an approved
   * version to stay editable, and gating on `approved` — the flag the export
   * controls use — is the plausible over-fix that would pass a test written
   * only against `submitted`. The third case below is what catches it.
   */
  const controls = () =>
    within(screen.getByTestId("diff-item")).queryAllByRole("button", {
      name: /^(Accept|Accepted|Reject|Rejected|Edit)$/,
    });

  it("offers no decision controls on an exported version", async () => {
    await renderTab(version({ status: "exported" }));

    expect(controls()).toHaveLength(0);
    // The diff itself stays. Hiding what the document says would be a
    // different claim from "this can no longer be changed".
    expect(screen.getByTestId("proposed-text")).toBeTruthy();
  });

  it("offers no decision controls on a submitted version", async () => {
    await renderTab(version({ status: "submitted" }));

    expect(controls()).toHaveLength(0);
    expect(screen.getByTestId("proposed-text")).toBeTruthy();
  });

  it("keeps them on an approved version, which FR-029 requires", async () => {
    await renderTab(version({ status: "ready" }));

    expect(controls()).toHaveLength(3);
  });

  /**
   * The defect T037 fixed for the export path, on the one path that never got
   * it: `decide()` had no `catch`, so a refused decision set no state, rendered
   * nothing, and left the row exactly as it was. Silence after a click reads as
   * success.
   *
   * Rendered against a `ready` version on purpose — after the gating above, a
   * locked version offers no button to click, and the refusal that remains
   * reachable is the one that arrives when the version was locked somewhere
   * else while this screen was open.
   */
  it("shows a refused decision instead of leaving the screen still", async () => {
    mocked.decideItem.mockRejectedValue(
      new ApiError(409, "This version has been submitted and can no longer be changed."),
    );
    await renderTab(version({ status: "ready" }));

    await userEvent.click(screen.getByRole("button", { name: "Reject" }));

    await waitFor(() => expect(screen.getByTestId("tailor-error")).toBeTruthy());
    expect(screen.getByText(/can no longer be changed/)).toBeTruthy();
    expect(screen.queryByTestId("decision-label")).toBeNull();
  });
});

// -- T054.3: FR-025 works and was unreachable through the interface ----------

describe("starting a new version from a locked one", () => {
  /**
   * FR-025 — a revision after submission is a **new** version — is implemented
   * and tested on the backend (`create_pending_version` reuses only a `draft`),
   * and through the UI there was no way to ask for it. The submitted view said
   * *"tailor this job again"* and offered `Download PDF` and three controls
   * that could only 409.
   *
   * Offered on both locked states, because an `exported` version's content is
   * frozen too: its owner has the same dead end, and `immutability.py` answers
   * both with the same sentence.
   *
   * **Not offered on `ready`.** That version is still editable, so the action
   * it wants is Edit, not a second paid run.
   */
  const retailor = () => screen.queryByTestId("retailor");

  it("offers it on a submitted version", async () => {
    await renderTab(version({ status: "submitted" }));
    expect(retailor()).toBeTruthy();
  });

  it("offers it on an exported version", async () => {
    await renderTab(version({ status: "exported" }));
    expect(retailor()).toBeTruthy();
  });

  it("does not offer it while the version is still editable", async () => {
    await renderTab(version({ status: "ready" }));
    expect(retailor()).toBeNull();
  });

  it("starts a run and moves the screen to the new version", async () => {
    mocked.startTailoring.mockResolvedValue({
      version_id: "version-2",
      status: "tailoring",
      run_id: "run-2",
    });
    await renderTab(version({ status: "submitted" }));

    mocked.getVersion.mockResolvedValue(version({ id: "version-2", status: "tailoring" }));
    await userEvent.click(screen.getByTestId("retailor"));

    expect(mocked.startTailoring).toHaveBeenCalledWith("app-1");
    // The new version is a different row; the submitted one was not mutated.
    await waitFor(() => expect(screen.getByTestId("working-step")).toBeTruthy());
  });

  /**
   * The same defect as the silent decision, one action along. `tailor()` sets
   * `refusal` rather than `error`, and until now only the start view rendered
   * it — so a re-tailor refused because the profile moved since the match would
   * have set state nobody displayed and left the screen exactly as it was.
   * A stale analysis is the *likely* case here, not an edge one: this version
   * was written against a match that is by now several actions old.
   */
  it("says why a refused run was refused, rather than nothing", async () => {
    mocked.startTailoring.mockRejectedValue(
      new ApiError(422, "Re-score this job first.", { reason: "stale_analysis" }),
    );
    await renderTab(version({ status: "submitted" }));

    await userEvent.click(screen.getByTestId("retailor"));

    await waitFor(() => expect(screen.getByTestId("refusal")).toBeTruthy());
    expect(screen.getByTestId("refusal").getAttribute("data-reason")).toBe("stale_analysis");
    // Still the sent version. A refused run changes nothing about it.
    expect(screen.getByTestId("tailor-diff").getAttribute("data-status")).toBe("submitted");
  });
});
