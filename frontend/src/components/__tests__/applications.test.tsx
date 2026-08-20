import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AddApplication } from "@/components/applications/add-application";
import { ApplicationsView } from "@/components/applications/applications-view";
import { DetailTabs } from "@/components/applications/detail-tabs";
import { StatusPill } from "@/components/applications/status-pill";
import type { Application, NormalizedStatus } from "@/lib/api";

/**
 * The three claims in docs/09 that the renderer can quietly break.
 *
 * Every display bug in slice 003 was found by a person looking at a real CV
 * rather than by the suite — data extracted correctly and then dropped,
 * summarised away, or detached from its context by the renderer. These assert
 * the design decisions that would be invisible in a passing build: that the
 * user's own label survives, that the tiles actually filter, and that an
 * unbuilt tab reads as unbuilt rather than as broken.
 */

function application(overrides: Partial<Application> = {}): Application {
  return {
    id: crypto.randomUUID(),
    company: { id: "c1", name: "Acme Corporation", domain: null },
    job_title: "Senior Backend Engineer",
    location: "Tel Aviv",
    job_description: "We are looking for a Senior Backend Engineer.",
    // `null` is the legacy default deliberately: every application recorded
    // before slice 004 has no captured posting (research.md R1).
    requirements: null,
    job_url: "https://example.com/posting",
    job_description_url: null,
    status: "Applied",
    normalized_status: "applied",
    date_added: "2026-08-01T10:00:00+00:00",
    date_applied: "2026-08-09T10:00:00+00:00",
    source: "Referral",
    salary_text: null,
    imported_match_rating: 0,
    contact_name: null,
    contact_email: null,
    notes: null,
    import_source: null,
    archived_at: null,
    status_history: [],
    ...overrides,
  };
}

describe("status pill", () => {
  it("shows the user's own label, not the normalized category", () => {
    // The label is what they call it; the category is what the system counts.
    // Replacing one with the other throws away the words the person chose.
    render(<StatusPill status="Interview Round 2" normalized="interviewing" />);

    expect(screen.getByText("Interview Round 2")).toBeInTheDocument();
  });

  it("does not print the category beside the label", () => {
    // Every Pre-Applied row read "Pre-Applied WISHLIST" — the same word twice,
    // on every row. A marker that appears everywhere is decoration.
    render(<StatusPill status="Pre-Applied" normalized="wishlist" />);

    expect(screen.getByText("Pre-Applied")).toBeInTheDocument();
    expect(screen.queryByText("wishlist")).not.toBeInTheDocument();
    expect(screen.queryByText(/WISHLIST/i)).not.toBeInTheDocument();
  });

  it("still exposes the category to assistive technology", () => {
    // Available without occupying the row, so the category is not carried by
    // colour alone (docs/09 §7).
    render(<StatusPill status="Interview Round 2" normalized="interviewing" />);

    expect(screen.getByTitle("Counted as interviewing")).toBeInTheDocument();
  });

  it("gives closed outcomes a neutral colour, never the failure red", () => {
    // A rejected application is among the commonest outcomes of a job search —
    // 63 of 96 in the reference data. Painting a third of the list red would
    // make an ordinary week look like a catastrophe (docs/09 §3).
    const closed: NormalizedStatus[] = ["rejected", "withdrawn", "ghosted"];

    for (const normalized of closed) {
      const { container, unmount } = render(
        <StatusPill status={normalized} normalized={normalized} />,
      );
      expect(container.innerHTML).toContain("--color-outcome-closed");
      expect(container.innerHTML).not.toContain("--color-failure");
      unmount();
    }
  });
});

