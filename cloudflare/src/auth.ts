const BASIC_SCHEME = "basic";
const encoder = new TextEncoder();

export interface JudgeCredentials {
  username: string;
  password: string;
}

function decodeBasicCredentials(header: string | null): JudgeCredentials | null {
  if (header === null) {
    return null;
  }

  const parts = header.trim().split(/\s+/u);
  if (parts.length !== 2 || parts[0]?.toLowerCase() !== BASIC_SCHEME || !parts[1]) {
    return null;
  }

  try {
    const binary = atob(parts[1]);
    const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
    const decoded = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes);
    const separator = decoded.indexOf(":");
    if (separator < 0) {
      return null;
    }
    return { username: decoded.slice(0, separator), password: decoded.slice(separator + 1) };
  } catch {
    return null;
  }
}

async function digestCredentials(credentials: JudgeCredentials): Promise<Uint8Array> {
  const payload = `${credentials.username}\u0000${credentials.password}`;
  return new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(payload)));
}

function equalBytes(left: Uint8Array, right: Uint8Array): boolean {
  let difference = left.length ^ right.length;
  const length = Math.max(left.length, right.length);
  for (let index = 0; index < length; index += 1) {
    difference |= (left[index] ?? 0) ^ (right[index] ?? 0);
  }
  return difference === 0;
}

export async function isJudgeAuthorized(
  authorizationHeader: string | null,
  expected: JudgeCredentials,
): Promise<boolean> {
  const presented = decodeBasicCredentials(authorizationHeader);
  if (presented === null) {
    return false;
  }

  const [presentedDigest, expectedDigest] = await Promise.all([
    digestCredentials(presented),
    digestCredentials(expected),
  ]);
  return equalBytes(presentedDigest, expectedDigest);
}

export function unauthorizedResponse(): Response {
  return new Response("Authentication required.", {
    status: 401,
    headers: {
      "Cache-Control": "private, no-store",
      "Content-Type": "text/plain; charset=utf-8",
      "WWW-Authenticate": 'Basic realm="Junto hackathon demo", charset="UTF-8"',
      "X-Robots-Tag": "noindex, nofollow, noarchive",
    },
  });
}
