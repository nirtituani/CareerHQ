import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ImportReview } from "@/components/import-review/review";
import type { ImportedResume } from "@/lib/imports";

function record(overrides: Partial<ImportedResume> = {}): ImportedResume {
  return {
    id: "import-1",
    filename: "cv.pdf",
    status: "extracted",
    extraction_error: null,
    is_fixture: false,
    model: "stub/model",
    created_at: null,
    items: [
      {
        id: "item-1",
        kind: "skill",
        payload: { name: "Python" },
        confidence: 0.99,
        source: "extracted",
        decision: "pending",
        ordinal: 0,
        parent_id: null,
      },
      {
        id: "item-2",
        kind: "skill",
        payload: { name: "Go" },
        confidence: 0.3,
        source: "extracted",
        decision: "pending",
        ordinal: 1,
        parent_id: null,
      },
    ],
    ...overrides,
  };
}

describe("ImportReview", () => {
  it("leaves every item undecided regardless of confidence", () => {
    // FR-029. A 0.99 item and a 0.3 item are equally pending: Principle II
    // admits no threshold, and confidence may inform but never decide.
    render(<ImportReview record={record()} onPatch={vi.fn()} onApprove={vi.fn()} />);

    expect(screen.getByText(/0 of 2/)).toBeInTheDocument();
    expect(screen.getByText(/1 need attention/)).toBeInTheDocument();
  });

  it("shows a persistent warning when the content is fixture data", () => {
    // The one unacceptable outcome of having a fixture mode is somebody
    // approving invented content into their own profile.
    render(
      <ImportReview record={record({ is_fixture: true })} onPatch={vi.fn()} onApprove={vi.fn()} />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(/not your CV/i);
  });

  it("does not warn when the extraction is real", () => {
    render(<ImportReview record={record()} onPatch={vi.fn()} onApprove={vi.fn()} />);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("accepts an item from the keyboard", async () => {
    // Keyboard review is the difference between finishing sixty items and
    // abandoning the import, so it is tested rather than assumed.
    const onPatch = vi.fn().mockResolvedValue(undefined);
    render(<ImportReview record={record()} onPatch={onPatch} onApprove={vi.fn()} />);

    await userEvent.keyboard("a");

    expect(onPatch).toHaveBeenCalledWith("item-1", { decision: "accepted" });
  });

  it("does not hijack letters typed into a field", async () => {
    const onPatch = vi.fn();
    render(
      <>
        <input aria-label="somewhere to type" />
        <ImportReview record={record()} onPatch={onPatch} onApprove={vi.fn()} />
      </>,
    );

    await userEvent.type(screen.getByLabelText("somewhere to type"), "ad");

    expect(onPatch).not.toHaveBeenCalled();
  });
});