describe("stat tiles", () => {
  const rows = [
    application({ status: "Applied", normalized_status: "applied" }),
    application({ status: "Phone Screen", normalized_status: "interviewing" }),
    application({ status: "Rejected", normalized_status: "rejected" }),
  ];

  it("filters the table when a tile is clicked, and marks the tile selected", async () => {
    // docs/09 §6.1: the tiles are filters, not decoration. This is the claim
    // that breaks silently — the counts stay right while the click does
    // nothing, and the screen still looks correct.
    render(<ApplicationsView applications={rows} showTiles />);

    expect(screen.getAllByRole("row")).toHaveLength(4); // header + 3

    const interviews = screen.getByRole("button", { name: /Interviews/ });
    await userEvent.click(interviews);

    expect(interviews).toHaveAttribute("aria-pressed", "true");
    const body = screen.getAllByRole("row").slice(1);
    expect(body).toHaveLength(1);
    expect(within(body[0]).getByText("Phone Screen")).toBeInTheDocument();
  });

  it("counts everything still in play as active, excluding closed outcomes", () => {
    render(<ApplicationsView applications={rows} showTiles />);

    const active = screen.getByRole("button", { name: /Active/ });
    // Applied and interviewing; the rejected one is closed.
    expect(within(active).getByText("2")).toBeInTheDocument();
  });
});

describe("application detail tabs", () => {
  it("marks unbuilt capabilities in the tab itself", async () => {
    // docs/09 §6.3, T072. Without the marker the user clicks Company to
    // discover it is not built, then clicks Interview to discover the same.
    render(<DetailTabs application={application()} />);

    for (const label of ["Company", "Interview", "Versions"]) {
      const tab = screen.getByRole("tab", { name: new RegExp(label) });
      expect(within(tab).getByLabelText("not built yet")).toBeInTheDocument();
    }

    expect(
      within(screen.getByRole("tab", { name: /Details/ })).queryByLabelText("not built yet"),
    ).not.toBeInTheDocument();
  });

  it("shows the full job description text rather than linking out to it", async () => {
    // The reason User Story 2 exists. **Failure looks like**: the detail view
    // linking out instead of showing stored text — a posting may have expired,
    // and slice 004 cannot tailor against a URL.
    const description = "Responsibilities:\n- Design and operate services\n- Mentor engineers";
    render(<DetailTabs application={application({ job_description: description })} />);

    expect(screen.getByText(/Mentor engineers/)).toBeInTheDocument();
  });

  it("reads an unbuilt panel as unfinished, never as failed", async () => {
    // §5's three empty states. The first must never look like the third: a
    // panel that is simply not built should not alarm anyone.
    const { container } = render(<DetailTabs application={application()} />);

    await userEvent.click(screen.getByRole("tab", { name: /Company/ }));

    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByText(/Company research/)).toBeInTheDocument();
    expect(panel.innerHTML).toContain("dashed");
    expect(container.innerHTML).not.toContain("--color-failure");
  });
});

