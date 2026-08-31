import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ResearchSections } from "@/components/applications/research-sections";
import type { ResearchPayload, SectionsResearch } from "@/lib/api";

function sectionsResearch(overrides: Partial<SectionsResearch> = {}): SectionsResearch {
  return {
    company_identification: {
      official_name: "Pango Pay & Go Ltd.",
      website: "https://www.pango.co.il",
      headquarters: "Petah Tikva, Israel",
      how_identified: "Matched the posting's location and parking domain.",
    },
    company_overview: "An Israeli smart-mobility company operating parking payments.",
    products_and_services: "The Pango app; operator dashboards.",
    business_and_market: "Transaction-fee SaaS; owned by Milgam and Unicell.",
    relevant_to_your_role: "The Parking team runs Python and AWS at scale.",
    what_to_know_before_the_interview: ["Owned by Milgam and Unicell.", "Millions of users."],
    questions_worth_asking: ["How is DynamoDB scaled for peak parking traffic?"],
    ...overrides,
  };
}

function payload(overrides: Partial<ResearchPayload> = {}): ResearchPayload {
  return {
    snapshot_id: "snap-1",
    status: "succeeded",
    shape: "sections",
    produced_by: "provider:tavily-research",
    failure_reason: null,
    retrieved_at: new Date().toISOString(),
    freshness: "fresh",
    cost: "0.456",
    cost_basis: "estimate",
    research: sectionsResearch(),
    sources: [
      {
        source_id: "s1",
        url: "https://www.pango.co.il",
        title: "Pango",
        fetch_status: "retrieved",
        excerpt: null,
      },
      {
        source_id: "s2",
        url: "https://crunchbase.com/organization/pango",
        title: "Crunchbase",
        fetch_status: "retrieved",
        excerpt: null,
      },
    ],
    ...overrides,
  };
}

describe("the sections-first research view (SC-008, FR-008/009/010)", () => {
  it("renders all seven sections and the entity identification", () => {
    const { container } = render(<ResearchSections research={payload()} />);
    const text = container.textContent ?? "";

    expect(text).toContain("Pango Pay & Go Ltd.");
    expect(text).toContain("Matched the posting's location and parking domain.");
    expect(text).toContain("Company overview");
    expect(text).toContain("Products & services");
    expect(text).toContain("Business & market");
    expect(text).toContain("Relevant to your role");
    expect(text).toContain("What to know before the interview");
    expect(text).toContain("Questions worth asking");
    expect(text).toContain("Sources");
    expect(text).toContain("How is DynamoDB scaled for peak parking traffic?");
  });

  it("exposes no tier vocabulary anywhere in the rendered output", () => {
    // SC-008, asserted against the full render target — the whole document
    // body, not a sub-container, so a portal could not hide a badge from the
    // assertion (testing rule 3).
    render(<ResearchSections research={payload()} />);
    const text = document.body.textContent ?? "";

    for (const forbidden of ["Fact", "Interpretation", "Inference"]) {
      expect(text).not.toContain(forbidden);
    }
  });

  it("renders provider sources as attribution without verified-quote affordances", () => {
    const { container } = render(<ResearchSections research={payload()} />);
    // No blockquote/verified marker for excerpt-less sources (FR-010); the
    // links themselves are still there.
    expect(container.querySelectorAll("blockquote")).toHaveLength(0);
    const links = Array.from(container.querySelectorAll("a")).map((a) => a.getAttribute("href"));
    expect(links).toContain("https://www.pango.co.il");
    expect(links).toContain("https://crunchbase.com/organization/pango");
  });

  it("shows a verified quote only where a source actually carries one", () => {
    const withExcerpt = payload({
      sources: [
        {
          source_id: "s1",
          url: "https://pango.co.il/about",
          title: "About",
          fetch_status: "retrieved",
          excerpt: "mobile parking payments",
        },
      ],
    });
    const { container } = render(<ResearchSections research={withExcerpt} />);
    expect(container.querySelectorAll("blockquote")).toHaveLength(1);
    expect(container.textContent).toContain("mobile parking payments");
  });

  it("renders the three freshness states distinctly", () => {
    // FR-013: fresh is unadorned; aging shows its age; stale flags it and
    // suggests refresh.
    const old = new Date(Date.now() - 40 * 24 * 3600 * 1000).toISOString();

    const fresh = render(<ResearchSections research={payload({ freshness: "fresh" })} />);
    expect(fresh.container.textContent).not.toContain("Older research");
    expect(fresh.container.textContent).not.toContain("Ageing research");
    fresh.unmount();

    const aging = render(
      <ResearchSections research={payload({ freshness: "aging", retrieved_at: old })} />,
    );
    expect(aging.container.textContent).toContain("Ageing research");
    aging.unmount();

    const stale = render(<ResearchSections research={payload({ freshness: "stale" })} />);
    expect(stale.container.textContent).toContain("Older research");
    expect(stale.container.textContent?.toLowerCase()).toContain("refresh");
  });

  it("lets a no-posting run explain itself instead of pretending", () => {
    // US2/FR-011: the provider was told to say so; the view must not swallow
    // or dress up that explanation.
    const explained = payload({
      research: sectionsResearch({
        relevant_to_your_role:
          "No job posting was provided for this application, so this research is company-level.",
      }),
    });
    const { container } = render(<ResearchSections research={explained} />);
    expect(container.textContent).toContain("No job posting was provided");
  });

  it("names the producing path quietly in the sources area", () => {
    const fallback = payload({ produced_by: "builtin" });
    const { container } = render(<ResearchSections research={fallback} />);
    expect(container.textContent).toContain("built-in pipeline");
  });
});
