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

/** A one-line rendering of an item, for the review list. */
export function summarise(item: ExtractionItem): string {
  const p = item.payload as Record<string, string | undefined>;
  switch (item.kind) {
    case "contact":
      return [p.full_name, p.email, p.location].filter(Boolean).join(" · ") || "Contact details";
    case "title":
      return p.title ?? "";
    case "summary":
      return p.text ?? "";
    case "work_experience":
      return [p.title, p.company].filter(Boolean).join(" — ");
    case "bullet":
      return p.text ?? "";
    case "skill":
      return p.name ?? "";
    case "project":
      return p.name ?? "";
    case "education":
      return [p.qualification, p.institution].filter(Boolean).join(", ");
    case "certification":
      return [p.name, p.issuer].filter(Boolean).join(" — ");
    case "language":
      return [p.name, p.proficiency].filter(Boolean).join(" — ");
    default:
      return JSON.stringify(item.payload);
  }
}