describe("add application form", () => {
  /** Open the modal and step past the automatic route to the manual form. */
  async function openManualForm() {
    render(<AddApplication open onOpenChange={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /Enter the details manually/ }));
  }

  it("asks how you applied only once the status says you have", async () => {
    // Applied Via and Date Applied are meaningless on a job nobody has applied
    // to yet. The source app asks for both up front, which is most of why its
    // form is long. Failure here is silent: the field simply sits there asking
    // a question that has no answer.
    await openManualForm();

    expect(screen.queryByLabelText("Applied Via")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Date Applied")).not.toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Status"), "Applied");

    expect(screen.getByLabelText("Applied Via")).toBeInTheDocument();
    expect(screen.getByLabelText("Date Applied")).toBeInTheDocument();
  });

  it("offers the source app's own Applied Via options", async () => {
    await openManualForm();

    await userEvent.selectOptions(screen.getByLabelText("Status"), "Applied");

    const options = within(screen.getByLabelText("Applied Via"))
      .getAllByRole("option")
      .map((option) => option.textContent);

    expect(options).toEqual([
      "Select…",
      "Company Website",
      "LinkedIn",
      "Recruiter",
      "Direct Email",
      "Referral",
      "Headhunter",
    ]);
  });

  it("has no rejected toggle anywhere on it", () => {
    // FR-016. The source app carries a `rejected` boolean beside the status and
    // reconciles the two at every read because they disagree. A form control is
    // exactly how a removed column grows back, so the absence is asserted here
    // as well as against information_schema in the backend suite.
    //
    // Queried through the dialog itself, not through `container`: Radix renders
    // into a portal, so `container` is empty and an assertion against it passes
    // whatever the form contains. That was true of this test until it was
    // watched failing.
    render(<AddApplication open onOpenChange={() => {}} />);
    const dialog = screen.getByRole("dialog");

    expect(dialog).toHaveTextContent(/Add Application/);
    expect(dialog.textContent).not.toMatch(/rejected/i);
    expect(within(dialog).queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("prefills the date added with today, so a stale job is visible later", async () => {
    await openManualForm();

    expect(screen.getByLabelText("Date Added")).toHaveValue(
      new Date().toISOString().slice(0, 10),
    );
  });
});

describe("adding a job automatically", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("opens on the automatic route, with manual entry always available", () => {
    render(<AddApplication open onOpenChange={() => {}} />);

    expect(screen.getByLabelText("Job URL")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Enter the details manually/ }),
    ).toBeInTheDocument();
  });

  it("fills the form from what was read, and saves nothing on its own", async () => {
    // Principle II. The extraction populates; the person confirms. A flow that
    // saved here would put a model's reading of a web page into the record with
    // nobody having looked at it.
    const created = vi.fn();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          posting: {
            company: "Acme Corporation",
            job_title: "Senior Backend Engineer",
            location: "Tel Aviv, IL",
            salary_text: "USD 90,000-110,000 year",
            job_description: "About Acme. We build and operate services at scale.",
            requirements: ["5+ years of Python", "Experience with PostgreSQL"],
            company_domain: "acme.com",
          },
          provenance: "structured_data",
          usage: null,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    render(<AddApplication open onOpenChange={created} />);
    await userEvent.type(screen.getByLabelText("Job URL"), "https://boards.greenhouse.io/x/1");
    await userEvent.click(screen.getByRole("button", { name: /Fetch/ }));

    expect(await screen.findByLabelText("Company Name *")).toHaveValue("Acme Corporation");
    expect(screen.getByLabelText("Job Title *")).toHaveValue("Senior Backend Engineer");
    expect(screen.getByLabelText("Location")).toHaveValue("Tel Aviv, IL");
    expect(screen.getByLabelText("Company Website (for logo)")).toHaveValue("acme.com");
    // The requirements are shown rather than hidden behind a disclosure: they
    // are what the person is being asked to approve. **Amended in slice 004**:
    // this box used to hold `job_description`, which since research.md R1 is
    // the whole posting — so it filled with the entire advert under a label
    // saying "Requirements".
    expect(screen.getByLabelText("Requirements")).toHaveValue(
      "5+ years of Python\nExperience with PostgreSQL",
    );

    // And the posting rides along, unedited and unlost — it is what match
    // analysis scores.
    expect(
      screen.getByRole("dialog").querySelector<HTMLInputElement>('input[name="job_description"]')
        ?.value,
    ).toBe("About Acme. We build and operate services at scale.");
  });

  it("says where the fields came from, so they get the right trust", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          posting: { company: "Acme", job_title: "Engineer" },
          provenance: "model",
          usage: { model: "anthropic/claude-sonnet-5", cost: "0.004", is_fixture: false },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    render(<AddApplication open onOpenChange={() => {}} />);
    await userEvent.type(screen.getByLabelText("Job URL"), "https://example.com/job");
    await userEvent.click(screen.getByRole("button", { name: /Fetch/ }));

    expect(await screen.findByText(/reading the posting/i)).toBeInTheDocument();
  });

  it("offers the paste fallback when a site refuses automated access", async () => {
    // The LinkedIn case, and the reason this step exists. Without it the
    // automatic route dead-ends into hand-typing on the sites people use most.
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: "This site does not allow automated access. Paste the posting text instead.",
        }),
        { status: 400, headers: { "Content-Type": "application/json" } },
      ),
    );

    render(<AddApplication open onOpenChange={() => {}} />);
    await userEvent.type(screen.getByLabelText("Job URL"), "https://www.linkedin.com/jobs/view/1");
    await userEvent.click(screen.getByRole("button", { name: /Fetch/ }));

    expect(await screen.findByText(/does not allow automated access/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Paste the posting text/)).toBeInTheDocument();
  });
});

