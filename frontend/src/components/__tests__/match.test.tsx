import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MatchCell, VERDICT_GLYPH, bandLabel } from "@/components/applications/match-score";

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
