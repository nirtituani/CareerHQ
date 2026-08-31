import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ResearchLegacy } from "@/components/applications/research-legacy";
import type { ResearchPayload } from "@/lib/api";

/** A real 008-shaped payload: tiers, evidence, an empty section with its
 *  reason, and a failed source — the affordances the extraction must keep. */
function tieredPayload(): ResearchPayload {
  return {
    snapshot_id: "legacy-1",
    status: "succeeded",
    shape: "tiered",
    produced_by: "legacy-company",
    failure_reason: null,
    retrieved_at: "2026-08-01T00:00:00Z",
    freshness: "aging",
    cost: "0.058972",
    cost_basis: "recorded",
    research: {
      what_the_company_does: {
        claims: [
          {
            id: "c1",
            text: "Pango operates mobile parking payments.",
            tier: "fact",
            evidence: [{ source_id: "s1", excerpt: "mobile parking payments" }],
            rests_on: [],
          },
          {
            id: "c2",
            text: "The company is positioned as an infrastructure operator.",
            tier: "interpretation",
            evidence: [],
            rests_on: ["c1"],
          },
        ],
        empty_reason: null,
      },
      products_and_services: { claims: [], empty_reason: "No public source covered this." },
      market_and_customers: { claims: [], empty_reason: "No public source covered this." },
      practical_facts: { claims: [], empty_reason: "No public source covered this." },
      interview_preparation: { claims: [], empty_reason: "No public source covered this." },
    },
    sources: [
      {
        source_id: "s1",
        url: "https://pango.co.il/about",
        title: "About Pango",
        fetch_status: "retrieved",
        excerpt: "mobile parking payments",
      },
      {
        source_id: "f1",
        url: "https://dead.example/page",
        title: null,
        fetch_status: "failed",
        excerpt: null,
      },
    ],
  };
}

describe("the extracted legacy (tiered) view — FR-014, testing rule 9", () => {
  it("keeps every 008 affordance: tiers, quoted evidence, rests_on, empty reasons", () => {
    const { container } = render(<ResearchLegacy research={tieredPayload()} />);
    const text = container.textContent ?? "";

    expect(text).toContain("Fact");
    expect(text).toContain("Interpretation");
    expect(text).toContain("mobile parking payments"); // the verbatim quote
    expect(text).toContain("Rests on c1");
    expect(text).toContain("No public source covered this."); // empty explains itself
  });

  it("still lists a source that could not be read (FR-009)", () => {
    const { container } = render(<ResearchLegacy research={tieredPayload()} />);
    expect(container.textContent).toContain("could not be read");
  });

  it("links evidence back to its source", () => {
    const { container } = render(<ResearchLegacy research={tieredPayload()} />);
    const hrefs = Array.from(container.querySelectorAll("a")).map((a) => a.getAttribute("href"));
    expect(hrefs).toContain("https://pango.co.il/about");
  });

  it("names the builtin pipeline when the fallback produced the result", () => {
    const fallback = { ...tieredPayload(), produced_by: "builtin" };
    const { container } = render(<ResearchLegacy research={fallback} />);
    expect(container.textContent).toContain("built-in pipeline");
  });
});
