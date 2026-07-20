import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ActivityHistoryPage } from "../ActivityHistoryPage";

const apiMocks = vi.hoisted(() => ({ deleteRoom: vi.fn(), getActivities: vi.fn() }));

vi.mock("../../../../api", () => ({ api: apiMocks }));
vi.mock("../../../../hooks/useDocumentTitle", () => ({ useDocumentTitle: vi.fn() }));

describe("ActivityHistoryPage", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("lists hosted activities as compact links to their room results", async () => {
    apiMocks.getActivities.mockResolvedValue({
      activities: [
        {
          roomId: "room-published",
          joinCode: "ABC123",
          title: "Dynamic programming review",
          status: "published",
          createdAt: "2026-07-19T10:00:00.000Z",
          groupingPublishedAt: "2026-07-19T10:20:00.000Z",
          participantCount: 20,
          questionCount: 3,
          groupCount: 5,
          generationMode: "coverage_aware",
          fullyCoveredGroupQuestions: 14,
          totalGroupQuestions: 15,
        },
        {
          roomId: "room-draft",
          joinCode: "DEF456",
          title: "Ethics seminar",
          status: "draft",
          createdAt: "2026-07-18T10:00:00.000Z",
          groupingPublishedAt: null,
          participantCount: 0,
          questionCount: 2,
          groupCount: 0,
          generationMode: null,
          fullyCoveredGroupQuestions: null,
          totalGroupQuestions: null,
        },
      ],
    });

    render(
      <MemoryRouter>
        <ActivityHistoryPage />
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Activities" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Dynamic programming review/ })).toHaveAttribute(
      "href",
      "/host/room-published",
    );
    expect(screen.getByText("20 participants · 5 groups")).toBeInTheDocument();
    expect(screen.getByText("14 of 15 fully covered")).toBeInTheDocument();
    expect(screen.getByText("Draft")).toBeInTheDocument();
    expect(screen.queryByText(/browser|expire/i)).not.toBeInTheDocument();
  });

  it("shows a concise empty history without inventing account history", async () => {
    apiMocks.getActivities.mockResolvedValue({ activities: [] });

    render(
      <MemoryRouter>
        <ActivityHistoryPage />
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "No activities yet." })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Create activity" })).toHaveLength(2);
  });

  it("requires the invite code before manually deleting an activity", async () => {
    const user = userEvent.setup();
    apiMocks.getActivities.mockResolvedValue({
      activities: [
        {
          roomId: "room-published",
          joinCode: "ABC123",
          title: "Dynamic programming review",
          status: "published",
          createdAt: "2026-07-19T10:00:00.000Z",
          groupingPublishedAt: "2026-07-19T10:20:00.000Z",
          participantCount: 20,
          questionCount: 3,
          groupCount: 5,
          generationMode: "coverage_aware",
          fullyCoveredGroupQuestions: 14,
          totalGroupQuestions: 15,
        },
      ],
    });
    apiMocks.deleteRoom.mockResolvedValue(undefined);

    render(
      <MemoryRouter>
        <ActivityHistoryPage />
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole("button", { name: "Delete Dynamic programming review" }));
    const deleteButton = screen.getByRole("button", { name: "Delete activity" });
    expect(deleteButton).toBeDisabled();
    await user.type(screen.getByLabelText(/Deletion password/), "abc123");
    expect(deleteButton).toBeEnabled();
    await user.click(deleteButton);

    expect(apiMocks.deleteRoom).toHaveBeenCalledWith("room-published", "ABC123");
    expect(await screen.findByRole("heading", { name: "No activities yet." })).toBeInTheDocument();
  });

  it("can retry a failed history request", async () => {
    const user = userEvent.setup();
    apiMocks.getActivities
      .mockRejectedValueOnce(new Error("Activities could not load."))
      .mockResolvedValueOnce({ activities: [] });

    render(
      <MemoryRouter>
        <ActivityHistoryPage />
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "No activities yet." })).toBeInTheDocument();
    expect(apiMocks.getActivities).toHaveBeenCalledTimes(2);
  });
});
