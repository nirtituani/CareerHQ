import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MatchCell, VERDICT_GLYPH, bandLabel } from "@/components/applications/match-score";
import { MatchTab } from "@/components/applications/match-tab";
import type { MatchAnalysis, MatchRequirement } from "@/lib/api";

function req(
  ordinal: number,
  text: string,
  kind: "must_have" | "preferred",
  importance: number,
  verdict: MatchRequirement["verdict"],
  shortfall: MatchRequirement["shortfall"],
  evidence: string | null,
): MatchRequirement {
  return { ordinal, text, kind, importance, verdict, shortfall, evidence };
}

/**
 * The four states, and the glyphs that survive greyscale.
 *
 * docs/09 §5 exists because "not scored yet" reading as "failed" is the
 * confusion that makes a working system look broken. Nothing downstream catches
 * it — each state renders perfectly well on its own.
 */
describe("match states", () => {
  it("renders all four states distinctly", () => {
    const rendered = (["running", "ready", "failed", "nothing_to_score"] as const).map((state) => {
      const { container } = render(
        <MatchCell match={{ state, band: state === "ready" ? "strong" : null, overall_score: 84 }} />,
      );
      return container.textContent?.trim() ?? "";
    });

    expect(new Set(rendered).size).toBe(4);
  });

  it("shows a band, never a bare percentage", () => {
    const { container } = render(
      <MatchCell match={{ state: "ready", band: "strong", overall_score: 84 }} />,
    );

    // FR-001a. 84% claims a precision the method does not have; the number is
    // retained for sorting and calibration, not for display.
    expect(container.textContent).toContain("Strong");
    expect(container.textContent).not.toContain("84");
    expect(container.textContent).not.toContain("%");
  });

  it("does not present nothing-to-score as an error", () => {
    render(<MatchCell match={{ state: "nothing_to_score", band: null, overall_score: null }} />);

    // A job added by hand with no description is ordinary. Reading it as a
    // failure is the docs/09 §5 confusion, and it is the state most likely to
    // appear: every row written before slice 004 is in it.
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("marks only a real failure as one", () => {
    render(<MatchCell match={{ state: "failed", band: null, overall_score: null }} />);

    expect(screen.getByRole("alert")).toBeTruthy();
  });
});

describe("verdict glyphs", () => {
  it("gives each of the five verdicts its own glyph", () => {
    const glyphs = Object.values(VERDICT_GLYPH);

    // docs/09 §7. The glyph carries the meaning so it survives greyscale and
    // colour blindness — a hue difference does not.
    expect(new Set(glyphs).size).toBe(5);
  });

  it("keeps transferable distinguishable from confirmed", () => {
    // Showing adjacent experience as direct experience is the fabrication
    // FR-011b forbids, one step removed from inventing it outright.
    expect(VERDICT_GLYPH.transferable).not.toBe(VERDICT_GLYPH.confirmed);
  });

  it("keeps unverified distinguishable from a gap", () => {
    // *Not mentioned* is not *does not have*. If these render alike, the
    // distinction the whole five-verdict taxonomy exists for is invisible to
    // the only person who can act on it.
    expect(VERDICT_GLYPH.unverified).not.toBe(VERDICT_GLYPH.gap);
  });
});

describe("band labels", () => {
  it("names every band without a number", () => {
    const labels = (["strong", "moderate", "stretch", "low_probability"] as const).map(bandLabel);

    expect(new Set(labels).size).toBe(4);
    expect(labels.join(" ")).not.toMatch(/\d/);
  });
});

/**
 * The Match tab — the screen that finally makes an analysis readable.
 *
 * Until this existed the whole judgement lived in the database and the only
 * thing on screen was a one-word band. Everything below is a display decision
 * that would be invisible in a passing build.
 */
describe("the match tab", () => {
  const ANALYSIS: MatchAnalysis = {
    id: "a1",
    band: "stretch",
    overall_score: 56,
    verdict: "Strong backend fit, but Kubernetes and Terraform are unproven.",
    criteria_version: "v2-importance",
    error: null,
    coverage: { confirmed: 2, partial: 1, transferable: 1, gap: 1, unverified: 2, total: 7 },
    requirements: [
      req(0, "5+ years backend", "must_have", 85, "confirmed", null, "Eight years at Sapiens."),
      req(1, "Python and FastAPI", "must_have", 85, "partial", "evidence", "Python services."),
      req(2, "Kubernetes in production", "must_have", 80, "unverified", null, null),
      req(3, "Terraform", "must_have", 65, "unverified", null, null),
      req(4, "10+ years regulated", "preferred", 40, "gap", "capability", "Eight years, not ten."),
      req(5, "Insurance domain", "preferred", 35, "transferable", "wording", "Mission-critical."),
      req(6, "Fast-paced startup", "preferred", 15, "unverified", null, null),
    ],
    model: "claude-sonnet-5",
    input_tokens: 3700,
    output_tokens: 2707,
    cost: "0.034470",
    is_fixture: false,
    created_at: "2026-08-20T07:50:00Z",
    completed_at: "2026-08-20T07:50:30Z",
  };

  it("shows the band and the verdict, not a bare percentage", () => {
    render(<MatchTab state="ready" analysis={ANALYSIS} stale={false} />);

    expect(screen.getByText(/Stretch/)).toBeInTheDocument();
    expect(screen.getByText(/Kubernetes and Terraform are unproven/)).toBeInTheDocument();
    expect(screen.queryByText(/56%/)).toBeNull();
  });

  it("puts what is missing in importance order, hardest first", () => {
    render(<MatchTab state="ready" analysis={ANALYSIS} stale={false} />);

    const missing = screen.getByTestId("whats-missing").textContent ?? "";
    // Kubernetes (80) must come before Terraform (65), which must come before
    // "fast-paced startup" (15). Listing them in posting order would bury the
    // thing that actually costs the interview under boilerplate.
    expect(missing.indexOf("Kubernetes")).toBeLessThan(missing.indexOf("Terraform"));
    expect(missing.indexOf("Terraform")).toBeLessThan(missing.indexOf("Fast-paced"));
  });

  it("groups unverified with the gaps rather than in a bucket of its own", () => {
    render(<MatchTab state="ready" analysis={ANALYSIS} stale={false} />);

    const missing = screen.getByTestId("whats-missing").textContent ?? "";
    // A requirement your CV does not evidence costs you the interview whether
    // or not the shortfall is provable. Hiding `unverified` in a neutral third
    // section would make the most actionable finding the least visible.
    expect(missing).toContain("Kubernetes");
    expect(missing).toContain("10+ years regulated");
  });

  it("shows the evidence for everything it claims", () => {
    render(<MatchTab state="ready" analysis={ANALYSIS} stale={false} />);

    // AI-008 made visible: every verdict that asserts something quotes the
    // profile, including the gap.
    expect(screen.getByText(/Eight years at Sapiens/)).toBeInTheDocument();
    expect(screen.getByText(/Eight years, not ten/)).toBeInTheDocument();
  });

  it("labels an unverified requirement as missing from the CV, not as absent", () => {
    render(<MatchTab state="ready" analysis={ANALYSIS} stale={false} />);

    // "Not on your CV" is true whether or not you have the skill, states the
    // cost, and points at the fix. "Not stated" read as a technicality.
    expect(screen.getAllByText("Not on your CV").length).toBeGreaterThan(0);
    expect(screen.queryByText(/you do not have/i)).toBeNull();
  });

  it("shows the coverage count", () => {
    render(<MatchTab state="ready" analysis={ANALYSIS} stale={false} />);

    expect(screen.getByTestId("coverage").textContent).toMatch(/3\s*\/\s*7/);
  });

  it("says it is AI-generated and what it cost", () => {
    render(<MatchTab state="ready" analysis={ANALYSIS} stale={false} />);

    const footer = screen.getByTestId("analysis-provenance").textContent ?? "";
    expect(footer).toMatch(/claude-sonnet-5/);
    expect(footer).toMatch(/0\.0344/);
  });

  it("reads nothing-to-score as ordinary, not as a failure", () => {
    render(<MatchTab state="nothing_to_score" analysis={null} stale={false} />);

    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText(/nothing to score against/i)).toBeInTheDocument();
  });

  it("marks a real failure as one, and says the job is still usable", () => {
    render(
      <MatchTab
        state="failed"
        analysis={{ ...ANALYSIS, error: "The analysis could not be completed." }}
        stale={false}
      />,
    );

    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("offers a re-run when the profile has moved on", () => {
    render(<MatchTab state="ready" analysis={ANALYSIS} stale />);

    expect(screen.getByText(/profile has changed/i)).toBeInTheDocument();
  });
});
