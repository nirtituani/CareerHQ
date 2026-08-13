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

/** Sections in the order a CV reads, which is the order review should follow. */
export const SECTIONS: { kind: string; label: string }[] = [
  { kind: "contact", label: "Contact" },
  { kind: "title", label: "Titles" },
  { kind: "summary", label: "Summary" },
  { kind: "work_experience", label: "Work experience" },
  { kind: "bullet", label: "Achievements" },
  { kind: "skill", label: "Skills" },
  { kind: "project", label: "Projects" },
  { kind: "education", label: "Education" },
  { kind: "certification", label: "Certifications" },
  { kind: "language", label: "Languages" },
];

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
    default:
      return { primary: JSON.stringify(item.payload), details: [] };
  }
}
