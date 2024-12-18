# Security

This document describes the security posture of the AI Evaluator Calibration
& Disagreement Analytics platform, its known limitations, and how to report
vulnerabilities.

> **Honesty note.** This project has **not** undergone a third-party security
> audit or regulatory certification. Claims below describe implemented
> controls, verified by the automated test suite; they are not an audit
> report.

## Implemented controls

| Area | Control |
| --- | --- |
| Authentication | JWT access + refresh tokens (HS256); tokens expire; refresh is required to mint a new access token. |
| Passwords | PBKDF2-HMAC-SHA256 via passlib at 600,000 iterations (OWASP-recommended), configurable via `PASSWORD_HASH_ITERATIONS`. |
| Authorization | Global roles (`admin`, `adjudicator`, `senior_reviewer`, `reviewer`) **and** per-project membership roles. Non-members receive 403 for all project data. |
| Blinding | A reviewer cannot see any peer rating for a task until they have submitted their own. Senior reviewers, adjudicators and admins may always view. |
| Rate limiting | Credential endpoints (`/register`, `/login`, `/refresh`) are rate-limited per client IP (default 60/min). |
| Input validation | Pydantic schemas on every endpoint; scale-aware score validation (range, ordinal steps, categorical membership); upload size capped (`MAX_UPLOAD_MB`). |
| Injection | All DB access via SQLAlchemy ORM / bound parameters; no string-built SQL. Frontend renders React-escaped output; no `dangerouslySetInnerHTML`. |
| Secrets | Provider API keys are Fernet-encrypted at rest, masked in API responses (`sk…3456`), and redacted from logs. `.env` is git-ignored. |
| CORS | Explicit allow-list via `CORS_ORIGINS`; credentials enabled only for listed origins. |
| Audit | Consequential actions (project/rubric changes, submissions, corrections, adjudications, membership, demo data) are written to an append-only audit log. |
| Data integrity | Submitted ratings are immutable: corrections create a new versioned row. Rubric changes create a new version; historical ratings keep their rubric version. Adjudication reopen creates a linked record rather than overwriting. |
| Errors | Unexpected exceptions return a generic message; details go to structured server logs only. |

## AI / LLM safety

- The platform is **fully functional offline**; no provider is configured by
  default and `LLM_ENABLED=false`.
- Evaluation content (prompts, responses, rationales) is **never** sent to an
  external provider unless `LLM_ENABLED=true` **and**
  `LLM_ALLOW_EVALUATION_CONTENT=true`.
- Prompts to providers treat evaluation content as untrusted data and instruct
  the model not to follow instructions contained in it (prompt-injection
  mitigation).
- All AI-generated output is labelled `AI-generated` in the UI and **never**
  mutates a rubric or an adjudication without explicit human approval.
- Usage is bounded by token caps, per-minute limits, timeouts, retries with
  backoff, and a daily cost budget (`LLM_MAX_COST_USD`).

## Known limitations

- Single-instance deployment model: the background job worker is in-process
  and the rate limiter is per-process. Horizontal scaling requires moving
  these to shared infrastructure (e.g. Redis + a queue).
- SQLite is intended for local development and small teams; production should
  use PostgreSQL (see `docker-compose.yml`).
- There is no built-in SSO/OIDC; integrate at the reverse-proxy level if
  required.
- Report files are stored on the backend filesystem under `REPORTS_DIR`;
  protect that volume.

## Reporting a vulnerability

Please report security issues privately by opening a confidential issue or
emailing the maintainers (see repository profile). Do **not** open a public
issue for an unverified vulnerability. We aim to acknowledge within 5 business
days and will coordinate disclosure with you.
