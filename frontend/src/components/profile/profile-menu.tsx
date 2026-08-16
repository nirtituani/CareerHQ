"use client";

import { MoreHorizontal, Pencil, Trash2, Upload } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { useEditMode } from "@/components/profile/edit-mode";
import { ClearProfileDialog } from "@/components/profile/remove";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

/**
 * The profile's actions, behind one control.
 *
 * Three buttons across the header made the page look like a toolbar for a
 * document rather than a record of someone's career, and gave "clear my
 * profile" the same visual weight as "edit" despite one being reversible and
 * the other not. Collapsing them puts the destructive option where it has to be
 * chosen deliberately, which is the same reason it asks for a typed
 * confirmation afterwards.
 */
export function ProfileMenu({ total }: { total: number }) {
  const { editing, toggle } = useEditMode();
  const [clearing, setClearing] = useState(false);

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="sm" aria-label="Profile actions" className="px-2">
            <MoreHorizontal className="size-4" />
          </Button>
        </DropdownMenuTrigger>

        <DropdownMenuContent align="end" className="w-52">
          <DropdownMenuItem onSelect={toggle}>
            <Pencil className="size-4" />
            {editing ? "Done editing" : "Edit profile"}
          </DropdownMenuItem>

          <DropdownMenuItem asChild>
            <Link href="/import">
              <Upload className="size-4" />
              Import another CV
            </Link>
          </DropdownMenuItem>

          <DropdownMenuSeparator />

          <DropdownMenuItem
            onSelect={() => setClearing(true)}
            style={{ color: "var(--color-failure)" }}
          >
            <Trash2 className="size-4" />
            Clear my profile
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      {/* Rendered outside the menu: the confirmation asks for a typed word, and
          a menu that closes on the first keystroke cannot host that. */}
      {clearing && <ClearProfileDialog total={total} onClose={() => setClearing(false)} />}
    </>
  );
}
