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
        // Real payloads carry confidence inside, because they come from the
        // extraction schema's model_dump(). The fixture matched the renderer
        // rather than the data until a test needed a field the editor does not
        // expose.
        payload: { name: "Python", category: "Languages", confidence: 0.99 },
        confidence: 0.99,
        source: "extracted",
        decision: "pending",
        ordinal: 0,
        parent_id: null,
      },
      {
        id: "item-2",
        kind: "skill",
        payload: { name: "Go", category: "Languages", confidence: 0.3 },
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

describe("correcting an item", () => {
  it("sends the edited payload and marks it corrected", async () => {
    // FR-003 asks for review, *correction* and approval. Until this existed the
    // screen offered only keep and discard, so `user_corrected` was unreachable
    // and every fact in a profile reported the same provenance forever.
    const onPatch = vi.fn().mockResolvedValue(undefined);
    render(<ImportReview record={record()} onPatch={onPatch} onApprove={vi.fn()} />);

    await userEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]);

    const field = screen.getByLabelText("Skill");
    await userEvent.clear(field);
    await userEvent.type(field, "Rust");
    await userEvent.click(screen.getByRole("button", { name: /save correction/i }));

    expect(onPatch).toHaveBeenCalledWith(
      "item-1",
      expect.objectContaining({ payload: expect.objectContaining({ name: "Rust" }) }),
    );
    expect(screen.getByText("CORRECTED")).toBeInTheDocument();
  });

  it("preserves fields the editor does not expose", async () => {
    // Confidence is not the user's to rewrite, and dropping it on save would
    // lose something the extraction produced.
    const onPatch = vi.fn().mockResolvedValue(undefined);
    render(<ImportReview record={record()} onPatch={onPatch} onApprove={vi.fn()} />);

    await userEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]);
    await userEvent.click(screen.getByRole("button", { name: /save correction/i }));

    const [, body] = onPatch.mock.calls[0] as [string, { payload: Record<string, unknown> }];
    expect(body.payload).toHaveProperty("confidence");
  });

  it("opens the editor from the keyboard", async () => {
    render(<ImportReview record={record()} onPatch={vi.fn()} onApprove={vi.fn()} />);

    await userEvent.keyboard("e");

    expect(screen.getByRole("button", { name: /save correction/i })).toBeInTheDocument();
  });
});

describe("a second import", () => {
  function repeat(): ImportedResume {
    const base = record();
    return {
      ...base,
      items: [
        { ...base.items[0], already_present: true },
        { ...base.items[1], already_present: false },
      ],
    };
  }

  it("says what is already yours and what is new", () => {
    // The phrase appears twice by design — once on each already-held row, once
    // in the summary — so this asserts the rendered text rather than trying to
    // single out an element, which was matching a section badge that happened
    // to share a number.
    const { container } = render(
      <ImportReview record={repeat()} onPatch={vi.fn()} onApprove={vi.fn()} />,
    );

    const text = container.textContent ?? "";
    expect(text).toMatch(/1\s*already in your profile/i);
    expect(text).toMatch(/1\s*new/i);
  });

  it("offers Add only on items the profile does not have", () => {
    // Showing Add on something already yours would invite a click that changes
    // nothing, which is the contradiction the old Keep button had.
    render(<ImportReview record={repeat()} onPatch={vi.fn()} onApprove={vi.fn()} />);

    expect(screen.getAllByRole("button", { name: "Add" })).toHaveLength(1);
  });

  it("narrows the approval button once something is added", async () => {
    const onPatch = vi.fn().mockResolvedValue(undefined);
    render(<ImportReview record={repeat()} onPatch={onPatch} onApprove={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: "Add" }));

    expect(
      screen.getByRole("button", { name: /add 1 selected to my profile/i }),
    ).toBeInTheDocument();
  });

  it("offers no per-item Add on a first import", () => {
    // On a first import people want the whole CV; thirty-nine confirmations of
    // the obvious is an obstacle rather than consent.
    render(<ImportReview record={record()} onPatch={vi.fn()} onApprove={vi.fn()} />);

    expect(screen.queryByRole("button", { name: "Add" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add 2 to my profile/i })).toBeInTheDocument();
  });
});
