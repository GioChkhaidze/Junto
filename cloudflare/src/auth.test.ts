import assert from "node:assert/strict";
import test from "node:test";

import { isJudgeAuthorized, unauthorizedResponse } from "./auth.ts";

const expected = { username: "judges", password: "correct horse battery staple" };

function basic(username: string, password: string): string {
  return `Basic ${Buffer.from(`${username}:${password}`, "utf8").toString("base64")}`;
}

test("accepts the configured credentials", async () => {
  assert.equal(await isJudgeAuthorized(basic(expected.username, expected.password), expected), true);
});

test("rejects missing, malformed, and incorrect credentials", async () => {
  assert.equal(await isJudgeAuthorized(null, expected), false);
  assert.equal(await isJudgeAuthorized("Bearer token", expected), false);
  assert.equal(await isJudgeAuthorized("Basic !!!", expected), false);
  assert.equal(await isJudgeAuthorized(basic(expected.username, "incorrect"), expected), false);
});

test("returns a private Basic Auth challenge", () => {
  const response = unauthorizedResponse();
  assert.equal(response.status, 401);
  assert.match(response.headers.get("WWW-Authenticate") ?? "", /^Basic /u);
  assert.equal(response.headers.get("Cache-Control"), "private, no-store");
  assert.equal(response.headers.get("X-Robots-Tag"), "noindex, nofollow, noarchive");
});
