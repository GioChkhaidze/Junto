import { afterEach, describe, expect, it, vi } from "vitest";

import { apiRequest, invalidateSession } from "../http";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function sessionResponse(csrfToken: string): Response {
  return jsonResponse(200, { csrfToken, hostRoomIds: [], participantRoomIds: [] });
}

function csrfError(): Response {
  return jsonResponse(403, {
    error: {
      code: "CSRF_INVALID",
      message: "The request could not be verified. Refresh the page and try again.",
      details: {},
    },
  });
}

afterEach(() => {
  invalidateSession();
  vi.unstubAllGlobals();
});

describe("apiRequest CSRF recovery", () => {
  it("refreshes the session and retries one rejected mutation", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(sessionResponse("stale-token"))
      .mockResolvedValueOnce(csrfError())
      .mockResolvedValueOnce(sessionResponse("fresh-token"))
      .mockResolvedValueOnce(jsonResponse(200, { accepted: true }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      apiRequest<{ accepted: boolean }>("/api/authoring/suggestions", { method: "POST", body: { target: "question" } }),
    ).resolves.toEqual({ accepted: true });

    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(new Headers(fetchMock.mock.calls[1]?.[1]?.headers).get("X-CSRF-Token")).toBe("stale-token");
    expect(new Headers(fetchMock.mock.calls[3]?.[1]?.headers).get("X-CSRF-Token")).toBe("fresh-token");
  });

  it("shares one refreshed session across concurrent rejected mutations", async () => {
    let sessionRequests = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      if (String(input) === "/api/session") {
        sessionRequests += 1;
        return sessionResponse(sessionRequests === 1 ? "stale-token" : "fresh-token");
      }
      const csrfToken = new Headers(init?.headers).get("X-CSRF-Token");
      return csrfToken === "stale-token" ? csrfError() : jsonResponse(200, { accepted: true });
    });
    vi.stubGlobal("fetch", fetchMock);

    await Promise.all([
      apiRequest("/api/authoring/suggestions", { method: "POST", body: { target: "question" } }),
      apiRequest("/api/authoring/suggestions", { method: "POST", body: { target: "coverage" } }),
    ]);

    expect(sessionRequests).toBe(2);
  });

  it("does not retry a different forbidden response", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(sessionResponse("valid-token"))
      .mockResolvedValueOnce(
        jsonResponse(403, {
          error: { code: "ORIGIN_NOT_TRUSTED", message: "This request origin is not allowed.", details: {} },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiRequest("/api/authoring/suggestions", { method: "POST", body: {} })).rejects.toMatchObject({
      code: "ORIGIN_NOT_TRUSTED",
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
