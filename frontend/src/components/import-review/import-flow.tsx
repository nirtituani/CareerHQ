"use client";

import { useState } from "react";

import { ImportReview } from "@/components/import-review/review";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import type { ImportedResume } from "@/lib/imports";

type State =
  | { name: "idle" }
  | { name: "uploading"; filename: string }
  | { name: "extracting"; filename: string }
  | { name: "reviewing"; record: ImportedResume }
  | { name: "failed"; message: string }
  | { name: "done" };

/**
 * Upload and extraction states, per docs/09 §6.6.
 *
 * The state that matters is `failed`. A CV that could not be read must say so
 * and suggest why — never present an empty review form, which would tell the
 * user their CV was read and found to contain nothing. That is the difference
 * between "we could not read this" and "you have no career history", and only
 * one of them is true.
 */
export function ImportFlow({ initial = null }: { initial?: ImportedResume | null }) {
  const [state, setState] = useState<State>(
    // A review already in progress resumes straight into itself. The id lives
    // in the URL, so a refresh is no longer a lost review and another paid
    // extraction.
    initial && initial.status === "extracted"
      ? { name: "reviewing", record: initial }
      : { name: "idle" },
  );

  async function upload(file: File) {
    setState({ name: "uploading", filename: file.name });
    const body = new FormData();
    body.append("file", file);

    try {
      setState({ name: "extracting", filename: file.name });
      const response = await fetch("/api/imports/resume", { method: "POST", body });

      if (!response.ok) {
        const detail = await response
          .json()
          .then((b: { detail?: string }) => b.detail)
          .catch(() => undefined);
        throw new ApiError(response.status, detail ?? "That upload could not be processed.");
      }

      const record = (await response.json()) as ImportedResume;
      // Put the id in the URL before rendering the review, so the very first
      // refresh already has somewhere to return to.
      window.history.replaceState(null, "", `/import?id=${record.id}`);
      setState({ name: "reviewing", record });
    } catch (error) {
      setState({
        name: "failed",
        message:
          error instanceof ApiError
            ? error.message
            : "Something went wrong reading that file.",
      });
    }
  }

  if (state.name === "reviewing") {
    return (
      <ImportReview
        record={state.record}
        onPatch={async (itemId, patch) => {
          await fetch(`/api/imports/${state.record.id}/items/${itemId}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(patch),
          });
        }}
        onApprove={async () => {
          const response = await fetch(`/api/imports/${state.record.id}/approve`, {
            method: "POST",
          });
          if (response.ok || response.status === 409) setState({ name: "done" });
        }}
      />
    );
  }

  if (state.name === "done") {
    return (
      <div className="rounded-lg border p-8 text-center" style={{ borderColor: "var(--border)" }}>
        <h2 className="text-lg" style={{ fontFamily: "var(--font-display)" }}>
          Your profile is ready
        </h2>
        <p className="mt-2 text-sm" style={{ color: "var(--muted)" }}>
          Everything you kept is now part of your professional profile.
        </p>
        <Button className="mt-6" asChild>
          <a href="/profile">View my profile</a>
        </Button>
      </div>
    );
  }

  if (state.name === "uploading" || state.name === "extracting") {
    return (
      <div className="rounded-lg border p-8 text-center" style={{ borderColor: "var(--border)" }}>
        <p className="text-sm">
          {state.name === "uploading" ? "Uploading" : "Reading"} {state.filename}…
        </p>
        <p className="mt-2 text-sm" style={{ color: "var(--muted)" }}>
          {state.name === "extracting"
            ? "Working out the structure of your CV. This takes a few seconds."
            : "Almost there."}
        </p>
      </div>
    );
  }

  return (
    <div>
      {state.name === "failed" && (
        <div
          role="alert"
          className="mb-6 rounded-md py-3 pr-4 text-sm"
          style={{
            borderLeft: "2px solid var(--color-failure)",
            paddingLeft: "0.75rem",
            color: "var(--foreground)",
          }}
        >
          <p className="font-medium">That CV could not be read</p>
          <p className="mt-1" style={{ color: "var(--muted)" }}>
            {state.message}
          </p>
        </div>
      )}

      <label
        className="flex cursor-pointer flex-col items-center rounded-xl border border-dashed p-12 text-center"
        style={{ borderColor: "var(--border-strong)" }}
      >
        <span className="text-base font-medium">Upload your CV</span>
        <span className="mt-2 max-w-sm text-sm" style={{ color: "var(--muted)" }}>
          PDF or DOCX. You will review everything we read from it before any of it becomes part
          of your profile.
        </span>
        <input
          type="file"
          accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          className="sr-only"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void upload(file);
          }}
        />
        <span
          className="mt-6 rounded-md px-4 py-2 text-sm"
          style={{ background: "var(--color-brand-600)", color: "white" }}
        >
          Choose a file
        </span>
      </label>
    </div>
  );
}
