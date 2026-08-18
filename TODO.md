# Production-readiness backlog

Assessment: ClearTerms is a solid MVP/internal beta, but is not ready for a
public launch. Priorities below are ordered by launch risk. Items marked DONE
remain as context for controls already implemented.

## P0 — public-launch blockers (security and privacy)

1. **Make storage and attachments private.**
   - `createbucket` makes `clearterms-media` anonymously downloadable. This
     exposes every object directly, including direct-message attachments.
   - `GET /forum/attachments/{id}` authorizes only that the caller is logged
     in; it does not verify ownership, forum visibility, or participation in
     the conversation containing the attachment. Sequential IDs are enumerable.
   - Make the bucket private, restrict MinIO/S3 to the backend, and issue
     short-lived URLs only after object-level authorization. Add integration
     tests for cross-user and cross-conversation attachment access.

2. **Put the public app behind TLS and isolate internal services.**
   - Compose currently publishes PostgreSQL (`5432`), MinIO API/console
     (`9000`/`9001`), Ollama (`11434`), and the backend (`8000`) on host
     interfaces. Only the HTTPS edge should be public.
   - Deploy a reverse proxy/load balancer with managed certificates, HTTP→HTTPS
     redirect, secure headers, and appropriate request limits. Use HTTPS for
     public S3 URLs too.
   - Bind operational services to the internal Docker network (or localhost
     only when needed for administration); firewall them at the infrastructure
     layer.

3. **Finish abuse prevention.**
   - Login and analysis are rate limited, but signup, attachment upload, forum
     posting/commenting/voting, and related expensive paths are not.
   - Add edge-level and application-level rate limits, per-user storage/usage
     quotas, signup anti-automation and email verification.
   - Stream uploads with an enforced byte limit instead of calling
     `UploadFile.read()` before applying the limit; otherwise direct backend
     access can exhaust process memory.

4. **Make session credentials resistant to theft and revocable.**
   - The web JWT is in `localStorage` and is copied into extension storage;
     XSS can exfiltrate it. Logout only clears the client copy.
   - Move the web session to secure, httpOnly, SameSite cookies or use
     short-lived access tokens plus a protected refresh flow. Implement token
     rotation/revocation and forced logout after credential compromise.

5. **Make the Chrome extension deployable.**
   - The extension and its manifest are hard-coded to localhost HTTP origins.
   - Introduce build-time environment configuration that generates both the JS
     config and manifest from one source of truth. Add a signed packaged build,
     Chrome Web Store release process, and production end-to-end tests.

6. **Decide and enforce analysis privacy.**
   - Analyses are intentionally a shared global cache: any authenticated user
     who guesses a document ID can read its URL and findings.
   - Confirm this is acceptable in the privacy model. If not, scope detail
     access to a user's history/authorization while retaining an internal
     deduplicated cache, and make externally visible IDs non-enumerable.

7. **Complete input-origin protections.**
   - Add explicit CORS allowlists and `TrustedHostMiddleware` for the deployed
     domains. Trust `X-Forwarded-*` only from the TLS proxy that strips
     caller-supplied headers.
   - Update the IP rate-limit dependency to use the validated forwarded client
     address; otherwise all proxied users share one login bucket.

8. [DONE] **Reject unsafe production JWT secrets.**
   - Non-dev startup now refuses the default secret and any secret under 32
     bytes; Compose sets `CLEARTERMS_ENVIRONMENT=prod` and requires a secret.

9. [DONE] **Introduce initial rate limiting.**
   - The `rate_limits` table supplies fixed-window limits for login, analysis,
     and direct messages. P0 item 3 extends this to remaining public writes.

10. [DONE] **Emit structured logs.**
    - JSON logging is installed for application and Uvicorn loggers. P1 still
      requires correlation IDs, access telemetry, metrics, and alerting.

## P1 — high (reliability, operations, and correctness)

1. **Use durable background jobs.**
   - The analysis queue is in-process, so queue depth, fairness, and worker
     limits break across replicas or restarts.
   - Attachment transforms run as FastAPI `BackgroundTasks`; a restart can
     leave rows permanently pending/failed with no retry.
   - Move analysis and media work to a durable broker/worker system with job
     persistence, retries, idempotency, dead-letter handling, and status
     visibility. Schedule the existing orphan-attachment sweep.

2. **Separate database migrations from web startup.**
   - `alembic upgrade head` runs in the backend container command. Multiple
     replicas can race during deployment.
   - Run migrations as a one-shot release job and make application containers
     serve only after that job succeeds.

3. **Implement liveness and readiness correctly.**
   - `/health` always returns OK. Keep it as liveness, and add readiness that
     checks database connectivity plus required object storage/model provider
     dependencies with bounded timeouts.

4. **Establish secrets, backup, and disaster-recovery controls.**
   - Use a managed secret store, least-privilege database/S3 credentials, and
     rotation. Do not rely on development defaults outside Compose.
   - Define encrypted database and object-storage backups, retention, restore
     tests, recovery objectives, and an incident runbook.

5. **Set runtime and deployment guardrails.**
   - Add CPU/memory/PID limits, autoscaling policy, model capacity planning,
     graceful shutdown timeouts, and database connection limits.
   - Pin and regularly update base images/dependencies; generate an SBOM and
     scan images and dependencies for vulnerabilities.

6. **Add production observability.**
   - Add request/correlation IDs, access logs, metrics (latency, error rate,
     queue depth, job duration, model failures), tracing, centralized error
     reporting, dashboards, alerts, and defined SLOs.

7. **Harden media processing.**
   - Run transforms in constrained workers, preserve retry/error diagnostics,
     and add malware/content scanning as appropriate. Verify deletion handles
     storage failures and does not leave private orphaned objects.

8. **Add public-service policy features.**
   - Before exposing forum/DM/media features, add moderation/reporting,
     abuse handling, account deletion/export, data-retention controls, privacy
     policy, terms of service, and support/incident processes.

## P2 — quality, testing, and maintainability

1. **Cover the frontend and extension with tests.**
   - There are no frontend component/browser tests and no extension tests.
     Add unit/component coverage plus authenticated browser E2E tests for core
     web and extension flows, uploads, failures, and deep links.

2. **Make CI match the release surface.**
   - CI currently validates backend and frontend, but does not typecheck/build
     the extension or package it for release.
   - Add extension gates, Compose/staging smoke tests, migration checks,
     security/secrets/dependency/image scanning, coverage reporting, and a
     controlled deployment/promotion pipeline.

3. **Introduce LLM quality and safety gates.**
   - Create a versioned, hand-labelled representative TOS evaluation set with
     accuracy/regression thresholds. Run it before model/prompt release.
   - Test adversarial/prompt-injection inputs, timeout/fallback behavior, and
     cost/latency budgets. Do not make legal-language claims beyond measured
     model performance.

4. **Resolve documentation drift.**
   - Update README/CLAUDE/nginx comments to match the actual queue, logging,
     CI, and extension behavior. In particular, CI does not currently run the
     documented Vitest/extension-zip gates, and nginx still says the queue is
     stubbed.

5. **Optimize the frontend delivery path.**
   - The production build reports a >500 KB JavaScript chunk. Add route-level
     code splitting and performance budgets, then measure Core Web Vitals in
     staging/production.

## Validation snapshot (2026-08-18)

- Passed: backend Ruff and mypy; frontend lint/build; extension typecheck/build;
  and `docker compose config --quiet` with injected test-only values.
- Full backend test run: 65 passed, 1 skipped, and 157 database-backed tests
  could not start because this assessment sandbox cannot access the Docker
  socket. Those errors were environmental, not failing application assertions.
