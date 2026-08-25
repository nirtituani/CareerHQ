import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MatchTab } from "@/components/applications/match-tab";
import type { MatchAnalysis, MatchResult, MatchState } from "@/lib/api";

/**
 * The Match tab must notice when scoring finishes.
 *
 * It did not, and a real run sat reading "Scoring" for over twenty minutes
 * while the analysis had been `ready` for nineteen of them. The backend was
 * never at fault: it started the completion at 13:01:23 and logged
 * `match analysis ready` at 13:01:50, twenty-seven seconds later. The page had
 * fetched `/match` **once**, in the same second scoring began, and nothing ever
 * fetched it again.
 *
 * The tab's own comment was the assumption that failed: *"Fetched by the page
 * alongside the record, so the tab has no loading state of its own — the four
 * states already say everything about readiness."* They say everything about
 * readiness **at render time**. Scoring outlives the request that starts it, so
 * render time is precisely when the answer is not yet known.
 *
 * These tests drive the clock rather than the component: they change what the
 * backend would answer and then let the interval fire, which is the only way to
 * prove the screen follows the database rather than its first impression.
 */

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, fetchMatch: vi.fn(), runMatch: vi.fn() };
});

const api = await import("@/lib/api");
const mocked = vi.mocked(api);

function analysis(overrides: Partial<MatchAnalysis> = {}): MatchAnalysis {
  return {
    id: "analysis-1",
    band: "moderate",
    overall_score: 71,
    credit: {},
    capped_by: null,
    verdict: "A moderate fit.",
    criteria_version: "v3-earned",
    error: null,
    coverage: {},
    requirements: [],
    model: "claude-sonnet-5",
    input_tokens: 4339,
    output_tokens: 3291,
    cost: "0.041588",
    is_fixture: false,
    created_at: "2026-08-25T13:01:22+00:00",
    completed_at: "2026-08-25T13:01:50+00:00",
    ...overrides,
  };
}

function result(state: MatchState, over: Partial<MatchResult> = {}): MatchResult {
  return { state, analysis: state === "ready" ? analysis() : null, stale: false, ...over };
}

/**
 * Advance the clock and let React flush what the poll produced.
 *
 * `act` is required because the update originates from an interval rather than
 * from anything the test did — which is exactly the situation this component
 * exists to handle, and exactly what the old one could not.
 */
