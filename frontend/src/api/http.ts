interface ApiErrorBody {
  error: { code: string; message: string; details: Record<string, unknown> };
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

interface ApiRequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  formData?: FormData;
  headers?: HeadersInit;
  signal?: AbortSignal;
}

const SAFE_METHODS = new Set(["GET"]);
interface Session {
  csrfToken: string;
  hostRoomIds: string[];
  participantRoomIds: string[];
}

let sessionPromise: Promise<Session> | undefined;

function cacheSession(pendingSession: Promise<Session>): Promise<Session> {
  sessionPromise = pendingSession;
  void pendingSession.catch(() => {
    if (sessionPromise === pendingSession) {
      sessionPromise = undefined;
    }
  });
  return pendingSession;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isApiErrorBody(value: unknown): value is ApiErrorBody {
  if (!isRecord(value) || !isRecord(value.error)) {
    return false;
  }

  const { code, message, details } = value.error;
  return (
    typeof code === "string" &&
    code.length > 0 &&
    typeof message === "string" &&
    message.length > 0 &&
    isRecord(details)
  );
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text();
  if (text.length === 0) {
    return undefined;
  }

  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new ApiError(response.status, "INVALID_API_RESPONSE", "The server returned a response Junto could not read.");
  }
}

async function errorFromResponse(response: Response): Promise<ApiError> {
  let payload: unknown;

  try {
    payload = await readJson(response);
  } catch (error) {
    if (error instanceof ApiError) {
      return error;
    }
    throw error;
  }

  if (isApiErrorBody(payload)) {
    return new ApiError(response.status, payload.error.code, payload.error.message, payload.error.details);
  }

  return new ApiError(
    response.status,
    `HTTP_${response.status}`,
    response.statusText || "The request could not be completed.",
  );
}

function apiPath(path: string): string {
  if (!path.startsWith("/api/")) {
    throw new Error(`API paths must be same-origin and begin with /api/: ${path}`);
  }
  return path;
}

async function fetchSession(): Promise<Session> {
  const response = await fetch("/api/session", {
    method: "GET",
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    throw await errorFromResponse(response);
  }

  const payload = await readJson(response);
  if (
    !isRecord(payload) ||
    typeof payload.csrfToken !== "string" ||
    !Array.isArray(payload.hostRoomIds) ||
    !payload.hostRoomIds.every((value) => typeof value === "string") ||
    !Array.isArray(payload.participantRoomIds) ||
    !payload.participantRoomIds.every((value) => typeof value === "string")
  ) {
    throw new ApiError(response.status, "INVALID_SESSION_RESPONSE", "The server returned an invalid session response.");
  }

  return {
    csrfToken: payload.csrfToken,
    hostRoomIds: payload.hostRoomIds,
    participantRoomIds: payload.participantRoomIds,
  };
}

function getSession(options: { refresh?: boolean } = {}): Promise<Session> {
  if (!options.refresh && sessionPromise !== undefined) {
    return sessionPromise;
  }

  return cacheSession(fetchSession());
}

async function refreshSessionAfterCsrfFailure(staleToken: string): Promise<Session> {
  while (true) {
    const observedSession = sessionPromise;
    if (observedSession !== undefined) {
      try {
        const currentSession = await observedSession;
        if (currentSession.csrfToken !== staleToken) {
          return currentSession;
        }
      } catch {
        // A failed session request is replaced below.
      }
      if (sessionPromise !== observedSession) {
        continue;
      }
    }

    return cacheSession(fetchSession());
  }
}

export function invalidateSession(): void {
  sessionPromise = undefined;
}

export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const method = options.method ?? "GET";
  const safeMethod = SAFE_METHODS.has(method);
  const requestPath = apiPath(path);
  if (options.body !== undefined && options.formData !== undefined) {
    throw new Error("An API request cannot contain both JSON and FormData.");
  }

  let body: BodyInit | undefined;
  if (options.formData !== undefined) {
    body = options.formData;
  } else if (options.body !== undefined) {
    body = JSON.stringify(options.body);
  }

  const send = async (session?: Session): Promise<Response> => {
    const headers = new Headers(options.headers);
    headers.set("Accept", "application/json");
    if (options.body !== undefined) {
      headers.set("Content-Type", "application/json");
    }
    if (session !== undefined) {
      headers.set("X-CSRF-Token", session.csrfToken);
    }

    return fetch(requestPath, { method, credentials: "same-origin", headers, body, signal: options.signal });
  };

  let requestSession = safeMethod ? undefined : await getSession();
  let response = await send(requestSession);

  if (!response.ok) {
    const error = await errorFromResponse(response);
    if (!safeMethod && requestSession !== undefined && error.code === "CSRF_INVALID") {
      requestSession = await refreshSessionAfterCsrfFailure(requestSession.csrfToken);
      response = await send(requestSession);
      if (!response.ok) {
        throw await errorFromResponse(response);
      }
    } else {
      throw error;
    }
  }

  if (response.status === 204 || response.status === 205) {
    return undefined as T;
  }

  return (await readJson(response)) as T;
}

export function pathSegment(value: string): string {
  return encodeURIComponent(value);
}
