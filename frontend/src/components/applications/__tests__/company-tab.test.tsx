import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CompanyTab } from "@/components/applications/company-tab";
import type { ResearchPayload } from "@/lib/api";

const api = vi.hoisted(() => ({
  getResearch: vi.fn(),
  startResearch: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  getResearch: api.getResearch,
  startResearch: api.startResearch,
}));

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
    company: "Pango",
    last_failure: null,
    research: {
      company_identification: {
        official_name: "Pango Pay & Go Ltd.",
        website: "https://www.pango.co.il",
        headquarters: null,
        how_identified: "matched",
      },
      company_overview: "o",
      products_and_services: "p",
      business_and_market: "b",
      relevant_to_your_role: "r",
      what_to_know_before_the_interview: ["k"],
      questions_worth_asking: ["q"],
    },
    sources: [],
    ...overrides,
  };
}

beforeEach(() => {
  api.getResearch.mockReset();
  api.startResearch.mockReset();
});

describe("failure and reuse stay visible in the tab (review fixes)", () => {
  it("shows a newer failed refresh riding along the current research", async () => {
    api.getResearch.mockResolvedValue(
      payload({
        last_failure: {
          failure_reason: "ResearchProviderUnavailable",
          retrieved_at: new Date().toISOString(),
        },
      }),
    );
    render(<CompanyTab applicationId="app-1" />);

    await screen.findByText(/latest refresh/i);
    expect(document.body.textContent).toContain("ResearchProviderUnavailable");
    // The research body still renders underneath — failure rides along, it
    // does not evict (FR-016 + US3 together).
    expect(document.body.textContent).toContain("Pango Pay & Go Ltd.");
  });

  it("tells the user when a refresh was answered by reuse instead of a run", async () => {
    api.getResearch.mockResolvedValue(payload());
    api.startResearch.mockResolvedValue({
      snapshot_id: "snap-1",
      status: "succeeded",
      reused: true,
    });
    render(<CompanyTab applicationId="app-1" />);
    await screen.findByText("Refresh research");

    await userEvent.click(screen.getByText("Refresh research"));

    await waitFor(() => {
      expect(document.body.textContent).toMatch(/up to date|reused/i);
    });
  });

  it("says nothing about reuse when a real run started", async () => {
    api.getResearch.mockResolvedValue(payload());
    api.startResearch.mockResolvedValue({
      snapshot_id: "snap-2",
      status: "running",
      reused: false,
    });
    render(<CompanyTab applicationId="app-1" />);
    await screen.findByText("Refresh research");

    await userEvent.click(screen.getByText("Refresh research"));

    await waitFor(() => expect(api.startResearch).toHaveBeenCalled());
    expect(document.body.textContent).not.toMatch(/up to date/i);
  });
});