describe("the applications row", () => {
  it("shows the same columns as the source app, and not location", () => {
    // Location is on the record you open, not in a row scanned ninety-six at a
    // time — the user's call, and the reason the row has room for Job Desc.
    render(<ApplicationsView applications={[application()]} />);

    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual([
      "Company",
      "Job Title",
      "Status",
      "Date Applied",
      "Match",
      "Applied Via",
      "Job Desc",
      "",
    ]);
    expect(screen.queryByText("Tel Aviv")).not.toBeInTheDocument();
  });

  it("shows the match rating as a percentage out of five", () => {
    // The source app's `match_rating * 20`. 4 reads as 80%, and 0 means unset
    // rather than a score of zero.
    render(<ApplicationsView applications={[application({ imported_match_rating: 4 })]} />);
    expect(screen.getByText("80%")).toBeInTheDocument();

    cleanup();
    render(<ApplicationsView applications={[application({ imported_match_rating: 0 })]} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("links the Job Desc icon to the posting, and greys it when there is none", () => {
    render(
      <ApplicationsView
        applications={[application({ job_description_url: "https://example.com/job" })]}
      />,
    );
    expect(screen.getByTitle("Open the original posting")).toHaveAttribute(
      "href",
      "https://example.com/job",
    );

    cleanup();
    render(<ApplicationsView applications={[application({ job_url: null })]} />);
    expect(screen.queryByTitle("Open the original posting")).not.toBeInTheDocument();
  });

  it("offers Mark as rejected, and Undo once it is rejected", () => {
    render(<ApplicationsView applications={[application()]} />);
    expect(screen.getByTitle("Mark as rejected")).toBeInTheDocument();
    expect(screen.queryByTitle("Undo rejection")).not.toBeInTheDocument();

    cleanup();
    render(
      <ApplicationsView
        applications={[application({ status: "Rejected", normalized_status: "rejected" })]}
      />,
    );
    // The source app's RotateCcw. Undo restores the previous status from
    // history rather than clearing a flag.
    expect(screen.getByTitle("Undo rejection")).toBeInTheDocument();
  });
});

describe("editing from the row", () => {
  it("opens the same modal, prefilled, and saves rather than creating", async () => {
    // One form, not two. A separate edit screen is how the two drift — the
    // Applied Via rule, the date pair and the absent rejected toggle would all
    // have to be remembered twice.
    const patch = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({}), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    render(
      <ApplicationsView
        applications={[
          application({
            status: "Applied",
            normalized_status: "applied",
            source: "Referral",
            notes: "Referred by Dana",
          }),
        ]}
      />,
    );

    await userEvent.click(screen.getByTitle("Edit"));

    // Straight to the form — there is nothing to read off a URL for a job
    // already recorded.
    expect(screen.queryByLabelText("Job URL")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Company Name *")).toHaveValue("Acme Corporation");
    expect(screen.getByLabelText("Job Title *")).toHaveValue("Senior Backend Engineer");
    expect(screen.getByLabelText("Location")).toHaveValue("Tel Aviv");
    expect(screen.getByLabelText("Notes")).toHaveValue("Referred by Dana");
    // Applied, so how and when it was applied are on screen and filled.
    expect(screen.getByLabelText("Applied Via")).toHaveValue("Referral");

    await userEvent.click(screen.getByRole("button", { name: /Save changes/ }));

    const [url, init] = patch.mock.calls.at(-1) as [string, RequestInit];
    expect(url).toMatch(/\/api\/applications\/[0-9a-f-]+$/);
    expect(init.method).toBe("PATCH");
  });
});

describe("the Add form's Requirements field", () => {
  /**
   * T088. Slice 004 gave `job_description` back its plain meaning — the whole
   * posting — and moved the extracted list to `requirements` (research.md R1).
   *
   * This form did not follow. Its one textarea is labelled **Requirements**,
   * placeholder "One requirement per line…", and was bound to
   * `job_description` — so opening it on an extracted job filled that box with
   * the entire advert.
   *
   * Cosmetic is the least of it. The label invites trimming the box down to a
   * list, and saving writes it straight back to `job_description` — silently
   * restoring the requirements-only storage R1 reversed, after which every
   * analysis scores against a requirements list while the prompt claims to be
   * reading a whole posting. The number would look entirely normal.
   */
  const POSTING =
    "About Cognita\n\nWe build the AI platform that underwrites commercial insurance.";
  const REQUIREMENTS = ["5+ years building production backend services", "Strong Python"];

  it("fills Requirements from requirements, not from the posting", () => {
    render(
      <AddApplication
        open
        onOpenChange={() => {}}
        editing={application({ job_description: POSTING, requirements: REQUIREMENTS })}
      />,
    );

    const field = screen.getByLabelText("Requirements") as HTMLTextAreaElement;

    expect(field.value).toBe(REQUIREMENTS.join("\n"));
    expect(field.value).not.toContain("underwrites commercial insurance");
  });

  it("keeps the posting through the form rather than dropping it", () => {
    // The posting is what match analysis scores. A person who opens this form
    // on an extracted job and saves must not silently discard it.
    render(
      <AddApplication
        open
        onOpenChange={() => {}}
        editing={application({ job_description: POSTING, requirements: REQUIREMENTS })}
      />,
    );

    const carried = screen
      .getByRole("dialog")
      .querySelector<HTMLInputElement>('input[name="job_description"]');

    expect(carried).not.toBeNull();
    expect(carried?.value).toBe(POSTING);
  });
});

describe("requirements rendering", () => {
  it("shows one bullet per requirement", () => {
    // Stored one per line. As a single pre-wrapped block a scannable list read
    // as a paragraph, which is the whole reason to store them as lines.
    render(
      <DetailTabs
        application={application({
          job_description: "6+ years of experience\nProven Python developer\nExperience with RAG",
        })}
      />,
    );

    const items = screen.getAllByRole("listitem").map((li) => li.textContent);
    expect(items).toEqual([
      "•6+ years of experience",
      "•Proven Python developer",
      "•Experience with RAG",
    ]);
  });

  it("does not double-bullet a source that already used dashes", () => {
    render(
      <DetailTabs
        application={application({ job_description: "- 6+ years\n• Python\n* PostgreSQL" })}
      />,
    );

    const items = screen.getAllByRole("listitem").map((li) => li.textContent);
    expect(items).toEqual(["•6+ years", "•Python", "•PostgreSQL"]);
  });

  it("leaves prose as prose", () => {
    // Records saved before requirements extraction existed hold paragraphs.
    // Bulleting each of their lines would be worse than leaving them alone.
    render(
      <DetailTabs
        application={application({
          job_description: "Company Overview:\n\nWe are a company that does things.",
        })}
      />,
    );

    expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
    expect(screen.getByText(/We are a company/)).toBeInTheDocument();
  });
});

describe("the Active tile", () => {
  // The source app's own definition, from its dashboard query:
  //   status NOT IN ('Pre-Applied','Rejected','Ghosted','Withdrawn')
  //          AND (rejected IS NOT TRUE)
  // Pre-Applied is *not* active — nothing has been sent yet. That is the case
  // this got wrong: an exclusion list of only the closed outcomes let every
  // wishlist row count as in flight, so the number said "you have six
  // applications running" when none had been submitted.
  const rows = [
    application({ status: "Pre-Applied", normalized_status: "wishlist" }),
    application({ status: "Applied", normalized_status: "applied" }),
    application({ status: "Phone Screen", normalized_status: "interviewing" }),
    application({ status: "Offer Received", normalized_status: "offer" }),
    application({ status: "Rejected", normalized_status: "rejected" }),
    application({ status: "Ghosted", normalized_status: "ghosted" }),
    application({ status: "Withdrawn", normalized_status: "withdrawn" }),
    // A custom label, which the source app counts as active because its
    // exclusion list does not name it.
    application({ status: "Call", normalized_status: "other" }),
  ];

  it("does not count Pre-Applied as active", () => {
    render(<ApplicationsView applications={rows} showTiles />);

    // Applied, Phone Screen, Offer Received, Call — not the wishlist row and
    // not the three closed ones.
    const active = screen.getByRole("button", { name: /Active/ });
    expect(within(active).getByText("4")).toBeInTheDocument();
  });

  it("excludes Pre-Applied from the filtered table too", async () => {
    render(<ApplicationsView applications={rows} showTiles />);

    await userEvent.click(screen.getByRole("button", { name: /Active/ }));

    const shown = screen.getAllByRole("row").slice(1);
    expect(shown).toHaveLength(4);
    expect(screen.queryByText("Pre-Applied")).not.toBeInTheDocument();
  });
});
