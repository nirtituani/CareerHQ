import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { EditModeProvider } from "@/components/profile/edit-mode";
import { ProfileMenu } from "@/components/profile/profile-menu";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

function open() {
  return render(
    <EditModeProvider>
      <ProfileMenu total={61} />
    </EditModeProvider>,
  );
}

describe("ProfileMenu", () => {
  it("keeps the actions behind one control", () => {
    open();

    // Nothing is on the page until asked for: three buttons across the header
    // gave "clear my profile" the same weight as "edit", despite one being
    // reversible and the other not.
    expect(screen.queryByText(/clear my profile/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /profile actions/i })).toBeInTheDocument();
  });

  it("offers edit, import and clear", async () => {
    open();
    await userEvent.click(screen.getByRole("button", { name: /profile actions/i }));

    expect(screen.getByText(/edit profile/i)).toBeInTheDocument();
    expect(screen.getByText(/import another cv/i)).toBeInTheDocument();
    expect(screen.getByText(/clear my profile/i)).toBeInTheDocument();
  });

  it("names the total and demands a typed word before clearing", async () => {
    open();
    await userEvent.click(screen.getByRole("button", { name: /profile actions/i }));
    await userEvent.click(screen.getByText(/clear my profile/i));

    // "Clear everything" and "delete 61 things" are the same action described at
    // two levels of honesty, so the confirmation uses the second.
    expect(screen.getByRole("alertdialog")).toHaveTextContent(/61 items/);

    const confirm = screen.getByRole("button", { name: /^clear my profile$/i });
    expect(confirm).toBeDisabled();

    await userEvent.type(screen.getByRole("textbox"), "clear");
    expect(confirm).toBeEnabled();
  });

  it("toggles edit mode from the menu", async () => {
    open();
    await userEvent.click(screen.getByRole("button", { name: /profile actions/i }));
    await userEvent.click(screen.getByText(/edit profile/i));

    await userEvent.click(screen.getByRole("button", { name: /profile actions/i }));
    expect(screen.getByText(/done editing/i)).toBeInTheDocument();
  });
});
