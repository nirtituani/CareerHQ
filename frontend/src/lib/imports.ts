/** Types and calls for the CV import flow. */

import type { Source } from "@/components/provenance";

export type Decision = "pending" | "accepted" | "discarded";

export type ExtractionItem = {
  id: string;
  kind: string;
  payload: Record<string, unknown>;
  confidence: number;
  source: Source;
  decision: Decision;
  ordinal: number;
  parent_id: string | null;
};

export type ImportedResume = {
  id: string;
  filename: string;
  status: "pending" | "extracted" | "failed" | "approved" | "discarded";
  extraction_error: string | null;
  /** True when the content is canned demo data rather than a real extraction. */
  is_fixture: boolean;
  model: string | null;
  created_at: string | null;
  items: ExtractionItem[];
};

/**
 * Sections in the order a CV reads, which is the order review should follow.
 *
 * **Bullets are not a section.** They are shown nested under the role they
 * belong to, because a bullet reviewed on its own cannot be checked: the whole
 * question is whether it was attached to the right job, and an "Achievements"
 * list strips exactly the context that would answer it. Nine bullets from two
 * roles, listed flat, are nine claims you have to take on trust.
 */
export const SECTIONS: { kind: string; label: string }[] = [
  { kind: "contact", label: "Contact" },
  { kind: "title", label: "Titles" },
  { kind: "summary", label: "Summary" },
  { kind: "work_experience", label: "Work experience" },
  { kind: "skill", label: "Skills" },
  { kind: "project", label: "Projects" },
  { kind: "education", label: "Education" },
  { kind: "certification", label: "Certifications" },
  { kind: "language", label: "Languages" },
  { kind: "volunteer", label: "Volunteering" },
  { kind: "military_service", label: "Military service" },
];

/** Bullets belonging to a role, in CV order. */
export function bulletsOf(items: ExtractionItem[], roleId: string): ExtractionItem[] {
  return items.filter((i) => i.kind === "bullet" && i.parent_id === roleId);
}

/**
 * How one item is rendered for review.
 *
 * `primary` is what the item *is*; `details` are the remaining captured fields.
 *
 * **Every populated field appears somewhere.** An earlier version returned a
 * single summary line and silently dropped the rest — a real CV's contact block
 * showed name, email and city while the phone number and two profile links were
 * extracted and invisible. That is not a smaller version of review, it is the
 * absence of it: the user would have approved the item believing those fields
 * had not been captured. FR-003 asks them to verify what was extracted, which
 * they cannot do for anything the interface does not show them.
 */
export type Described = { primary: string; details: string[] };

function join(...parts: (string | null | undefined)[]): string {
  return parts.filter(Boolean).join(" · ");
}

function dates(p: Record<string, unknown>): string | null {
  const start = p.start_date as string | null;
  const end = (p.is_current ? "Present" : (p.end_date as string | null)) ?? null;
  if (!start && !end) return null;
  return [start ?? "?", end ?? "?"].join(" – ");
}

export function describe(item: ExtractionItem): Described {
  const p = item.payload as Record<string, unknown>;
  const str = (k: string) => (p[k] as string | null) ?? null;

  switch (item.kind) {
    case "contact": {
      const links = Array.isArray(p.links) ? (p.links as string[]) : [];
      return {
        primary: str("full_name") ?? "Contact details",
        details: [join(str("email"), str("phone"), str("location")), ...links].filter(Boolean),
      };
    }
    case "title":
      return { primary: str("title") ?? "", details: [] };
    case "summary":
      return { primary: str("text") ?? "", details: [] };
    case "work_experience":
      return {
        primary: join(str("title"), str("company")),
        details: [join(dates(p), str("location"))].filter(Boolean),
      };
    case "bullet":
      return { primary: str("text") ?? "", details: [] };
    case "skill":
      return { primary: str("name") ?? "", details: [str("category") ?? ""].filter(Boolean) };
    case "project":
      return {
        primary: str("name") ?? "",
        details: [str("description"), str("url")].filter((x): x is string => Boolean(x)),
      };
    case "education":
      return {
        primary: join(str("qualification"), str("field_of_study"), str("institution")),
        details: [join(dates(p), str("grade"))].filter(Boolean),
      };
    case "certification":
      return {
        primary: join(str("name"), str("issuer")),
        details: [str("year") ?? ""].filter(Boolean),
      };
    case "language":
      return { primary: join(str("name"), str("proficiency")), details: [] };
    case "military_service":
      return {
        primary: join(str("role"), str("branch")),
        details: [join(dates(p)), str("details") ?? ""].filter(Boolean),
      };
    case "volunteer":
      return {
        primary: join(str("role"), str("organisation")),
        details: [join(dates(p)), str("description") ?? ""].filter(Boolean),
      };
    default:
      return { primary: JSON.stringify(item.payload), details: [] };
  }
}


