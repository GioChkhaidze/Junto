import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { HomePage } from "../HomePage";

function JoinDestination() {
  const { joinCode } = useParams<{ joinCode: string }>();
  return <h1>Joining {joinCode}</h1>;
}

describe("HomePage", () => {
  it("normalizes an invite code and navigates to its join page", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/join/:joinCode" element={<JoinDestination />} />
        </Routes>
      </MemoryRouter>,
    );

    const codeInput = screen.getByRole("textbox", { name: "Invite code" });
    const continueButton = screen.getByRole("button", { name: "Continue" });
    expect(continueButton).toBeDisabled();

    await user.type(codeInput, " j7-km 4p! ");

    expect(codeInput).toHaveValue("J7KM4P");
    expect(continueButton).toBeEnabled();

    await user.click(continueButton);

    expect(
      screen.getByRole("heading", { level: 1, name: "Joining J7KM4P" }),
    ).toBeInTheDocument();
  });
});
