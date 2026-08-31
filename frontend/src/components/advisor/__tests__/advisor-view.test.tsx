/**
 * The advisor page's client half (T020/T021, extended by T029/T034/T038).
 *
 * The run-status assertions wait for the *run* state, never for the page
 * load — the tailor flake's lesson: two effects resolve independently, and
 * waiting for "Loading…" to disappear says nothing about the run fetch.
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

function memory(overrides: Partial<CareerMemory> = {}): CareerMemory {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    claim: "3 of 6 of your applications ended rejected",
    kind: "outcome_pattern",
    scope: { kind: "global", value: null },
    status: "active",
    priority: 70,
    priority_reason: "the dominant outcome in your history",
    evidence: {
      as_of: "2026-09-01T10:00:00Z",
      rules_version: "v1-advisor",
      facts: [
        {
          fact_id: "outcome.rejection_rate.global",
          kind: "outcome",
          scope_kind: "global",
          scope_value: null,
          numerator: 3,
          denominator: 6,
          value: "3 of 6 applications (50%) ended rejected",
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

function state(overrides: Partial<AdvisorState> = {}): AdvisorState {
  return {
    memories: [],
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
    is_fixture: false,
    created_at: "2026-09-01T10:00:00Z",
    completed_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("AdvisorView", () => {
  it("renders the honest empty state naming what the advisor needs", async () => {
    api.getAdvisor.mockResolvedValue(
      state({ coverage: { applications: 0, analysed: 0, message: "m" } }),
    );
    render(<AdvisorView />);
    const empty = await screen.findByTestId("empty-state");
    expect(empty.textContent).toContain("Nothing to analyse yet");
    expect(empty.textContent).toContain("application history");
  });

  it("renders the coverage line's denominators — the insufficient-data answer", async () => {
    api.getAdvisor.mockResolvedValue(state());
    render(<AdvisorView />);
    const coverage = await screen.findByTestId("coverage");
    expect(coverage.textContent).toContain("0 of 6 applications have a match analysis");
  });

  it("shows a memory with claim, priority reason, denominators and dismiss", async () => {
    api.getAdvisor.mockResolvedValue(state({ memories: [memory()] }));
    render(<AdvisorView />);
    const card = await screen.findByTestId(`memory-${memory().id}`);
    expect(card.textContent).toContain("3 of 6 of your applications ended rejected");
    expect(within(card).getByTestId("priority").textContent).toContain(
      "the dominant outcome in your history",
    );
    expect(within(card).getByTestId("evidence").textContent).toContain("(3/6)");
    expect(within(card).getByRole("button", { name: "Dismiss" })).toBeTruthy();
  });

  it("marks a tentative memory visibly, with its small denominator intact", async () => {
    api.getAdvisor.mockResolvedValue(
      state({ memories: [memory({ status: "tentative" })] }),
    );
    render(<AdvisorView />);
    const card = await screen.findByTestId(`memory-${memory().id}`);
    expect(within(card).getByTestId("tentative-badge")).toBeTruthy();
  });

  it("waits for the run fetch itself before asserting run state", async () => {
    api.getAdvisor.mockResolvedValue(state());
    api.startAdvisorRun.mockResolvedValue({ state: "running", run: run() });
    render(<AdvisorView />);
    const button = await screen.findByTestId("analyze");
    await userEvent.click(button);
    // The assertion waits for the run state, not for the page load.
    await waitFor(() => {
      expect(screen.getByTestId("analyze").textContent).toContain("Analyzing…");
    });
  });

  it("keeps serving the previous memories through a failed run", async () => {
    api.getAdvisor.mockResolvedValue(
      state({
        memories: [memory()],
        latest_run: run({ status: "failed", error: "The analysis could not be completed." }),
      }),
    );
    render(<AdvisorView />);
    const alert = await screen.findByTestId("run-failed");
    expect(alert.textContent).toContain("The analysis could not be completed");
    expect(screen.getByTestId(`memory-${memory().id}`)).toBeTruthy();
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

  it("dismissing reloads the state", async () => {
    api.getAdvisor.mockResolvedValueOnce(state({ memories: [memory()] }));
    api.dismissMemory.mockResolvedValue({ memory: memory({ status: "retired" }) });
    api.getAdvisor.mockResolvedValueOnce(state({ memories: [] }));
    render(<AdvisorView />);
    const card = await screen.findByTestId(`memory-${memory().id}`);
    await userEvent.click(within(card).getByRole("button", { name: "Dismiss" }));
    await waitFor(() => {
      expect(api.dismissMemory).toHaveBeenCalledWith(memory().id);
      expect(api.getAdvisor).toHaveBeenCalledTimes(2);
    });
  });
});

describe("SidebarNav", () => {
  it("renders Career Advisor as a real link, not the Soon marker", () => {
    const { container } = render(<SidebarNav />);
    // Query inside the nav container — portals lie (testing rule 3).
    const nav = within(container).getByRole("navigation");
    const link = within(nav).getByRole("link", { name: /Career Advisor/ });
    expect(link.getAttribute("href")).toBe("/advisor");
    expect(link.textContent).not.toContain("Soon");
  });
});
