# Operations guide

## Deployment boundary

This guide supports one education-track demonstration deployment: one FastAPI process, one PostgreSQL database, one
configured language-model provider, and the in-process CP-SAT solver. It is not a claim of institutional production
readiness, compliance certification, durable job execution, multi-region availability, or proven learning impact.

The runtime deliberately has one web process. Analysis is currently an in-process task; running multiple web workers
could claim or strand work in ways this deployment has not been designed to coordinate. A durable queue and worker are a
later scaling decision, not part of this release.

```text
HTTPS reverse proxy
        |
        v
one Junto container  ------>  OpenAI API
        |
        v
PostgreSQL
```

The image builds the Vite assets in a Node stage, installs the fully pinned `backend/requirements.runtime.lock` closure
in a second stage, and copies only runtime inputs into a non-root Python image. Node is not present in the final image.
The application filesystem is read-only except for a bounded `/tmp` mount used while parsing uploads.

## Required operator decisions

Before exposing Junto outside a development machine, decide and record:

1. the HTTPS hostname and the reverse proxy allowed to send forwarded headers;
2. the OpenAI project and its data-handling settings;
3. who can operate the database and read encrypted backups;
4. the room-retention period, which defaults to 24 hours for a demonstration;
5. who owns the demo during a provider failure or interrupted analysis;
6. whether creators have seen the disclosure in [Authoring-assistance disclosure](#authoring-assistance-disclosure);
7. whether participants have seen the disclosure in [Participant disclosure](#participant-disclosure).

Do not deploy with a shared example secret, a public database port, HTTP cookies, an unreviewed fixture, or provider
logging that captures request bodies.

## Configuration

Secrets belong in the deployment platform's secret store. A local `.env` may be used for a private workstation
demonstration, but it is ignored by Git and must never be committed.

- `APP_ENV` — `production`. Enables strict production validation.
- `DATABASE_URL` — required. SQLAlchemy PostgreSQL URL using the `psycopg` driver.
- `SESSION_SECRET` — required, with at least 32 random characters. Signs anonymous room capabilities. Rotate it only
  with an accepted logout of every browser session.
- `TRUSTED_ORIGINS` — exact HTTPS origin list. Rejects browser requests from outside the deployment. Do not use `*`.
- `OPENAI_API_KEY` — required for AI authoring or live OpenAI analysis. This credential never reaches the browser or
  database. In development it enables authoring with `placeholder`, `recorded`, or `openrouter` analysis.
- `ANALYSIS_ENGINE` — `openai` in production. Selects analysis but does not gate AI-assisted authoring. Production
  rejects `recorded` and `placeholder`.
- `OPENAI_MODEL` — `gpt-5.6-sol`. The explicit structured-output model for authoring assistance and semantic analysis.
  Review changes before deployment.
- `OPENAI_REASONING_EFFORT` — `low`. Bounded reasoning for authoring assistance and the live compiler.
- `OPENROUTER_API_KEY` — unset. Enables development-only OpenRouter semantic and synthetic calls.
- `OPENROUTER_MODELS` — two pinned model IDs. The first handles semantic analysis; the pool rotates synthetic batches.
- `PORT` — `8000`. Internal HTTP port.
- `LOG_LEVEL` — `info`. Application log level; default Uvicorn access logs are disabled.
- `FORWARDED_ALLOW_IPS` — `127.0.0.1`. Reverse proxies trusted to supply forwarded client metadata.
- `POSTGRES_PASSWORD` — required by local Compose. Used only to construct its database connection.
- `TEST_DATABASE_URL` — unset. Optional disposable PostgreSQL connection for integration tests.

Cookie behavior, provider concurrency, synthetic cohort shape, solver limits, retries, retention, and request-rate
limits are typed application defaults rather than deployment variables. Change them in reviewed code with matching tests
and documentation. Keep the documented classroom ceiling at 60 participants unless a new load run establishes another
supported limit.

Generate independent secrets rather than reusing a database password:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Clean container release

The application never runs migrations during web startup. This prevents multiple web instances from racing schema
changes and keeps a failed migration separate from a failed health check.

From a clean checkout with Docker Engine and Compose v2:

```powershell
docker compose build --pull
docker compose up -d postgres
docker compose --profile release run --rm release
docker compose up -d app
docker compose ps
```

The release container executes exactly:

```text
python -m alembic -c backend/alembic.ini upgrade head
```

The web container then executes one Uvicorn worker through `backend/scripts/start.py`. It does not run Alembic and does
not fall back to the in-memory repository in production.

The Compose port binds to loopback. Put an HTTPS reverse proxy in front of it and forward only the configured hostname.
Cookie security derives from `APP_ENV`: production always uses secure cookies, while a local development browser can use
loopback HTTP.

### Release order

1. Take and verify a database backup for a migration that changes stored data.
2. Build the immutable image once.
3. Start or verify PostgreSQL.
4. Run the one-shot release command and stop on any non-zero result.
5. Replace the application with the same image digest used for the release command.
6. Wait for readiness, then run the smoke flow.
7. Retain the prior image until the smoke flow completes.

Prefer a forward repair migration over an ad hoc downgrade. Use `alembic downgrade` only when that revision's downgrade
was exercised against a restored copy of representative data and the old application is compatible with the resulting
schema.

## Health and readiness

- `GET /api/health`
  - Means the HTTP process can serve a small response.
  - Must not query PostgreSQL or call an external provider.
- `GET /api/ready`
  - Means required configuration is valid and PostgreSQL accepts a bounded probe.
  - Must not call OpenAI, run the solver, migrate, or modify data.

The container health check uses readiness. A provider outage does not remove the application from service; it causes new
analyses to fail safely while rooms, answers, and already-published groups remain readable.

Useful checks:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-RestMethod http://127.0.0.1:8000/api/ready
docker compose logs --since 5m app
```

The last command must show structured operational events, not request bodies. Do not enable generic reverse-proxy body
capture while diagnosing the application.

## Network, request, and abuse controls

- Terminate TLS at a maintained reverse proxy or platform load balancer.
- Redirect HTTP to HTTPS before a browser can receive a room cookie.
- Preserve `HttpOnly`, `Secure`, and `SameSite=Lax` on the signed room-session cookie.
- Allow only the exact public origin and host. The browser uses same-origin API requests.
- Keep PostgreSQL on a private network; the Compose database has no host port.
- Cap the incoming body before multipart parsing. The proxy limit must be no larger than the application upload limit
  plus multipart overhead.
- Keep PDF page, DOCX expanded-size, extracted-character, question-count, answer-length, participant, and per-room
  material bounds enabled.
- Apply bounded per-source and per-room rate limits to room creation, authoring suggestions, join, answer mutation, and
  analysis/retry commands. Status polling has a separate classroom-sized allowance.
- Return `429` with a retry hint; never respond to excess traffic by starting extra provider calls.
- Keep one active analysis claim per frozen room. Repeated commands return the existing state.

Rate limiting is abuse resistance, not identity. Junto remains anonymous and room-scoped.

## Privacy-safe observability

Default Uvicorn access logs are disabled because a URL can contain a join code. Application logs may contain:

- timestamp, severity, event name, request correlation ID;
- route template rather than raw URL;
- HTTP status and bounded duration;
- analysis stage, provider/solver duration, authoring-provider duration, attempt number, and sanitized outcome;
- non-reversible or deployment-keyed room correlation if incident analysis truly needs it.

Application logs, traces, metrics labels, and error-reporting breadcrumbs must not contain:

- cookies, CSRF values, join codes, API keys, or database credentials;
- participant names, answer text, question text, extracted reference text, or original upload bytes;
- provider prompts or structured provider responses;
- raw room or participant IDs in third-party telemetry;
- model chain-of-thought;
- SQL parameter values from room content.

Measure provider and solver timing around the call boundary. Record model identifier, schema version, solver status, and
time-limit outcome as bounded metadata. Provider refusals, timeouts, invalid structured output, infeasibility, and
unknown/time-limited solver results are distinct outcomes; their public messages remain concise and sanitized.

## Stored data and retention

Room data includes the room configuration, host-authored coverage units, participant display names, answers, extracted
reference text, the frozen response snapshot, validated semantic artifact, and published grouping artifact. Uploaded
source-file bytes are not retained after bounded extraction. The provider response is accepted only after schema
validation; provider reasoning is neither requested for storage nor persisted.

For the demonstration deployment:

- expire draft, lobby, published, and failed rooms 24 hours after their last terminal or editing activity;
- do not delete an actively answering room before its deadline and recovery grace period;
- treat a room-level delete or expiry as a cascade over questions, materials, participants, responses, semantic
  artifacts, grouping artifacts, and capability records;
- keep deletion idempotent and audit only the event/time, never deleted content;
- ensure backup expiry is no longer than the approved backup-retention period.

Changing the room-retention policy is a privacy decision. Record the reason and update participant copy before extending
it. A database backup can temporarily outlive an online room; access must be restricted and its destruction schedule
documented.

## Authoring-assistance disclosure

Before a creator invokes AI-assisted drafting, show concise copy equivalent to:

> When you request a suggestion, Junto sends the extracted or pasted reference text, activity title, and complete
> current question-and-coverage draft to the configured OpenAI model. Original upload bytes are not sent. Review and
> edit the result before creating the activity.

The action must remain explicit and limited to the requested question or coverage target. A suggestion must not persist
authoring data, open a room, or appear in a participant surface by itself. Operators should treat host-provided
reference text as potentially sensitive and should not enable request-body capture in proxies, logs, traces, or error
reporting.

## Participant disclosure

Before the join form accepts a name in a live-provider deployment, show concise copy equivalent to:

> This room stores the name you enter and your answers for the room's limited retention period. Your question and answer
> text may be sent to OpenAI to identify which ideas are represented; Junto does not grade you or create an account. Ask
> the host before continuing if you do not want your response processed this way.

The host must be able to state the configured retention period and identify an alternative activity for someone who
cannot participate under that disclosure. Do not describe the model classification as certain, a grade, or evidence of
understanding.

## Backup and restore

For Compose, create a custom-format logical backup in a restricted location:

```powershell
docker compose exec -T postgres pg_dump --username junto --dbname junto --format custom --no-owner --no-acl > junto.dump
```

Encrypt the file at rest, restrict it to named operators, and record its expiry. Do not upload it to consumer file
sharing or attach it to an issue.

Test restoration into an isolated database rather than overwriting the live database:

1. create an empty isolated PostgreSQL database at the same major version;
2. restore with `pg_restore --no-owner --no-acl`;
3. point a disposable application container at it;
4. verify Alembic head, readiness, one pre-existing room projection, and cascading deletion;
5. destroy the isolated database and test credentials.

A backup is not considered usable until this restore drill succeeds.

## Interrupted-analysis recovery

The database stores the frozen response snapshot separately from validated semantic and grouping artifacts. Publication
is atomic: a group result is visible only after both compiler and optimizer complete and the room changes to `published`
in the same commit.

On startup or a bounded maintenance pass, an `analyzing` room older than the typed stale-analysis threshold is changed
to `failed` with a sanitized interruption reason. Partial artifacts remain non-public and are overwritten by a bounded
host retry using the same frozen snapshot. The retry must claim one new attempt atomically; it must not duplicate
participants or publish an artifact from an older attempt.

Recovery drill:

1. create a fixture and stop the app after analysis is claimed but before publication;
2. restart the same image and database;
3. verify the room is never shown as published with a partial result;
4. after the stale window, verify it becomes failed with no provider content in the public error;
5. invoke one host retry and verify exactly one final publication;
6. compare group membership and diagnostics to the persisted attempt identifier.

If this drill fails, do not run a live-provider demonstration. A separate durable worker is required before horizontal
web scaling or guaranteed recovery across deploys.

## Classroom fixture and load check

`backend/scripts/load_demo.py` creates the reviewed programming-and-philosophy fixture through the normal API, joins
bounded room-scoped sessions, saves complementary answers, and submits them. It refuses non-loopback URLs and never
inserts database rows directly.

With a local HTTP-only test configuration:

```powershell
backend\.venv\Scripts\python.exe backend\scripts\load_demo.py --participants 12
```

Exercise the documented 60-participant polling envelope after a successful analysis:

```powershell
backend\.venv\Scripts\python.exe backend\scripts\load_demo.py --participants 60 --poll-rounds 3 --wait-seconds 300
```

The command reports only IDs/codes needed to locate the fixture, terminal state, and aggregate latency. It does not
print names, answers, prompts, cookies, or provider output. Record the result, image digest, model, solver time limit,
database size, and machine shape. The check is a demo envelope, not a general capacity benchmark.

## Failure drills

Before the event, verify each of these against a disposable room:

- **Wrong or missing OpenAI key:** analysis fails with a sanitized retryable/non-retryable distinction; no groups
  appear.
- **Provider timeout or refusal:** the bounded attempt ends; no partial semantic artifact is published.
- **Invalid structured output:** one bounded repair is allowed; answer text does not enter logs.
- **Solver infeasible:** the host receives honest capacity/coverage diagnostics, not an invented result.
- **Solver time limit or unknown status:** result labels do not claim optimality.
- **App restart during answers:** saved answers and the server deadline survive.
- **App restart during analysis:** stale recovery follows the procedure above.
- **Database unavailable:** readiness fails; liveness remains useful; no in-memory fallback starts.
- **Oversized upload:** the proxy or application rejects it before unbounded extraction.
- **Repeated join or analysis requests:** rate limiting or idempotent state prevents resource multiplication.

## Release checklist

- [ ] Image was built from the reviewed commit and its digest recorded.
- [ ] Migration succeeded as a separate release operation.
- [ ] HTTPS, secure cookies, exact origins/hosts, and forwarded-proxy allowlist are active.
- [ ] Database is private and the current backup passed a restore drill.
- [ ] Provider project, model, timeout, concurrency, and privacy settings were reviewed.
- [ ] Retention and cascading deletion were tested.
- [ ] Participant disclosure is visible before a name or answer is submitted.
- [ ] Health/readiness and privacy-safe logs were inspected.
- [ ] Recorded and live fixture results were reviewed without claiming semantic certainty.
- [ ] Accessibility, narrow viewport, failure, restart, and 60-participant checks passed.
- [ ] A named operator owns the stop/retry decision during the demonstration.
