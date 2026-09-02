/**
 * The advisor page's client half (US1/US2/US4 + the topic-first refinement).
 *
 * Detail now lives behind a topic chip: the first view shows compact chips
 * grouped into sections, and clicking a chip expands the full existing detail
 * (claim, evidence, priority reason, lineage, dismiss). Tests that inspect the
 * detail expand the chip first — progressive disclosure, nothing removed.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdvisorView } from "@/components/advisor/advisor-view";
import { SidebarNav } from "@/components/sidebar-nav";
import type { AdvisorRun, AdvisorState, CareerMemory } from "@/lib/api";

vi.mock("next/navigation", () => ({ usePathname: () => "/advisor" }));

const api = vi.hoisted(() => ({
  getAdvisor: vi.fn(),
  startAdvisorRun: vi.fn(),
  getAdvisorRun: vi.fn(),
  dismissMemory: vi.fn(),
  getMemory: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  getAdvisor: api.getAdvisor,
  startAdvisorRun: api.startAdvisorRun,
  getAdvisorRun: api.getAdvisorRun,
  dismissMemory: api.dismissMemory,
  getMemory: api.getMemory,
}));

const MEMORY_ID = "11111111-1111-4111-8111-111111111111";

/** Default: a visible recommendation skill memory (chip renders directly). */
function memory(overrides: Partial<CareerMemory> = {}): CareerMemory {
  return {
    id: MEMORY_ID,
    claim: "AWS was a gap in 4 of 7 analyzed postings",
    kind: "recurring_gap",
    scope: { kind: "skill", value: "AWS" },
    status: "active",
    priority: 70,
    priority_reason: "the dominant unmet requirement in your target roles",
    tier: "recommendation",
    section: "recommended",
    topic: "AWS",
    counts: { occurrences: 5, coverage: 7, gaps: 4 },
    specifics: [
      {
        requirement_id: "req-1",
        text: "Deep understanding of cloud infrastructure (AWS/GCP)",
        verdict: "gap",
        shortfall: "capability",
        importance: 80,
        profile_quote: "Building and deploying cloud-based applications",
        resolved: true,
      },
      {
        requirement_id: "req-2",
        text: "Experience with cloud platforms and products",
        verdict: "confirmed",
        shortfall: null,
        importance: 70,
        profile_quote: "Building and deploying cloud-based applications",
        resolved: true,
      },
    ],
    specific_labels: ["Deep understanding of cloud infrastructur…", "Experience with cloud platforms"],
    profile_quotes: ["Building and deploying cloud-based applications"],
    specifics_unresolved: 0,
    assessment: "You partly meet these asks — the shortfalls are depth of hands-on capability.",
    action: {
      category: "learn_build",
      text: "Build hands-on depth here — this is a capability gap, not a wording one.",
    },
    evidence: {
      as_of: "2026-09-01T10:00:00Z",
      rules_version: "v1-advisor",
      facts: [
        {
          fact_id: "tier2.gap.g1",
          kind: "tier2.gap",
          scope_kind: "skill",
          scope_value: "AWS",
          numerator: 4,
          denominator: 7,
          value: "AWS was a gap in 4 of 7 analyzed postings",
          date_range: null,
          record_ids: [],
          basis: "test",
        },
      ],
      groupings: [],
    },
    created_at: "2026-09-01T10:00:00Z",
    last_confirmed_at: "2026-09-01T10:00:00Z",
    supersedes_id: null,
    recreates_dismissed_id: null,
    retired_reason: null,
    last_disposition: null,
    ...overrides,
  };
}

function sectioned(memories: CareerMemory[]): AdvisorState["sections"] {
  const s: AdvisorState["sections"] = {
    recommended: [],
    emerging: [],
    strengths: [],
    portfolio: [],
    data_notes: [],
  };
  for (const m of memories) s[m.section].push(m);
  return s;
}

