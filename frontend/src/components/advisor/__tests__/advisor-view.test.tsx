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
    action: "This is a recurring gap. Prioritise closing it.",
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
    expect(card.textContent).toContain("AWS was a gap in 4 of 7 analyzed postings");
    expect(within(card).getByTestId("priority").textContent).toContain(
      "the dominant unmet requirement in your target roles",
    );
    expect(within(card).getByTestId("evidence").textContent).toContain("(4/7)");
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
    expect(chip.textContent).toContain("Gap in 4 of 7 analyzed postings");
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
    expect(within(chip).getByTestId("action").textContent).toContain("Prioritise closing it");
  });

  it("portfolio memories live in a collapsed drawer, opened on demand", async () => {
    const portfolio = memory({
      id: "33333333-3333-4333-8333-333333333333",
      tier: "portfolio",
      section: "portfolio",
      topic: "outcome pattern",
      counts: null,
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
  it("shows the grouping a skill memory's counts ran through, once expanded (T034)", async () => {
    api.getAdvisor.mockResolvedValue(
      state({
        memories: [
          memory({
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
