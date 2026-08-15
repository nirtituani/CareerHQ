import { describe as group, expect, it } from "vitest";

import {
  describe as describeItem,
  groupByCategory,
  type ExtractionItem,
} from "@/lib/imports";

function item(kind: string, payload: Record<string, unknown>): ExtractionItem {
  return {
    id: "x",
    kind,
    payload,
    confidence: 0.9,
    source: "extracted",
    decision: "pending",
    ordinal: 0,
    parent_id: null,
  };
}

group("describe", () => {
  it("shows every captured contact field", () => {
    // Regression. The first version rendered name, email and city and silently
    // dropped the phone number and both profile links — all of which had been
    // extracted correctly. The user would have approved the item believing they
    // were never captured, which is the absence of review rather than a shorter
    // version of it.
    const rendered = describeItem(
      item("contact", {
        full_name: "Nir Tituani",
        email: "nirtituani13@gmail.com",
        phone: "052-4626053",
        location: "Tel Aviv",
        links: ["linkedin.com/in/nir-tituani", "https://github.com/nirtituani"],
      }),
    );

    const all = [rendered.primary, ...rendered.details].join(" ");
    for (const value of [
      "Nir Tituani",
      "nirtituani13@gmail.com",
      "052-4626053",
      "Tel Aviv",
      "linkedin.com/in/nir-tituani",
      "https://github.com/nirtituani",
    ]) {
      expect(all).toContain(value);
    }
  });

  it("shows the dates on a role", () => {
    const rendered = describeItem(
      item("work_experience", {
        title: "C++ Developer",
        company: "Sapiens",
        start_date: "10/2017",
        end_date: "01/2026",
        is_current: false,
      }),
    );

    const all = [rendered.primary, ...rendered.details].join(" ");
    expect(all).toContain("10/2017");
    expect(all).toContain("01/2026");
  });

  it("marks a current role as ongoing rather than showing a blank end", () => {
    const rendered = describeItem(
      item("work_experience", {
        title: "Engineer",
        company: "Acme",
        start_date: "2021",
        end_date: null,
        is_current: true,
      }),
    );

    expect([rendered.primary, ...rendered.details].join(" ")).toContain("Present");
  });

  it("shows a skill's category", () => {
    const rendered = describeItem(
      item("skill", { name: "C++", category: "Programming Languages" }),
    );
    expect([rendered.primary, ...rendered.details].join(" ")).toContain("Programming Languages");
  });

  it("omits fields that were genuinely empty rather than printing blanks", () => {
    const rendered = describeItem(item("skill", { name: "Go", category: null }));
    expect(rendered.details).toEqual([]);
  });
});

group("groupByCategory", () => {
  it("keeps the categories the CV used, whatever they are", () => {
    // Nothing is hardcoded. A CV organised as "Languages / Cloud" gets those
    // two; the six groups seen on one real CV were that CV's own headings.
    const groups = groupByCategory([
      item("skill", { name: "C++", category: "Languages" }),
      item("skill", { name: "AWS", category: "Cloud" }),
      item("skill", { name: "Go", category: "Languages" }),
    ]);

    expect(groups.map(([category]) => category)).toEqual(["Languages", "Cloud"]);
    expect(groups[0][1]).toHaveLength(2);
  });

  it("gives an uncategorised list no heading rather than inventing one", () => {
    // A CV with no skill headings would otherwise render a single group called
    // "Other" — a heading its author never wrote, making a plain list look like
    // a categorised one with one odd bucket.
    const groups = groupByCategory([
      item("skill", { name: "C++", category: null }),
      item("skill", { name: "Go", category: "  " }),
    ]);

    expect(groups).toHaveLength(1);
    expect(groups[0][0]).toBeNull();
  });
});
