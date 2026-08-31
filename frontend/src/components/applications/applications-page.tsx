"use client";

import { Plus, Upload } from "lucide-react";
import { useState } from "react";

import { AddApplication } from "@/components/applications/add-application";
import { ApplicationsView } from "@/components/applications/applications-view";
import { Button } from "@/components/ui/button";
import type { Application } from "@/lib/api";

/**
 * The Applications screen: header, the Add Application modal, and the table.
 *
 * A client component only because the modal opens and closes; the data is
 * fetched on the server and handed down, so the table renders with the page
 * rather than after a round trip.
 */
export function ApplicationsPage({ applications }: { applications: Application[] }) {
  const [adding, setAdding] = useState(false);

  return (
    <>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Applications</h1>
          <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
            {applications.length === 0
              ? "Every job you are pursuing, in one place."
              : `${applications.length} ${applications.length === 1 ? "job" : "jobs"} tracked.`}
          </p>
        </div>

        <div className="flex items-center gap-2">
          {/* Secondary to Add Application: importing is a one-off, adding is
              the daily action. */}
          <Button asChild variant="outline">
            <a href="/applications/import">
              <Upload aria-hidden />
              Import
            </a>
          </Button>

          <Button onClick={() => setAdding(true)}>
            <Plus aria-hidden />
            Add Application
          </Button>
        </div>
      </div>

      <AddApplication open={adding} onOpenChange={setAdding} />

      <ApplicationsView applications={applications} showSearch />
    </>
  );
}
