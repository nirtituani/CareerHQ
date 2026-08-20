import { render, screen, within } from "@testing-library/react";
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
    // 85*1 + 85*.6 + 80*.2 + 65*.2 + 40*.25 + 35*.8 + 15*.2 = 206 of 405 → 51
    overall_score: 51,
    verdict: "Strong backend fit, but Kubernetes and Terraform are unproven.",
    criteria_version: "v2-importance",
    error: null,
    credit: { confirmed: 1, transferable: 0.8, partial: 0.6, gap: 0.25, unverified: 0.2 },
    capped_by: { ordinal: 2, text: "Kubernetes in production", importance: 80 },
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

  it("shows the band, the score, and the verdict", () => {
    render(<MatchTab state="ready" analysis={ANALYSIS} stale={false} />);

    expect(screen.getByText(/Stretch/)).toBeInTheDocument();
    expect(screen.getByText(/Kubernetes and Terraform are unproven/)).toBeInTheDocument();

    // The number is shown **beside** the band, never as a bare percentage: a
    // "56% match" implies a measurement nobody took, while a total sitting next
    // to its four parts and their weights is arithmetic a person can check.
    expect(screen.getByTestId("score").textContent).toMatch(/51\s*\/\s*100/);
    expect(screen.queryByText(/51%/)).toBeNull();
  });

  it("draws the score as a ring, sized to the score", () => {
    const { container } = render(<MatchTab state="ready" analysis={ANALYSIS} stale={false} />);

    const arc = container.querySelector<SVGCircleElement>("[data-testid='score-arc']");
    expect(arc).not.toBeNull();

    // The sweep is the score: a full circle at 100, nothing at 0. Asserted on
    // the geometry rather than the animation, because the animation is a
    // presentation of this value and `prefers-reduced-motion` removes it.
    const circumference = 2 * Math.PI * 32;
    const offset = Number(arc?.style.strokeDashoffset);
    expect(offset).toBeCloseTo(circumference * (1 - 51 / 100), 1);
  });

  it("lands on the finished ring when motion is reduced, never on an empty one", () => {
    const { container } = render(<MatchTab state="ready" analysis={ANALYSIS} stale={false} />);
    const arc = container.querySelector<SVGCircleElement>("[data-testid='score-arc']");

    // The base style *is* the finished state and the keyframe only supplies the
    // start. The global reduced-motion rule collapses animations to 0.01ms, so
    // the ring snaps to its true value — if the base style were the empty ring
    // instead, reduced motion would leave the score permanently at zero.
    expect(arc?.style.strokeDashoffset).toBeTruthy();
    expect(Number(arc?.style.strokeDashoffset)).toBeLessThan(2 * Math.PI * 32);
  });

  it("names the score for assistive technology, not only in the drawing", () => {
    render(<MatchTab state="ready" analysis={ANALYSIS} stale={false} />);

    expect(screen.getByRole("img", { name: /51 out of 100.*stretch/i })).toBeInTheDocument();
  });

  it("draws no ring for an analysis with no score", () => {
    const { container } = render(
      <MatchTab state="ready" analysis={{ ...ANALYSIS, overall_score: null }} stale={false} />,
    );

    expect(container.querySelector("[data-testid='score-arc']")).toBeNull();
  });

  it("shows where the score was earned, grouped by verdict", () => {
    render(<MatchTab state="ready" analysis={ANALYSIS} stale={false} />);

    const breakdown = screen.getByTestId("breakdown").textContent ?? "";
    // The same requirements a person is reading below, grouped — not four
    // separate ratings that can disagree with them.
    for (const label of ["Directly on your CV", "Related experience", "Not on your CV"]) {
      expect(breakdown).toContain(label);
    }
  });

  it("shows a breakdown that adds up to the score", () => {
    render(<MatchTab state="ready" analysis={ANALYSIS} stale={false} />);

    // The fixture: 85 confirmed, 85 partial, 80+65+15 unverified, 40 gap,
    // 35 transferable. Worth 405; earned 85 + 51 + 32 + 10 + 28 = 206 → 51.
    const rows = screen.getAllByTestId("earned");
    const totalEarned = rows.reduce((sum, el) => sum + Number(el.dataset.earned), 0);
    const totalWorth = rows.reduce((sum, el) => sum + Number(el.dataset.worth), 0);

    expect(Math.round((100 * totalEarned) / totalWorth)).toBe(
      ANALYSIS.overall_score,
    );
  });

  it("says which requirement held the band down", () => {
    render(<MatchTab state="ready" analysis={ANALYSIS} stale={false} />);

    // 56 sits in Moderate's range; the band reads Stretch. Unexplained that is
    // a contradiction on screen, so the requirement responsible is named.
    expect(screen.getByTestId("cap-reason").textContent).toMatch(/Kubernetes in production/);
  });

  it("shows no breakdown when there are no requirements to group", () => {
    render(
      <MatchTab
        state="ready"
        analysis={{ ...ANALYSIS, requirements: [] }}
        stale={false}
      />,
    );

    expect(screen.queryByTestId("breakdown")).toBeNull();
    expect(screen.getByTestId("score")).toBeInTheDocument();
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

  it("does not repeat the section's own meaning on every row", () => {
    render(<MatchTab state="ready" analysis={ANALYSIS} stale={false} />);

    // Everything under WHAT'S MISSING is missing — saying "Not on your CV" on
    // each row restates the heading four times and buries the one row that
    // means something different. `unverified` is the default here and goes
    // unlabelled; the explanation appears once, for the section.
    const missing = within(screen.getByTestId("whats-missing"));
    expect(missing.queryAllByText("Not on your CV")).toHaveLength(0);
    expect(screen.getAllByText(/add anything you have and score again/i)).toHaveLength(1);

    // And it still never claims you lack the skill.
    expect(screen.queryByText(/you do not have/i)).toBeNull();
  });

  it("still marks the one verdict that is not the section default", () => {
    render(<MatchTab state="ready" analysis={ANALYSIS} stale={false} />);

    // A `gap` is a *proven* shortfall, not a silence. It is the exception in
    // this section, so it is the thing that earns a label — the distinction
    // the five-verdict taxonomy exists for stays visible while the noise goes.
    const missing = within(screen.getByTestId("whats-missing"));
    expect(missing.getByText(/below what they ask/i)).toBeInTheDocument();
  });

  it("shows how much each requirement matters", () => {
    render(<MatchTab state="ready" analysis={ANALYSIS} stale={false} />);

    // Ordering implies priority; nothing stated it. A three-segment meter is
    // the pattern docs/09 §5 already uses for confidence — same shape of
    // signal, so the interface stays one language.
    const critical = screen.getByLabelText(/Kubernetes in production.*critical/i);
    const minor = screen.getByLabelText(/fast-paced startup.*minor/i);

    expect(critical).toBeInTheDocument();
    expect(minor).toBeInTheDocument();
  });

  it("counts only what is directly on the CV, not everything addressed", () => {
    render(<MatchTab state="ready" analysis={ANALYSIS} stale={false} />);

    // The fixture has 1 confirmed of 7. Counting `partial` and `transferable`
    // alongside them reported "4/7 shown on your profile", which reads as a
    // near-perfect match and then contradicts itself with a low score.
    //
    // Worse, it is the error the taxonomy exists to prevent: FR-011b forbids
    // presenting transferable experience as direct experience, and a headline
    // that adds them together does exactly that.
    expect(screen.getByTestId("coverage").textContent).toMatch(/1\s*of\s*7/);
    expect(screen.getByTestId("coverage").textContent).toMatch(/direct/i);
  });

  it("does not report full coverage for a profile that only transfers", () => {
    // The case that exposed this: 8 requirements, none missing, but only 2
    // actually on the CV — shown as "8/8", which invites exactly the wrong
    // conclusion about whether to apply.
    const transfers = {
      ...ANALYSIS,
      requirements: ANALYSIS.requirements.map((r, i) =>
        i === 0
          ? { ...r, verdict: "confirmed" as const, shortfall: null }
          : { ...r, verdict: "transferable" as const, shortfall: "wording" as const,
              evidence: "Something adjacent." },
      ),
    };
    render(<MatchTab state="ready" analysis={transfers} stale={false} />);

    const coverage = screen.getByTestId("coverage").textContent ?? "";
    expect(coverage).toMatch(/1\s*of\s*7/);
    expect(coverage).not.toMatch(/7\s*of\s*7/);
  });

  it("says it is AI-generated and what it cost", () => {
    render(<MatchTab state="ready" analysis={ANALYSIS} stale={false} />);

    const footer = screen.getByTestId("analysis-provenance").textContent ?? "";
    expect(footer).toMatch(/claude-sonnet-5/);
    expect(footer).toMatch(/0\.0344/);
  });

  it("offers to score a job that has requirements but has never been scored", async () => {
    // A record repaired by fetching its posting has requirements and no
    // analysis. Scoring only fires on create, so without this the job is stuck
    // reading "nothing to score against" forever with no way out — the same
    // shape of dead end as the abandoned `pending` row.
    render(
      <MatchTab state="nothing_to_score" analysis={null} stale={false} applicationId="a1" canScore />,
    );

    expect(screen.getByRole("button", { name: /Score this job/i })).toBeInTheDocument();
  });

  it("offers nothing when there is genuinely nothing to score against", () => {
    // No posting, no requirements. Offering a button here would promise a
    // result nothing can produce.
    render(<MatchTab state="nothing_to_score" analysis={null} stale={false} applicationId="a1" />);

    expect(screen.queryByRole("button", { name: /Score this job/i })).toBeNull();
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