function state(overrides: Partial<AdvisorState> = {}): AdvisorState {
  const memories = overrides.memories ?? [];
  return {
    memories,
    sections: overrides.sections ?? sectioned(memories),
    tier_rules_version: "v1-tiers",
    action_rules_version: "v1-actions",
    coverage: {
      applications: 6,
      analysed: 0,
      message: "Skill-level patterns grow as applications get match analyses.",
    },
    latest_run: null,
    history_counts: { superseded: 0, retired: 0 },
    ...overrides,
  };
}

function run(overrides: Partial<AdvisorRun> = {}): AdvisorRun {
  return {
    id: "run-1",
    status: "pending",
    error: null,
    rules_version: "v1-advisor",
    ops: null,
    models: { grouping: null, reason: null },
    cost: null,
    input_tokens: null,
    output_tokens: null,
    is_fixture: false,
    created_at: "2026-09-01T10:00:00Z",
    completed_at: null,
    ...overrides,
  };
}

/** Expand a chip and return its (now-rendered) detail card. */
async function expand(id = MEMORY_ID): Promise<HTMLElement> {
  const chip = await screen.findByTestId(`chip-${id}`);
  await userEvent.click(within(chip).getByRole("button", { expanded: false }));
  return within(chip).getByTestId(`memory-${id}`);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("AdvisorView — honesty & lifecycle", () => {
  it("renders the honest empty state naming what the advisor needs", async () => {
    api.getAdvisor.mockResolvedValue(
      state({ coverage: { applications: 0, analysed: 0, message: "m" } }),
    );
    render(<AdvisorView />);
    const empty = await screen.findByTestId("empty-state");
    expect(empty.textContent).toContain("Nothing to analyse yet");
    expect(empty.textContent).toContain("application history");
  });

  it("renders the coverage line's denominators", async () => {
    api.getAdvisor.mockResolvedValue(state());
    render(<AdvisorView />);
    const coverage = await screen.findByTestId("coverage");
    expect(coverage.textContent).toContain("0 of 6 applications have a match analysis");
  });

  it("expands a chip to the full detail: claim, priority reason, denominators, dismiss", async () => {
    api.getAdvisor.mockResolvedValue(state({ memories: [memory()] }));
    render(<AdvisorView />);
    const card = await expand();
    // V2: the rows the roles actually asked for, the user's own quoted
    // evidence, and the deterministic assessment — not the claim restated.
    expect(within(card).getByTestId("what-roles-ask").textContent).toContain(
      "Deep understanding of cloud infrastructure (AWS/GCP)",
    );
    expect(within(card).getByTestId("your-evidence").textContent).toContain(
      "Building and deploying cloud-based applications",
    );
    expect(within(card).getByTestId("assessment").textContent).toContain(
      "depth of hands-on capability",
    );
    expect(within(card).getByTestId("priority").textContent).toContain(
      "the dominant unmet requirement in your target roles",
    );
    expect(within(card).getByRole("button", { name: "Dismiss" })).toBeTruthy();
  });

  it("marks a tentative memory visibly once expanded", async () => {
    api.getAdvisor.mockResolvedValue(state({ memories: [memory({ status: "tentative" })] }));
    render(<AdvisorView />);
    const card = await expand();
    expect(within(card).getByTestId("tentative-badge")).toBeTruthy();
  });

  it("waits for the run fetch itself before asserting run state", async () => {
    api.getAdvisor.mockResolvedValue(state());
    api.startAdvisorRun.mockResolvedValue({ state: "running", run: run() });
    render(<AdvisorView />);
    await userEvent.click(await screen.findByTestId("analyze"));
    await waitFor(() => {
      expect(screen.getByTestId("analyze").textContent).toContain("Analyzing…");
    });
  });

  it("keeps serving the previous memories (chips) through a failed run", async () => {
    api.getAdvisor.mockResolvedValue(
      state({
        memories: [memory()],
        latest_run: run({ status: "failed", error: "The analysis could not be completed." }),
      }),
    );
    render(<AdvisorView />);
    const alert = await screen.findByTestId("run-failed");
    expect(alert.textContent).toContain("The analysis could not be completed");
    expect(screen.getByTestId(`chip-${MEMORY_ID}`)).toBeTruthy();
  });

  it("distinguishes found-nothing from discarded-everything in the run summary", async () => {
    api.getAdvisor.mockResolvedValue(
      state({
        memories: [memory()],
        latest_run: run({
          status: "ready",
          ops: { proposed: 3, applied: 1, discarded: 2 },
          cost: "0.041000",
        }),
      }),
    );
    render(<AdvisorView />);
    const summary = await screen.findByTestId("run-summary");
    expect(summary.textContent).toContain("1 kept, 2 discarded of 3 proposed");
  });

  it("dismissing (from the expanded card) reloads the state", async () => {
    api.getAdvisor.mockResolvedValueOnce(state({ memories: [memory()] }));
    api.dismissMemory.mockResolvedValue({ memory: memory({ status: "retired" }) });
    api.getAdvisor.mockResolvedValueOnce(state({ memories: [] }));
    render(<AdvisorView />);
    const card = await expand();
    await userEvent.click(within(card).getByRole("button", { name: "Dismiss" }));
    await waitFor(() => {
      expect(api.dismissMemory).toHaveBeenCalledWith(MEMORY_ID);
      expect(api.getAdvisor).toHaveBeenCalledTimes(2);
    });
  });
});

describe("topic-first sections (refinement v1)", () => {
  it("groups a memory under its section with compact evidence on the chip", async () => {
    api.getAdvisor.mockResolvedValue(state({ memories: [memory()] }));
    render(<AdvisorView />);
    const chip = await screen.findByTestId(`chip-${MEMORY_ID}`);
    expect(chip.getAttribute("data-tier")).toBe("recommendation");
    expect(chip.textContent).toContain("AWS");
    expect(chip.textContent).toContain("Required in 5 of 7 · Gap in 4");
    expect(chip.textContent).toContain("High priority");
    expect(chip.textContent).not.toContain("the dominant unmet requirement");
  });

  it("shows the explicit insufficient-evidence empty state when nothing is recommended", async () => {
    const emerging = memory({ tier: "emerging", section: "emerging" });
    api.getAdvisor.mockResolvedValue(state({ memories: [emerging] }));
    render(<AdvisorView />);
    const section = await screen.findByTestId("section-recommended-actions");
    expect(within(section).getByTestId("section-empty").textContent).toContain(
      "insufficient evidence",
    );
  });

  it("a weak (emerging) pattern never appears under Recommended actions", async () => {
    const weak = memory({
      id: "22222222-2222-4222-8222-222222222222",
      tier: "emerging",
      section: "emerging",
      topic: "Database",
      counts: { occurrences: 2, coverage: 5, gaps: 1 },
      specifics: [],
      specific_labels: [],
      profile_quotes: [],
      specifics_unresolved: 0,
      assessment: null,
      action: null,
    });
    api.getAdvisor.mockResolvedValue(state({ memories: [weak] }));
    render(<AdvisorView />);
    const recommended = await screen.findByTestId("section-recommended-actions");
    expect(recommended.textContent).not.toContain("Database");
    const emerging = screen.getByTestId("section-emerging-patterns");
    expect(within(emerging).getByText("Database")).toBeTruthy();
  });

  it("the expanded chip shows the deterministic action for a recommendation", async () => {
    api.getAdvisor.mockResolvedValue(state({ memories: [memory()] }));
    render(<AdvisorView />);
    const chip = await screen.findByTestId(`chip-${MEMORY_ID}`);
    await userEvent.click(within(chip).getByRole("button", { expanded: false }));
    const action = within(chip).getByTestId("action");
    expect(action.getAttribute("data-category")).toBe("learn_build");
    expect(action.textContent).toContain("Build hands-on depth here");
  });

  it("portfolio memories live in a collapsed drawer, opened on demand", async () => {
    const portfolio = memory({
      id: "33333333-3333-4333-8333-333333333333",
      tier: "portfolio",
      section: "portfolio",
      topic: "outcome pattern",
      counts: null,
      specifics: [],
      specific_labels: [],
      profile_quotes: [],
      specifics_unresolved: 0,
      assessment: null,
      action: null,
    });
    api.getAdvisor.mockResolvedValue(state({ memories: [portfolio] }));
    render(<AdvisorView />);
    const drawer = await screen.findByTestId("drawer-portfolio-insights");
    expect(within(drawer).queryByTestId(`chip-${portfolio.id}`)).toBeNull();
    await userEvent.click(within(drawer).getByRole("button", { expanded: false }));
    expect(within(drawer).getByTestId(`chip-${portfolio.id}`)).toBeTruthy();
  });
});

describe("the lifecycle surface (T029)", () => {
  it("badges a memory with what the latest run did to it, once expanded", async () => {
    api.getAdvisor.mockResolvedValue(
      state({
        memories: [
          memory({
            last_disposition: {
              action: "confirmed",
              run_id: "run-9",
              reason: null,
              evidence_delta: { facts: [] },
            },
          }),
        ],
        latest_run: run({ id: "run-9", status: "ready", ops: { proposed: 0, applied: 0, discarded: 0 } }),
      }),
    );
    render(<AdvisorView />);
    const card = await expand();
    expect(within(card).getByTestId("since-last-run").textContent).toBe("Confirmed");
  });

  it("opens a superseded memory's lineage and renders every predecessor", async () => {
    const head = memory({ supersedes_id: "22222222-2222-4222-8222-222222222222" });
    api.getAdvisor.mockResolvedValue(state({ memories: [head] }));
    api.getMemory.mockResolvedValue({
      memory: head,
      lineage: [
        memory({
          id: "22222222-2222-4222-8222-222222222222",
          claim: "AWS was a gap in 2 of 4 analyzed postings",
          status: "superseded",
        }),
      ],
      dispositions: [],
    });
    render(<AdvisorView />);
    const card = await expand();
    await userEvent.click(within(card).getByRole("button", { name: "How this evolved" }));
    const lineage = await within(card).findByTestId("lineage");
    expect(lineage.textContent).toContain("AWS was a gap in 2 of 4 analyzed postings");
    expect(api.getMemory).toHaveBeenCalledWith(head.id);
  });
});

describe("Tier 2 & dismissal surfaces", () => {
  it("falls back to the grouping only when the rows themselves cannot be read (T034)", async () => {
    api.getAdvisor.mockResolvedValue(
      state({
        memories: [
          memory({
            specifics: [],
            specific_labels: [],
            profile_quotes: [],
            specifics_unresolved: 4,
            evidence: {
              ...memory().evidence,
              groupings: [
                { group_id: "g_aws", label: "AWS", group_kind: "skill", member_ids: ["a", "b", "c", "d"] },
              ],
            },
          }),
        ],
      }),
    );
    render(<AdvisorView />);
    const card = await expand();
    expect(within(card).getByTestId("groupings").textContent).toContain("read as AWS: 4 requirements");
    expect(within(card).getByTestId("unresolved").textContent).toContain(
      "no longer available to read",
    );
  });

  it("shows the dismissal history on a legitimately recreated memory (T038)", async () => {
    api.getAdvisor.mockResolvedValue(
      state({ memories: [memory({ recreates_dismissed_id: "33333333-3333-4333-8333-333333333333" })] }),
    );
    render(<AdvisorView />);
    const card = await expand();
    expect(within(card).getByTestId("recreated-note").textContent).toContain(
      "You dismissed an earlier version",
    );
  });
});

describe("SidebarNav", () => {
  it("renders Career Advisor as a real link, not the Soon marker", () => {
    const { container } = render(<SidebarNav />);
    const nav = within(container).getByRole("navigation");
    const link = within(nav).getByRole("link", { name: /Career Advisor/ });
    expect(link.getAttribute("href")).toBe("/advisor");
    expect(link.textContent).not.toContain("Soon");
  });
});

describe("V2 — specifics, action and single-statement statistics", () => {
  it("shows only topic, prevalence and tier — never requirement snippets", async () => {
    api.getAdvisor.mockResolvedValue(state({ memories: [memory()] }));
    render(<AdvisorView />);
    const chip = await screen.findByTestId(`chip-${MEMORY_ID}`);
    expect(within(chip).queryByTestId("specific-labels")).toBeNull();
    // The requirement prose belongs to the expanded view alone.
    expect(chip.textContent).not.toContain("Deep understanding of cloud infrastructure");
    expect(chip.textContent).not.toContain("Experience with cloud platforms and products");
    // ...while the three permitted signals are all present.
    expect(chip.textContent).toContain("AWS");
    expect(chip.textContent).toContain("Required in 5 of 7 · Gap in 4");
    expect(chip.textContent).toContain("High priority"); // uppercased by CSS, not in the DOM
  });

  it("shows grounded technology tags on the compact card", async () => {
    api.getAdvisor.mockResolvedValue(state({ memories: [memory()] }));
    render(<AdvisorView />);
    const chip = await screen.findByTestId(`chip-${MEMORY_ID}`);
    expect(within(chip).getByTestId("tech-tags").textContent).toBe("AWS · GCP");
  });

  it("never shows a technology the evidence does not contain", async () => {
    api.getAdvisor.mockResolvedValue(state({ memories: [memory()] }));
    render(<AdvisorView />);
    const chip = await screen.findByTestId(`chip-${MEMORY_ID}`);
    // These fixture rows name AWS and GCP only — Azure must not appear.
    expect(chip.textContent).not.toContain("Azure");
  });

  it("omits the tag line entirely when the asks name no technology", async () => {
    const capability = memory({
      topic: "AI & LLM Experience",
      specifics: [
        {
          requirement_id: "r1",
          text: "Hands-on production experience with AI agent systems",
          verdict: "gap",
          shortfall: "capability",
          importance: 80,
          profile_quote: null,
          resolved: true,
        },
      ],
    });
    api.getAdvisor.mockResolvedValue(state({ memories: [capability] }));
    render(<AdvisorView />);
    const chip = await screen.findByTestId(`chip-${MEMORY_ID}`);
    expect(within(chip).queryByTestId("tech-tags")).toBeNull();
  });

  it("states each statistic exactly once across the whole expanded card", async () => {
    api.getAdvisor.mockResolvedValue(state({ memories: [memory()] }));
    render(<AdvisorView />);
    const chip = await screen.findByTestId(`chip-${MEMORY_ID}`);
    await userEvent.click(within(chip).getByRole("button", { expanded: false }));
    const text = chip.textContent ?? "";
    for (const statistic of ["5 of 7", "Gap in 4", "Required in"]) {
      const occurrences = text.split(statistic).length - 1;
      expect(occurrences, `"${statistic}" rendered ${occurrences} times`).toBeLessThanOrEqual(1);
    }
    // ...and the LLM claim prose is no longer part of the default expansion.
    expect(text).not.toContain("AWS was a gap in 4 of 7 analyzed postings");
  });

  it("keeps every requirement row in the expanded view", async () => {
    api.getAdvisor.mockResolvedValue(state({ memories: [memory()] }));
    render(<AdvisorView />);
    const card = await expand();
    const asks = within(card).getByTestId("what-roles-ask").textContent ?? "";
    expect(asks).toContain("Deep understanding of cloud infrastructure (AWS/GCP)");
    expect(asks).toContain("Experience with cloud platforms and products");
  });

  it("renders the four V2 sections in the expansion", async () => {
    api.getAdvisor.mockResolvedValue(state({ memories: [memory()] }));
    render(<AdvisorView />);
    const chip = await screen.findByTestId(`chip-${MEMORY_ID}`);
    await userEvent.click(within(chip).getByRole("button", { expanded: false }));
    expect(within(chip).getByTestId("action")).toBeTruthy();
    expect(within(chip).getByTestId("what-roles-ask")).toBeTruthy();
    expect(within(chip).getByTestId("your-evidence")).toBeTruthy();
    expect(within(chip).getByTestId("assessment")).toBeTruthy();
  });

  it("marks each ask as met or unmet with its cause", async () => {
    api.getAdvisor.mockResolvedValue(state({ memories: [memory()] }));
    render(<AdvisorView />);
    const card = await expand();
    const asks = within(card).getByTestId("what-roles-ask").textContent ?? "";
    expect(asks).toContain("(gap · capability)");
    expect(asks).toContain("(met)");
  });

  it("says nothing actionable when the evidence does not support it", async () => {
    const weak = memory({
      tier: "emerging",
      section: "emerging",
      action: { category: "no_action_yet", text: "Not enough to point at one next step yet — tracking it." },
      assessment: "The shortfalls are mixed — no single cause dominates.",
    });
    api.getAdvisor.mockResolvedValue(state({ memories: [weak] }));
    render(<AdvisorView />);
    const chip = await screen.findByTestId(`chip-${MEMORY_ID}`);
    await userEvent.click(within(chip).getByRole("button", { expanded: false }));
    const action = within(chip).getByTestId("action");
    expect(action.getAttribute("data-category")).toBe("no_action_yet");
    expect(action.textContent).toContain("Not enough to point at one next step yet");
  });

  it("a portfolio memory carries no action or assessment sections", async () => {
    const portfolio = memory({
      id: "44444444-4444-4444-8444-444444444444",
      tier: "portfolio",
      section: "portfolio",
      topic: "outcome pattern",
      counts: null,
      specifics: [],
      specific_labels: [],
      profile_quotes: [],
      specifics_unresolved: 0,
      assessment: null,
      action: null,
    });
    api.getAdvisor.mockResolvedValue(state({ memories: [portfolio] }));
    render(<AdvisorView />);
    const drawer = await screen.findByTestId("drawer-portfolio-insights");
    await userEvent.click(within(drawer).getByRole("button", { expanded: false }));
    const chip = within(drawer).getByTestId(`chip-${portfolio.id}`);
    await userEvent.click(within(chip).getByRole("button", { expanded: false }));
    expect(within(chip).queryByTestId("action")).toBeNull();
    expect(within(chip).queryByTestId("assessment")).toBeNull();
    expect(within(chip).queryByTestId("what-roles-ask")).toBeNull();
  });
});

describe("the compact evidence line (prevalence · gap)", () => {
  it("states prevalence first, then the gap, each figure once", async () => {
    api.getAdvisor.mockResolvedValue(state({ memories: [memory()] }));
    render(<AdvisorView />);
    const chip = await screen.findByTestId(`chip-${MEMORY_ID}`);
    expect(chip.textContent).toContain("Required in 5 of 7 · Gap in 4");
  });

  it("omits the gap half when there is no gap", async () => {
    const strength = memory({
      tier: "strength",
      section: "strengths",
      topic: "Backend Engineering",
      counts: { occurrences: 7, coverage: 7, gaps: 0 },
    });
    api.getAdvisor.mockResolvedValue(state({ memories: [strength] }));
    render(<AdvisorView />);
    const chip = await screen.findByTestId(`chip-${MEMORY_ID}`);
    expect(chip.textContent).toContain("Required in 7 of 7");
    expect(chip.textContent).not.toContain("Gap in");
  });

  it("falls back to the claim when a memory carries no counts", async () => {
    const portfolio = memory({
      tier: "portfolio",
      section: "portfolio",
      topic: "outcome pattern",
      counts: null,
      claim: "4 of 7 applications ended rejected",
    });
    api.getAdvisor.mockResolvedValue(state({ memories: [portfolio] }));
    render(<AdvisorView />);
    const drawer = await screen.findByTestId("drawer-portfolio-insights");
    await userEvent.click(within(drawer).getByRole("button", { expanded: false }));
    expect(within(drawer).getByTestId(`chip-${MEMORY_ID}`).textContent).toContain(
      "4 of 7 applications ended rejected",
    );
  });
});

describe("action contract compatibility (B1)", () => {
  // The two services deploy independently. A bundle must render whichever shape
  // the backend it happens to be talking to sends — the object it was built for,
  // or the plain string an older backend still returns.
  it("renders the typed action when the backend sends recommended_action", async () => {
    api.getAdvisor.mockResolvedValue(
      state({
        memories: [
          memory({
            action: "Build hands-on depth here — this is a capability gap, not a wording one.",
            recommended_action: {
              category: "learn_build",
              text: "Build hands-on depth here — this is a capability gap, not a wording one.",
            },
          }),
        ],
      }),
    );
    render(<AdvisorView />);
    await expand();
    const action = screen.getByTestId("action");
    expect(action.getAttribute("data-category")).toBe("learn_build");
    expect(action.textContent).toContain("Build hands-on depth here");
  });

  it("renders a plain-string action from a backend that predates the typed form", async () => {
    api.getAdvisor.mockResolvedValue(
      state({
        memories: [
          memory({
            action: "Build hands-on depth here — this is a capability gap, not a wording one.",
            recommended_action: undefined,
          }),
        ],
      }),
    );
    render(<AdvisorView />);
    await expand();
    expect(screen.getByTestId("action").textContent).toContain("Build hands-on depth here");
  });

  it("renders nothing rather than throwing when there is no action at all", async () => {
    api.getAdvisor.mockResolvedValue(
      state({ memories: [memory({ action: null, recommended_action: null })] }),
    );
    render(<AdvisorView />);
    await expand();
    expect(screen.queryByTestId("action")).toBeNull();
  });
});

describe("the advisor's reasoning is shown for every memory (H3, FR-022)", () => {
  // `assess()` returns null for portfolio and data-note memories, always. While
  // `priority_reason` was nested inside the assessment block, the reasoning
  // disappeared entirely for that whole class — an expanded portfolio card
  // showed a kind/scope line and a Dismiss button and nothing else.
  it.each([
    ["portfolio", "portfolio", "4 of 10 applications ended in rejection"],
    ["data_note", "data_notes", "some applications have inconsistent dates"],
  ])("shows priority_reason on a %s memory that has no assessment", async (tier, section, claim) => {
    api.getAdvisor.mockResolvedValue(
      state({
        memories: [
          memory({
            claim,
            tier: tier as CareerMemory["tier"],
            section: section as CareerMemory["section"],
            counts: null,
            specifics: [],
            specific_labels: [],
            profile_quotes: [],
            assessment: null,
            action: null,
            recommended_action: null,
            priority_reason: "it is the clearest signal in your recent history",
          }),
        ],
      }),
    );
    render(<AdvisorView />);
    // Portfolio and data-note memories live in a collapsed drawer; open it first.
    const drawer = await screen.findByTestId(
      section === "portfolio" ? "drawer-portfolio-insights" : "drawer-data-notes",
    );
    await userEvent.click(within(drawer).getByRole("button", { expanded: false }));
    const card = await expand();

    expect(within(card).queryByTestId("assessment")).toBeNull();
    expect(within(card).getByTestId("priority").textContent).toContain(
      "it is the clearest signal in your recent history",
    );
  });

  it("still shows the reasoning beside an assessment when there is one", async () => {
    api.getAdvisor.mockResolvedValue(state({ memories: [memory()] }));
    render(<AdvisorView />);
    const card = await expand();
    expect(within(card).getByTestId("assessment")).toBeTruthy();
    expect(within(card).getByTestId("priority").textContent).toContain(
      "the dominant unmet requirement in your target roles",
    );
  });
});
