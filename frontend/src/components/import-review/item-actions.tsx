"use client";

import { ConfidenceMeter, ProvenanceLabel } from "@/components/provenance";
import { Button } from "@/components/ui/button";
import type { Decision, ExtractionItem } from "@/lib/imports";

/**
 * The controls for one reviewable item.
 *
 * Extracted because there are two render paths — skills are grouped by
 * category, everything else is a flat list — and adding an affordance to one
 * and not the other happened **twice**: Edit, then Add. Both times the
 * behaviour depended on which section you were looking at, which is not a
 * property anyone would design on purpose. One component makes that class of
 * bug impossible rather than merely unlikely.
 */
export function ItemActions({
  item,
  isRepeat,
  onDecide,
  onEdit,
}: {
  item: ExtractionItem;
  isRepeat: boolean;
  onDecide: (decision: Decision) => void;
  onEdit: () => void;
}) {
  if (item.already_present) {
    // Nothing to decide: it is already yours. Saying so beats showing controls
    // that would change nothing — the contradiction the old Keep button had.
    return (
      <span className="flex shrink-0 items-center gap-3">
        <span className="text-xs" style={{ color: "var(--faint)" }}>
          Already in your profile
        </span>
      </span>
    );
  }

  return (
    <span className="flex shrink-0 items-center gap-2">
      <ConfidenceMeter value={item.confidence} />
      <ProvenanceLabel source={item.source} />

      {isRepeat && (
        <Button
          size="sm"
          variant={item.decision === "accepted" ? "default" : "outline"}
          onClick={() => onDecide(item.decision === "accepted" ? "pending" : "accepted")}
        >
          {item.decision === "accepted" ? "Added" : "Add"}
        </Button>
      )}

      <Button size="sm" variant="ghost" onClick={onEdit}>
        Edit
      </Button>
      <Button
        size="sm"
        variant="ghost"
        onClick={() => onDecide(item.decision === "discarded" ? "pending" : "discarded")}
      >
        {item.decision === "discarded" ? "Undo" : "Discard"}
      </Button>
    </span>
  );
}
