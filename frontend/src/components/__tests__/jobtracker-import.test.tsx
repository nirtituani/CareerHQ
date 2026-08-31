import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JobtrackerImport } from "@/components/applications/jobtracker-import";
import { ApiError } from "@/lib/api";
import type { JobtrackerImportReport } from "@/lib/api";

/**
 * The JobTracker import screen (T083), over the endpoint T084 already exercised
 * in production.
 *
 * **What these tests are for.** The endpoint reports four outcomes and two of
 * the pairs are one careless render away from lying:
 *
 * * `skipped` is a **success**. Re-running an import is safe by design, and the
 *   route's own docstring says a person unsure whether their upload worked
 *   should be able to press it again. Rendering it as a failure would make the
 *   correct behaviour look broken.
 * * `notices` describe rows that **did** import. They are carried separately
 *   from `rejected` because conflating them "would send someone looking for
 *   history that is already there".
 *
 * Neither is visible by looking at a screen that renders one plausible number,
 * which is exactly the class of bug this project keeps shipping.
 */

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, importJobtracker: vi.fn() };
});

const mocked = vi.mocked(await import("@/lib/api"));

function report(overrides: Partial<JobtrackerImportReport> = {}): JobtrackerImportReport {
  return { imported: 96, skipped: 0, rejected: [], notices: [], ...overrides };
}

/** A CSV file of a given size, so the size guard can be exercised honestly. */
function csv(name = "jobtracker.csv", bytes = 1024): File {
  return new File(["x".repeat(bytes)], name, { type: "text/csv" });
}

async function upload(file: File) {
  render(<JobtrackerImport />);
  const input = screen.getByLabelText(/csv|file|upload/i);
  await userEvent.upload(input, file);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("the upload step", () => {
  it("states plainly what to upload", () => {
    render(<JobtrackerImport />);
    expect(screen.getByText(/upload your jobtracker csv export/i)).toBeInTheDocument();
  });

  it("shows an indeterminate working state while the import runs", async () => {
    // The endpoint is synchronous and has no progress API, so this can only be
    // indeterminate. It must still be distinguishable from idle: a 96-row
    // import is a long POST, and a screen that looks idle invites a second
    // upload of the same file.
    let release: (value: JobtrackerImportReport) => void = () => {};
    mocked.importJobtracker.mockReturnValue(
      new Promise<JobtrackerImportReport>((resolve) => {
        release = resolve;
      }),
    );

    await upload(csv());
    expect(await screen.findByTestId("importing")).toBeInTheDocument();

    release(report());
    await waitFor(() => expect(screen.queryByTestId("importing")).toBeNull());
  });

  it("refuses a file over 10 MB without calling the API", async () => {
    // Mirrors MAX_UPLOAD_BYTES. The server still guards this; the client check
    // exists so a large file fails at once instead of after a long upload.
    await upload(csv("huge.csv", 10 * 1024 * 1024 + 1));

    expect(await screen.findByRole("alert")).toHaveTextContent(/10 MB/i);
    expect(mocked.importJobtracker).not.toHaveBeenCalled();
  });
});

describe("the four outcomes", () => {
  it("reports what was imported", async () => {
    mocked.importJobtracker.mockResolvedValue(report({ imported: 96 }));
    await upload(csv());

    const imported = await screen.findByTestId("outcome-imported");
    expect(imported).toHaveTextContent("96");
  });

  it("presents skipped as a success, not as a failure", async () => {
    // The whole point. A re-import reports everything as skipped and nothing
    // went wrong; this is the render that would most plausibly say otherwise.
    mocked.importJobtracker.mockResolvedValue(report({ imported: 0, skipped: 96 }));
    await upload(csv());

    const skipped = await screen.findByTestId("outcome-skipped");
    expect(skipped).toHaveTextContent("96");
    expect(skipped).toHaveTextContent(/already/i);
    expect(skipped.textContent).not.toMatch(/fail|error|reject|problem/i);

    // And the screen as a whole must not announce a failure.
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("says notices were imported, and keeps them apart from rejections", async () => {
    mocked.importJobtracker.mockResolvedValue(
      report({
        imported: 96,
        notices: [{ source_id: "abc-1", message: "Unrecognised status 'Ghosted'." }],
        rejected: [{ source_id: "def-2", reason: "No company name." }],
      }),
    );
    await upload(csv());

    const notices = await screen.findByTestId("outcome-notices");
    const rejected = await screen.findByTestId("outcome-rejected");

    // The reason they are separate: a notice row IS in the database.
    expect(notices).toHaveTextContent(/imported/i);
    expect(notices).toHaveTextContent("abc-1");
    expect(notices).toHaveTextContent("Unrecognised status 'Ghosted'.");

    // A rejection is not, and must say so with its reason.
    expect(rejected).toHaveTextContent("def-2");
    expect(rejected).toHaveTextContent("No company name.");

    // Neither block may contain the other's row — the conflation this guards.
    expect(notices.textContent).not.toContain("def-2");
    expect(rejected.textContent).not.toContain("abc-1");
  });

  it("does not render empty outcome blocks", async () => {
    // A clean import showing "0 rejected" invites a hunt for a problem that
    // does not exist.
    mocked.importJobtracker.mockResolvedValue(report({ imported: 96 }));
    await upload(csv());

    await screen.findByTestId("outcome-imported");
    expect(screen.queryByTestId("outcome-rejected")).toBeNull();
    expect(screen.queryByTestId("outcome-notices")).toBeNull();
  });
});

describe("failures", () => {
  it("shows the server's reason when the file is not an export", async () => {
    // 400 carries our own message naming the missing columns, and it is the
    // only thing that tells a person what is wrong with their file.
    mocked.importJobtracker.mockRejectedValue(
      new ApiError(400, "That file is missing the columns: company, title."),
    );
    await upload(csv());

    expect(await screen.findByRole("alert")).toHaveTextContent(/missing the columns/i);
  });

  it("explains a concurrent import rather than reporting a generic failure", async () => {
    mocked.importJobtracker.mockRejectedValue(
      new ApiError(409, "An import of this file is already running. Try again in a moment."),
    );
    await upload(csv());

    expect(await screen.findByRole("alert")).toHaveTextContent(/already running/i);
  });

  it("surfaces the server's size refusal too", async () => {
    // The client pre-check is a convenience, not the guard. If the server
    // refuses, the person still has to be told why.
    mocked.importJobtracker.mockRejectedValue(
      new ApiError(413, "That file is larger than 10 MB."),
    );
    await upload(csv());

    expect(await screen.findByRole("alert")).toHaveTextContent(/10 MB/i);
  });

  it("does not show a raw failure for an unexpected error", async () => {
    // A 500's detail is the operator's, not the browser's.
    mocked.importJobtracker.mockRejectedValue(new Error("psycopg.OperationalError: host=10.0.0.4"));
    await upload(csv());

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).not.toMatch(/psycopg|10\.0\.0\.4/);
    expect(alert).toHaveTextContent(/could not|went wrong/i);
  });

  it("lets a failed upload be retried", async () => {
    mocked.importJobtracker.mockRejectedValueOnce(new ApiError(409, "Already running."));
    await upload(csv());
    await screen.findByRole("alert");

    mocked.importJobtracker.mockResolvedValue(report({ imported: 5 }));
    await userEvent.upload(screen.getByLabelText(/csv|file|upload/i), csv());

    expect(await screen.findByTestId("outcome-imported")).toHaveTextContent("5");
  });
});
