import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TailorDiffItem } from "@/components/applications/tailor-diff-item";
import { TailorTab } from "@/components/applications/tailor-tab";
import { ApiError } from "@/lib/api";
import type { ResumeVersion, ReviewerFinding, VersionItem } from "@/lib/api";

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

  render(<TailorTab applicationId="app-1" />);
  await waitFor(() => expect(screen.queryByText("Loading…")).toBeNull());
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
