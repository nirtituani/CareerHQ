import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MatchTab } from "@/components/applications/match-tab";
import type { MatchAnalysis } from "@/lib/api";

/**
 * An application with no posting content must look incomplete, persistently.
 *
 * The failure it follows from: a job saved after extraction failed could still
 * be scored, spent a completion against an empty posting, and came back
 * `0/100 · low_probability`. Nothing on the screen said the posting was
 * missing — the number looked like a judgement about the person.
 *
 * Two separate claims are tested here, because they fail independently:
 * a job that *cannot* be scored must say so and must not offer to score, and a
 * score computed from nothing must not be rendered as a score.
 */

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, fetchMatch: vi.fn(), runMatch: vi.fn() };
});

function empty(): MatchAnalysis {
  return {
    id: "a1",
    band: "low_probability",
    overall_score: 0,
    credit: {},
    capped_by: null,
    verdict: "No job posting content was provided, so fit cannot be assessed.",
    criteria_version: "v3-earned",
    error: null,
    coverage: {},
    requirements: [],
    model: "claude-sonnet-5",
    input_tokens: 3018,
    output_tokens: 123,
    cost: "0.007266",
    is_fixture: false,
    created_at: "2026-08-26T00:00:00+00:00",
    completed_at: "2026-08-26T00:00:00+00:00",
  };
}

describe("a job with no posting content", () => {
  it("asks for the posting rather than offering to score", () => {
    render(
      <MatchTab
        state="nothing_to_score"
        analysis={null}
        stale={false}
        applicationId="app-1"
        canScore={false}
      />,
    );

    expect(screen.getByTestId("needs-posting")).toHaveTextContent(/add the posting/i);
    // Offering the action would spend a completion on nothing and return the
    // same empty zero that started this.
    expect(screen.queryByRole("button", { name: /score this job/i })).toBeNull();
  });

  it("does not render a zero computed from nothing as a score", () => {
    // The server reports `nothing_to_score` for an analysis with no requirement
    // rows, so the band and the number never reach the screen.
    render(
      <MatchTab
        state="nothing_to_score"
        analysis={empty()}
        stale={false}
        applicationId="app-1"
        canScore={false}
      />,
    );

    expect(screen.queryByText("Low probability")).toBeNull();
    expect(screen.queryByTestId("score")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("still offers to score a job that has content but was never scored", () => {
    render(
      <MatchTab
        state="nothing_to_score"
        analysis={null}
        stale={false}
        applicationId="app-1"
        canScore
      />,
    );

    expect(screen.getByRole("button", { name: /score this job/i })).toBeInTheDocument();
    expect(screen.queryByTestId("needs-posting")).toBeNull();
  });
});
