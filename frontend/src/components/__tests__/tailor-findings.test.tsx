import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TailorDiffItem } from "@/components/applications/tailor-diff-item";
import type { ReviewerFinding, VersionItem } from "@/lib/api";

/**
 * T066 — where a Reviewer concern is rendered, which is the whole of FR-042.
 *
 * The failure this file exists to prevent has no error and no visual glitch: a
 * finding rendered as a page-level banner looks perfectly reasonable. It is
 * only *unattributable*. Eleven proposals and one note reading "stronger than
 * your profile shows" leaves the reader either guessing which of the eleven it
 * means or re-reading all of them — and the person doing that re-reading is
 * deciding whether to send the document to an employer.
 *
 * So these assert **containment**, not presence. `getByText` would pass against
 * a banner. The finding must be a descendant of the item it concerns.
 *
 * The one exception is `uncovered`, which must stay an exception: an
 * unaddressed requirement has no item to point at, and manufacturing one would
 * demand a reference the Reviewer has no honest basis to give.
 */

function finding(overrides: Partial<ReviewerFinding> = {}): ReviewerFinding {
  return {
    kind: "overstated",
    detail: "The profile shows a latency improvement but never states 40%.",
    quoted_text: "cutting p99 latency 40%",
    attempt: 0,
    ...overrides,
  };
}

function item(overrides: Partial<VersionItem> = {}): VersionItem {
  return {
    id: "item-1",
    source_kind: "experience_bullet",
    source_item_id: "bullet-1",
    position: 0,
    included: true,
    original_text: "Led the payments platform team for six years.",
    proposed_text: "Owned the payments platform for six years.",
    final_text: "Owned the payments platform for six years.",
    decision: "pending",
    findings: [],
    ...overrides,
  };
}

describe("a finding's position on the page", () => {
  it("renders inside the item it concerns, not beside it", () => {
    render(<TailorDiffItem item={item({ findings: [finding()] })} onDecide={vi.fn()} />);

    // Containment, not presence. A banner would satisfy `getByText`.
    const row = screen.getByTestId("diff-item");
    const note = within(row).getByTestId("finding");
    expect(row).toContainElement(note);
  });

  it("follows the proposal rather than preceding it", () => {
    const { container } = render(
      <TailorDiffItem item={item({ findings: [finding()] })} onDecide={vi.fn()} />,
    );

    // Subordinate (T068): the proposal is what a person is deciding about and
    // the note is commentary on it. A note above the text it concerns reads as
    // a warning about the whole item and is the banner problem in miniature.
    const proposed = screen.getByTestId("proposed-text");
    const note = screen.getByTestId("finding");
    const order = proposed.compareDocumentPosition(note);
    expect(order & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(container.textContent).toContain("cutting p99 latency 40%");
  });

  it("quotes the words it objects to", () => {
    render(<TailorDiffItem item={item({ findings: [finding()] })} onDecide={vi.fn()} />);

    // A finding that cannot say *which* words are unsupported cannot be
    // checked by a person, which is the whole reason the schema requires a
    // quote on `ungrounded` and the prompt asks for one everywhere else.
    expect(screen.getByTestId("finding")).toHaveTextContent("cutting p99 latency 40%");
  });

  it("is not painted as a failure", () => {
    const { container } = render(
      <TailorDiffItem item={item({ findings: [finding()] })} onDecide={vi.fn()} />,
    );

    // docs/09 §3 reserves red for things that broke. A Reviewer note on a draft
    // is the system working exactly as designed, and on an ordinary draft there
    // are several. Painting them red makes a working run look like an incident.
    expect(container.innerHTML).toContain("--color-attention");
    expect(container.innerHTML).not.toContain("--color-failure");
  });

  it("marks nothing on an item the Reviewer did not object to", () => {
    render(<TailorDiffItem item={item()} onDecide={vi.fn()} />);

    expect(screen.queryByTestId("finding")).toBeNull();
  });
});

describe("findings from more than one review pass", () => {
  it("says which pass caught each one", () => {
    // Findings persist from **every** review pass, deliberately — a
    // fabrication caught on attempt one and fixed on attempt two still
    // happened, and the record is the evidence the guardrail ran.
    //
    // Rendered without that context, three near-identical notes on one bullet
    // read as three simultaneous complaints about the wording currently on
    // screen, which is both wrong and alarming. They are a history.
    render(
      <TailorDiffItem
        item={item({
          findings: [
            finding({ attempt: 0, detail: "Overstates the latency work." }),
            finding({ attempt: 1, detail: "Still overstates it." }),
          ],
        })}
        onDecide={vi.fn()}
      />,
    );

    const notes = screen.getAllByTestId("finding");
    expect(notes).toHaveLength(2);
    expect(notes[0]).toHaveTextContent(/first pass/i);
    expect(notes[1]).toHaveTextContent(/revision 1/i);
  });

  it("says nothing about passes when there was only one", () => {
    // The marker exists to disambiguate. Printing "first pass" on every finding
    // of every single-pass run is the `EXTRACTED` provenance mistake again: a
    // label carried by everything tells a reader nothing and costs a line.
    render(<TailorDiffItem item={item({ findings: [finding({ attempt: 0 })] })} onDecide={vi.fn()} />);

    expect(screen.getByTestId("finding").textContent).not.toMatch(/first pass/i);
  });
});