async function tick(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

/** The tab as the page renders it while the backend is still working. */
function renderScoring(canScore = false) {
  return render(
    <MatchTab
      state="running"
      analysis={null}
      stale={false}
      applicationId="app-1"
      canScore={canScore}
    />,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("while an analysis is running", () => {
  it("follows the backend to ready without a reload", async () => {
    mocked.fetchMatch.mockResolvedValue(result("ready"));
    renderScoring();

    expect(screen.getByText("Scoring")).toBeInTheDocument();

    await tick(2_000);

    expect(mocked.fetchMatch).toHaveBeenCalledWith("app-1");
    expect(screen.queryByText("Scoring")).toBeNull();
    expect(screen.getByText("Moderate")).toBeInTheDocument();
    expect(screen.getByTestId("score")).toHaveTextContent("71/100");
  });

  it("follows the backend to failed just as readily", async () => {
    // A run that dies leaves the row `pending` until the reaper flips it. The
    // server already reports that correctly; nobody could see it.
    mocked.fetchMatch.mockResolvedValue({
      state: "failed",
      analysis: analysis({ error: "The analysis stopped before it finished." }),
      stale: false,
    });
    renderScoring();

    await tick(2_000);

    expect(screen.getByRole("alert")).toHaveTextContent("stopped before it finished");
  });

  it("keeps polling until something changes", async () => {
    mocked.fetchMatch.mockResolvedValue(result("running"));
    renderScoring();

    await tick(6_000);

    // Still working, so still asking. Three ticks, not one.
    expect(mocked.fetchMatch.mock.calls.length).toBe(3);
    expect(screen.getByText("Scoring")).toBeInTheDocument();
  });

  it("survives a poll that fails without giving up or crashing", async () => {
    // A dropped request mid-scoring must not strand the screen. The next tick
    // simply asks again.
    mocked.fetchMatch
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValue(result("ready"));
    renderScoring();

    await tick(4_000);

    expect(screen.getByText("Moderate")).toBeInTheDocument();
  });
});

describe("once the analysis is terminal", () => {
  it("stops polling", async () => {
    mocked.fetchMatch.mockResolvedValue(result("ready"));
    renderScoring();

    await tick(2_000);
    const afterArrival = mocked.fetchMatch.mock.calls.length;

    await tick(30_000);

    // An interval nobody stops is a request every two seconds for as long as
    // the tab is open — and it would keep asking a question already answered.
    expect(mocked.fetchMatch.mock.calls.length).toBe(afterArrival);
  });

  it.each(["ready", "failed", "nothing_to_score"] as const)(
    "never starts polling when the page already rendered %s",
    async (state) => {
      render(
        <MatchTab
          state={state}
          analysis={state === "nothing_to_score" ? null : analysis()}
          stale={false}
          applicationId="app-1"
        />,
      );

      await tick(10_000);

      expect(mocked.fetchMatch).not.toHaveBeenCalled();
    },
  );
});

describe("the manual Score this job action", () => {
  it("shows the run and then its result, without a reload", async () => {
    mocked.runMatch.mockResolvedValue(result("running"));
    mocked.fetchMatch.mockResolvedValue(result("ready"));

    render(
      <MatchTab
        state="nothing_to_score"
        analysis={null}
        stale={false}
        applicationId="app-1"
        canScore
      />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /score this job/i }));
    });

    // The same gap as the automatic flow: this fired the POST and then never
    // re-read, so the button was as stuck as the initial render.
    expect(screen.getByText("Scoring")).toBeInTheDocument();

    await tick(2_000);

    expect(screen.getByText("Moderate")).toBeInTheDocument();
  });

  it("does not leave the screen scoring when the request is refused", async () => {
    // 409: a run is already in flight. The poll below finds it and reports it.
    mocked.runMatch.mockRejectedValue(new Error("An analysis is already running."));
    mocked.fetchMatch.mockResolvedValue(result("ready"));

    render(
      <MatchTab
        state="nothing_to_score"
        analysis={null}
        stale={false}
        applicationId="app-1"
        canScore
      />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /score this job/i }));
    });
    await tick(2_000);

    expect(screen.getByText("Moderate")).toBeInTheDocument();
  });
});

describe("moving between jobs", () => {
  it("shows the new job's state, not the previous job's", async () => {
    // Real timers: this exercises a navigation, not the clock, and Radix's tab
    // trigger schedules its own work that deadlocks against a faked one.
    vi.useRealTimers();
    // Introduced by this change and closed with it. Giving the tab local state
    // means React keeps it across a navigation: same component, same position,
    // different job. Before, the props always won because there was no state to
    // win against — so a fix for staleness in time would have created staleness
    // across records, which is the worse of the two.
    const { DetailTabs } = await import("@/components/applications/detail-tabs");
    const application = (id: string) =>
      ({
        id,
        company: { id: "c", name: "Acme", domain: null },
        job_title: "Engineer",
        location: null,
        job_description: null,
        requirements: [],
        job_url: null,
        job_description_url: null,
        status: "Applied",
        normalized_status: "applied" as const,
        date_added: "2026-08-25T00:00:00+00:00",
        date_applied: null,
        source: null,
        salary_text: null,
        imported_match_rating: 0,
        contact_name: null,
        contact_email: null,
        notes: null,
        import_source: null,
        archived_at: null,
        status_history: [],
      }) as never;

    const { rerender } = render(
      <DetailTabs application={application("app-a")} match={result("ready")} />,
    );
    await userEvent.click(screen.getByRole("tab", { name: /Match/ }));
    expect(screen.getByText("Moderate")).toBeInTheDocument();

    rerender(<DetailTabs application={application("app-b")} match={result("running")} />);

    expect(screen.getByText("Scoring")).toBeInTheDocument();
    expect(screen.queryByText("Moderate")).toBeNull();
  });
});
