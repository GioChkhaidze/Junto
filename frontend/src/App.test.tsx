import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { App, RouteLoading } from "./App";
import styles from "./App.module.css";
import shellStyles from "./components/layout/AppShell.module.css";

function renderLoading(pathname: string) {
  render(
    <MemoryRouter initialEntries={[pathname]}>
      <RouteLoading />
    </MemoryRouter>,
  );
}

afterEach(cleanup);

describe("RouteLoading", () => {
  it("uses the green host shell while a host room route loads", () => {
    renderLoading("/host/room-1");

    expect(screen.getByRole("banner")).toHaveClass(shellStyles.darkHeader!);
    expect(screen.getByRole("status", { name: "Loading page" }).parentElement).toHaveClass(styles.hostLoadingPanel!);
    expect(screen.getByRole("status", { name: "Loading page" }).children).toHaveLength(8);
  });

  it("renders the landing page without a route skeleton", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Loading page" })).not.toBeInTheDocument();
  });

  it("matches the authoring header context and action", () => {
    renderLoading("/create");

    expect(screen.getByRole("banner")).toHaveClass(shellStyles.darkHeader!);
    expect(screen.getByText("Create an activity")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Activities" })).toHaveAttribute("href", "/activities");
  });

  it("keeps the white participant shell while a participant room route loads", () => {
    renderLoading("/room/room-1");

    expect(screen.getByRole("banner")).not.toHaveClass(shellStyles.darkHeader!);
  });
});
