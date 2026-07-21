import { Container } from "@cloudflare/containers";
import { env } from "cloudflare:workers";

import { isJudgeAuthorized, unauthorizedResponse } from "./auth";

const CONTAINER_INSTANCE = "primary";

export class JuntoContainer extends Container {
  defaultPort = 8000;
  requiredPorts = [8000];
  pingEndpoint = "api/ready";
  sleepAfter = "15m";
  envVars = {
    ANALYSIS_ENGINE: "openai",
    APP_ENV: "production",
    DATABASE_URL: env.DATABASE_URL,
    FORWARDED_ALLOW_IPS: "*",
    LOG_LEVEL: "info",
    OPENAI_API_KEY: env.OPENAI_API_KEY,
    OPENAI_MODEL: "gpt-5.6-luna",
    OPENAI_REASONING_EFFORT: "high",
    OPENROUTER_API_KEY: env.OPENROUTER_API_KEY,
    OPENROUTER_MODEL: "google/gemini-2.5-flash",
    PORT: "8000",
    SESSION_SECRET: env.SESSION_SECRET,
    SYNTHETIC_CLASSROOM_ENABLED: "true",
    SYNTHETIC_MAX_COHORT_SIZE: "12",
    TRUSTED_ORIGINS: env.TRUSTED_ORIGINS,
  };
}

function protectedResponse(response: Response): Response {
  const headers = new Headers(response.headers);
  headers.set("Cache-Control", "private, no-store");
  headers.set("X-Robots-Tag", "noindex, nofollow, noarchive");
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
}

function unavailableResponse(): Response {
  return new Response("Junto is starting. Please retry in a moment.", {
    status: 503,
    headers: {
      "Cache-Control": "private, no-store",
      "Content-Type": "text/plain; charset=utf-8",
      "Retry-After": "10",
      "X-Robots-Tag": "noindex, nofollow, noarchive",
    },
  });
}

export default {
  async fetch(request: Request, workerEnv: Env): Promise<Response> {
    const authorized = await isJudgeAuthorized(request.headers.get("Authorization"), {
      username: workerEnv.JUDGE_USERNAME,
      password: workerEnv.JUDGE_PASSWORD,
    });
    if (!authorized) {
      return unauthorizedResponse();
    }

    const upstreamRequest = new Request(request);
    upstreamRequest.headers.delete("Authorization");

    try {
      const container = workerEnv.JUNTO_CONTAINER.getByName(CONTAINER_INSTANCE);
      return protectedResponse(await container.fetch(upstreamRequest));
    } catch (error: unknown) {
      console.error(
        JSON.stringify({
          event: "container_request_failed",
          message: error instanceof Error ? error.message : "unknown container error",
        }),
      );
      return unavailableResponse();
    }
  },
} satisfies ExportedHandler<Env>;
