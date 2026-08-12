## P0 — blockers (security / data integrity)

1. JWT secret defaults to "change-me" with no startup guard.
config.py:32. If deployed without CLEARTERMS_JWT_SECRET, tokens are trivially forgeable → full auth bypass. Nothing fails startup if left default. Add a model_validator that refuses to boot on the dev secret when not in dev mode.

2. No rate limiting anywhere.
forum.py:324 check_rate_limit raises NotImplementedError, unwired. /auth/login → unlimited credential brute-force. /analyze → unlimited expensive LLM calls (cost/DoS). Needs real limiter (per-IP + per-user) before public.

3. Logging is a no-op.
core/logging.py = # TODO: implement. Zero observability in prod — no request logs, no error traces, no request IDs. Blind to incidents. Wire structured logging + uvicorn handler integration.

4. No TLS anywhere in the stack.
nginx serves plain HTTP; JWT + passwords cross the wire in clear. Presigned S3 URLs are http://. Need TLS termination (reverse proxy / LB) + https public endpoints.

## P1 — high (correctness / ops)

1. /health is a static {"status":"ok"}.
Returns healthy even if Postgres/Ollama/MinIO are down. Useless as an LB/k8s readiness probe. Split liveness vs readiness; readiness should ping DB.

2. Migrations run inside backend CMD.
alembic upgrade head && uvicorn. Multiple replicas race on migrate. Move to a separate one-shot job/init container; app should only serve.

3. Analysis queue is per-process (documented caveat).
Concurrency cap and fairness only hold within one uvicorn process — scale horizontally and both break. Real scaling needs an out-of-process broker (jobs as data, not callables). Blocks multi-replica.

4. Secrets management.
Compose has plaintext creds; s3 defaults minioadmin/minioadmin, JWT/db in env. Need a secrets store (or at least .env files kept out of images — now handled — plus rotation). Also backend/.env is git-tracked (currently only comments, but should be .env.example).

5. No container resource limits / DB backup.
No mem/cpu caps → Ollama can OOM the host. pgdata volume has no backup strategy. MinIO bucket set to anonymous download = media is world-readable (verify that's intended).

## P2 — medium (hardening)

1. JWT in localStorage (auth/storage.ts) — XSS-exfiltratable, no server-side revocation; logout is client-only. Consider httpOnly cookie + token invalidation.
2. No CORS / TrustedHost middleware — deliberately deferred per CLAUDE.md, but the actual prodss-origin and can't call the API until this lands.
3. s3_public_endpoint_url defaults to localhost:9000 — presigned URLs break behind a real domain until configured; easy to miss.
4. Stale doc: nginx.conf says queue.submit is stubbed but it's wired (analysis.py:63) — the 60ill holds, just fix the note.