/**
 * Skills grouped by the category the CV used.
 *
 * A real CV listed 22 skills under six headings — Programming Languages,
 * Databases, Development Tools, AI Tools, Cloud, Distributed Systems. Rendering
 * them as one flat list of 22 discards the structure the author wrote and makes
 * the section a wall to be skimmed rather than reviewed. The categories were
 * being extracted correctly the whole time; only the display ignored them.
 */
export function groupByCategory(items: ExtractionItem[]): [string | null, ExtractionItem[]][] {
  const groups = new Map<string | null, ExtractionItem[]>();

  for (const item of items) {
    const raw = (item.payload as Record<string, unknown>).category;
    const category = typeof raw === "string" && raw.trim() ? raw : null;
    groups.set(category, [...(groups.get(category) ?? []), item]);
  }

  // A CV with no skill headings produces one nameless group. Labelling it
  // "Other" would invent a heading the author never wrote and make an
  // uncategorised list look like a categorised one with a single odd bucket.
  // The caller renders a null category as no heading at all.
  return [...groups.entries()];
}

/**
 * The fields a reviewer can correct, per kind.
 *
 * FR-003 asks for "review, **correction**, and approval". Until this existed
 * the screen offered only keep and discard, so a wrong value could be thrown
 * away but never fixed — and `user_corrected` was unreachable, which made the
 * whole provenance system report the same answer for every fact ever imported.
 *
 * Confidence and internal keys are deliberately absent: the model's own
 * certainty is not the user's to rewrite, and a corrected value carries its own
 * meaning through provenance instead.
 */
export type EditableField = { key: string; label: string; multiline?: boolean };

export const EDITABLE_FIELDS: Record<string, EditableField[]> = {
  contact: [
    { key: "full_name", label: "Name" },
    { key: "email", label: "Email" },
    { key: "phone", label: "Phone" },
    { key: "location", label: "Location" },
  ],
  title: [{ key: "title", label: "Title" }],
  summary: [{ key: "text", label: "Summary", multiline: true }],
  work_experience: [
    { key: "title", label: "Job title" },
    { key: "company", label: "Company" },
    { key: "location", label: "Location" },
    { key: "start_date", label: "Start" },
    { key: "end_date", label: "End" },
  ],
  bullet: [{ key: "text", label: "Achievement", multiline: true }],
  skill: [
    { key: "name", label: "Skill" },
    { key: "category", label: "Category" },
  ],
  project: [
    { key: "name", label: "Project" },
    { key: "description", label: "Description", multiline: true },
    { key: "url", label: "Link" },
  ],
  education: [
    { key: "qualification", label: "Qualification" },
    { key: "field_of_study", label: "Field of study" },
    { key: "institution", label: "Institution" },
    { key: "start_date", label: "Start" },
    { key: "end_date", label: "End" },
    { key: "grade", label: "Grade" },
  ],
  certification: [
    { key: "name", label: "Certification" },
    { key: "issuer", label: "Issuer" },
    { key: "year", label: "Year" },
  ],
  language: [
    { key: "name", label: "Language" },
    { key: "proficiency", label: "Proficiency" },
  ],
  military_service: [
    { key: "role", label: "Role" },
    { key: "branch", label: "Branch" },
    { key: "start_date", label: "Start" },
    { key: "end_date", label: "End" },
  ],
  volunteer: [
    { key: "role", label: "Role" },
    { key: "organisation", label: "Organisation" },
    { key: "start_date", label: "Start" },
    { key: "end_date", label: "End" },
  ],
};
